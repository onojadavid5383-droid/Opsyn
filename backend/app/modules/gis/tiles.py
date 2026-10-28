# ============================================================
# OPSYN VECTOR TILES — app/modules/gis/tiles.py
#
# Builds Mapbox Vector Tiles for the live network straight from PostGIS
# (ST_AsMVT / ST_AsMVTGeom). One tile carries two source-layers:
#
#   assets   point assets   id, asset_code, asset_type, name,
#                            lifecycle_status, creation_method,
#                            capacity, used_capacity, contained,
#                            util_pct (topology.py utilisation, 0-100+)
#   cables   linestrings    id, asset_code, cable_category, name,
#                            lifecycle_status, fiber_count, length_m,
#                            route_method
#
# Only what the NETWORK mode shows goes in: design_id IS NULL, not
# deleted, lifecycle in LIVE_STATES, and each type only from its min_zoom
# (contained assets from CONTAINED_MIN_ZOOM). Zoom filtering therefore
# happens here, not in the browser.
#
# Caching: tiles are cached in Redis per tenant and per network revision
# (a digest of the tenant's latest net_* change, see revision_sql). Any
# write moves the revision, the client's tile URL carries it, so stale
# tiles are never served and nothing needs explicit invalidation.
# ============================================================

from __future__ import annotations

import re

from app.modules.gis.layer_registry import (
    ASSETS_SOURCE_LAYER, CABLES_SOURCE_LAYER, TILE_MAX_ZOOM, TILE_MIN_ZOOM,
)
from app.modules.network.asset_types import (
    CONTAINED_MIN_ZOOM, asset_types_visible_at, cable_categories_visible_at,
)
from app.modules.network.lifecycle import LIVE_STATES
from app.modules.network.topology import UTIL_CAPACITY, UTIL_JOINS, UTIL_USED

MVT_EXTENT = 4096
MVT_BUFFER = 64
MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"
CACHE_TTL_SECONDS = 3600

_REVISION_RE = re.compile(r"^[0-9a-f]{1,32}$")


def valid_tile(z: int, x: int, y: int) -> bool:
    """Tile coordinates exist at this zoom (XYZ / web-mercator scheme)."""
    if not TILE_MIN_ZOOM <= z <= TILE_MAX_ZOOM:
        return False
    n = 1 << z
    return 0 <= x < n and 0 <= y < n


def valid_revision(rev: str | None) -> bool:
    return bool(rev) and bool(_REVISION_RE.match(rev))


def cache_key(tenant_id: str, revision: str, group: str, z: int, x: int, y: int) -> str:
    return f"mvt:v1:{tenant_id}:{revision}:{group}:{z}:{x}:{y}"


def tile_params(tenant_id, z: int, x: int, y: int) -> dict:
    """Bound parameters for TILE_SQL. Zoom filtering is decided here."""
    return {
        "tid": tenant_id, "z": z, "x": x, "y": y,
        "live": list(LIVE_STATES),
        "asset_types": asset_types_visible_at(z),
        "cable_categories": cable_categories_visible_at(z),
        "show_contained": z >= CONTAINED_MIN_ZOOM,
        "extent": MVT_EXTENT, "buffer": MVT_BUFFER,
        "margin": MVT_BUFFER / MVT_EXTENT,
    }


# The envelope is widened by the buffer margin so features just outside the
# tile still draw their overlap (labels, line caps) without seams.
TILE_SQL = f"""
WITH bounds AS (
    SELECT ST_TileEnvelope(:z, :x, :y)                                    AS env_3857,
           ST_Transform(ST_TileEnvelope(:z, :x, :y, margin => :margin), 4326) AS env_4326
),
assets AS (
    SELECT ST_AsMVTGeom(ST_Transform(a.geom, 3857), b.env_3857, :extent, :buffer, true) AS geom,
           a.id::text          AS id,
           a.asset_code,
           a.asset_type,
           coalesce(a.name, '') AS name,
           a.lifecycle_status,
           a.creation_method,
           a.capacity,
           a.used_capacity,
           (a.parent_id IS NOT NULL) AS contained,
           CASE WHEN {UTIL_CAPACITY} > 0 AND {UTIL_USED} IS NOT NULL
                THEN round(100.0 * {UTIL_USED} / {UTIL_CAPACITY})::int END AS util_pct
    FROM bounds b, net_assets a
    {UTIL_JOINS}
    WHERE a.tenant_id = :tid
      AND a.deleted_at IS NULL
      AND a.design_id IS NULL
      AND a.lifecycle_status = ANY(:live)
      AND a.asset_type = ANY(:asset_types)
      AND (a.parent_id IS NULL OR :show_contained)
      AND a.geom && b.env_4326
),
cables AS (
    SELECT ST_AsMVTGeom(ST_Transform(c.geom, 3857), b.env_3857, :extent, :buffer, true) AS geom,
           c.id::text          AS id,
           c.asset_code,
           c.cable_category,
           coalesce(c.name, '') AS name,
           c.lifecycle_status,
           c.fiber_count,
           c.length_m::float8  AS length_m,
           c.route_method
    FROM net_cables c, bounds b
    WHERE c.tenant_id = :tid
      AND c.deleted_at IS NULL
      AND c.design_id IS NULL
      AND c.lifecycle_status = ANY(:live)
      AND c.cable_category = ANY(:cable_categories)
      AND c.geom && b.env_4326
)
SELECT
    coalesce((SELECT ST_AsMVT(assets, '{ASSETS_SOURCE_LAYER}', :extent, 'geom') FROM assets WHERE geom IS NOT NULL), ''::bytea)
 || coalesce((SELECT ST_AsMVT(cables, '{CABLES_SOURCE_LAYER}', :extent, 'geom') FROM cables WHERE geom IS NOT NULL), ''::bytea)
"""

# A digest that changes whenever any live-network row of the tenant is
# created, changed or soft-deleted (all of which touch updated_at).
# Connections are included: they change utilisation, which tiles carry.
REVISION_SQL = """
SELECT substr(md5(
    coalesce((SELECT max(updated_at)::text || count(*)::text FROM net_assets WHERE tenant_id = :tid AND design_id IS NULL), '')
    || '|' ||
    coalesce((SELECT max(updated_at)::text || count(*)::text FROM net_cables WHERE tenant_id = :tid AND design_id IS NULL), '')
    || '|' ||
    coalesce((SELECT max(updated_at)::text || count(*)::text FROM net_connections WHERE tenant_id = :tid AND design_id IS NULL), '')
), 1, 16)
"""

COUNTS_SQL = """
SELECT 'asset' AS kind, asset_type AS key, count(*) AS n
FROM net_assets
WHERE tenant_id = :tid AND deleted_at IS NULL AND design_id IS NULL AND lifecycle_status = ANY(:live)
GROUP BY asset_type
UNION ALL
SELECT 'cable', cable_category, count(*)
FROM net_cables
WHERE tenant_id = :tid AND deleted_at IS NULL AND design_id IS NULL AND lifecycle_status = ANY(:live)
GROUP BY cable_category
"""

BOUNDS_SQL = """
WITH live AS (
    SELECT geom FROM net_assets
    WHERE tenant_id = :tid AND deleted_at IS NULL AND design_id IS NULL AND lifecycle_status = ANY(:live)
    UNION ALL
    SELECT geom FROM net_cables
    WHERE tenant_id = :tid AND deleted_at IS NULL AND design_id IS NULL AND lifecycle_status = ANY(:live)
),
ext AS (SELECT ST_Extent(geom) AS e, count(*) AS n FROM live)
SELECT ST_XMin(e) AS min_lng, ST_YMin(e) AS min_lat, ST_XMax(e) AS max_lng, ST_YMax(e) AS max_lat, n
FROM ext
"""
