# ============================================================
# OPSYN NETWORK TOPOLOGY — app/modules/network/topology.py
#
# Phase 3: explicit topology, tracing and utilisation.
#
# CONNECTIONS (net_connections) point downstream: source feeds dest.
# They come from explicit data only — never from proximity:
#   manual     made by hand (source_table NULL)
#   derived    kept in step with other explicit data by the rules below:
#     net_cables           a cable whose two endpoints are set
#     attr:parent_splitter an uploaded splitter's parent splitter      (SPLIT)
#     attr:cabinet         an uploaded splitter's cabinet, when it has
#                          no parent splitter (a second-level splitter is
#                          fed by its parent, not by the cabinet)        (PATCH)
#     attr:parent_fdt      a FAT's parent_fdt_code matching exactly one
#                          live FDT                                      (FEED)
#   sync_derived_connections() re-applies every rule for a tenant; it is
#   idempotent (keyed by source_table/source_id) and retires derived rows
#   whose data went away. Any connection touching a soft-deleted asset is
#   retired too. Migration 0089 runs the same statements once.
#
# TRACE walks the connections with a recursive CTE (depth cap, cycle guard
# via the path array, row cap) upstream towards the OLT or downstream to
# everything fed.
#
# UTILISATION has ONE definition (UTIL_* SQL), used by the per-asset API
# and by the MVT tiles, so the map and the inspector can never disagree:
#   OLT        PON ports in use / PON ports      (when net_ports exist)
#   FDT        ports of connected FATs / FDT ports
#   FAT, SPLITTER, ODF, ENCLOSURE
#              connected downstream assets / capacity
#   otherwise  the recorded used_capacity (or an upload's number_customer)
#   `basis` says which applied, so a number is never shown without where
#   it came from.
# ============================================================

from __future__ import annotations

from typing import Any

from app.modules.network.asset_types import FIBRES_PER_TUBE, TIA_598_COLOURS

# ── Derived connections ──────────────────────────────────────

_UUID_RE = "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def _tenant(alias: str) -> str:
    return f"(CAST(:tid AS uuid) IS NULL OR {alias}.tenant_id = CAST(:tid AS uuid))"


def _live(alias: str) -> str:
    return f"{alias}.deleted_at IS NULL AND {alias}.design_id IS NULL"


def _uuid_attr(alias: str, key: str) -> str:
    """An attribute read as a uuid — only when it looks like one, so a single
    malformed value cannot abort the whole sync."""
    return (f"(CASE WHEN {alias}.attributes->>'{key}' ~* '{_UUID_RE}' "
            f"THEN CAST({alias}.attributes->>'{key}' AS uuid) END)")


# (source_table, SELECT yielding: tenant_id, source_asset_id, dest_asset_id,
#  via_cable_id, connection_type, lifecycle_status, source_id)
DERIVED_RULES: tuple[tuple[str, str], ...] = (
    ("net_cables", f"""
        SELECT c.tenant_id, c.source_asset_id, c.dest_asset_id, c.id AS via_cable_id,
               CASE c.cable_category WHEN 'DROP' THEN 'DROP' ELSE 'FEED' END AS connection_type,
               c.lifecycle_status, c.id AS source_id
        FROM net_cables c
        JOIN net_assets s ON s.id = c.source_asset_id AND {_live('s')}
        JOIN net_assets d ON d.id = c.dest_asset_id   AND {_live('d')}
        WHERE c.deleted_at IS NULL AND c.design_id IS NULL
          AND c.source_asset_id <> c.dest_asset_id
          AND {_tenant('c')}
    """),
    ("attr:parent_splitter", f"""
        SELECT x.tenant_id, p.id AS source_asset_id, x.id AS dest_asset_id, NULL::uuid AS via_cable_id,
               'SPLIT' AS connection_type, 'ACTIVE' AS lifecycle_status, x.id AS source_id
        FROM net_assets x
        JOIN net_assets p ON p.id = {_uuid_attr('x', 'legacy_parent_splitter_asset_id')}
                         AND {_live('p')} AND p.tenant_id = x.tenant_id
        WHERE x.asset_type = 'SPLITTER' AND {_live('x')}
          AND p.id <> x.id
          AND {_tenant('x')}
    """),
    ("attr:cabinet", f"""
        SELECT x.tenant_id, cab.id AS source_asset_id, x.id AS dest_asset_id, NULL::uuid AS via_cable_id,
               'PATCH' AS connection_type, 'ACTIVE' AS lifecycle_status, x.id AS source_id
        FROM net_assets x
        JOIN net_assets cab ON cab.id = {_uuid_attr('x', 'legacy_cabinet_asset_id')}
                           AND {_live('cab')} AND cab.tenant_id = x.tenant_id
        WHERE x.asset_type = 'SPLITTER' AND {_live('x')}
          AND NOT x.attributes ? 'legacy_parent_splitter_asset_id'
          AND {_tenant('x')}
    """),
    ("attr:parent_fdt", f"""
        SELECT x.tenant_id, f.id AS source_asset_id, x.id AS dest_asset_id, NULL::uuid AS via_cable_id,
               'FEED' AS connection_type, 'ACTIVE' AS lifecycle_status, x.id AS source_id
        FROM net_assets x
        JOIN LATERAL (
            SELECT min(f0.id::text)::uuid AS id, count(*) AS n
            FROM net_assets f0
            WHERE f0.tenant_id = x.tenant_id AND f0.asset_type = 'FDT' AND {_live('f0')}
              AND lower(f0.asset_code) = lower(x.attributes->>'parent_fdt_code')
        ) f ON f.n = 1
        WHERE x.asset_type = 'FAT' AND {_live('x')}
          AND coalesce(x.attributes->>'parent_fdt_code', '') <> ''
          AND {_tenant('x')}
    """),
)

DERIVED_SOURCES: tuple[str, ...] = tuple(t for t, _ in DERIVED_RULES)


def _upsert(source_table: str, select_sql: str) -> str:
    return f"""
    WITH rule AS ({select_sql})
    INSERT INTO net_connections (tenant_id, source_asset_id, dest_asset_id, via_cable_id,
                                 connection_type, lifecycle_status, source_table, source_id)
    SELECT r.tenant_id, r.source_asset_id, r.dest_asset_id, r.via_cable_id,
           r.connection_type, r.lifecycle_status, '{source_table}', r.source_id
    FROM rule r
    ON CONFLICT (tenant_id, source_table, source_id) WHERE source_table IS NOT NULL
    DO UPDATE SET source_asset_id  = EXCLUDED.source_asset_id,
                  dest_asset_id    = EXCLUDED.dest_asset_id,
                  via_cable_id     = EXCLUDED.via_cable_id,
                  connection_type  = EXCLUDED.connection_type,
                  lifecycle_status = EXCLUDED.lifecycle_status,
                  deleted_at = NULL, deleted_by = NULL, updated_at = now()
    WHERE net_connections.deleted_at IS NOT NULL
       OR (net_connections.source_asset_id, net_connections.dest_asset_id, net_connections.via_cable_id,
           net_connections.connection_type, net_connections.lifecycle_status)
          IS DISTINCT FROM
          (EXCLUDED.source_asset_id, EXCLUDED.dest_asset_id, EXCLUDED.via_cable_id,
           EXCLUDED.connection_type, EXCLUDED.lifecycle_status)
    """


def _retire(source_table: str, select_sql: str) -> str:
    return f"""
    WITH rule AS ({select_sql})
    UPDATE net_connections n SET deleted_at = now(), updated_at = now()
    WHERE n.source_table = '{source_table}' AND n.deleted_at IS NULL
      AND {_tenant('n')}
      AND NOT EXISTS (SELECT 1 FROM rule r WHERE r.source_id = n.source_id)
    """


RETIRE_DEAD_ENDPOINTS = f"""
UPDATE net_connections n SET deleted_at = now(), updated_at = now()
WHERE n.deleted_at IS NULL AND {_tenant('n')}
  AND EXISTS (SELECT 1 FROM net_assets a
              WHERE a.id IN (n.source_asset_id, n.dest_asset_id) AND a.deleted_at IS NOT NULL)
"""

SYNC_STATEMENTS: tuple[str, ...] = (
    *(_upsert(t, sql) for t, sql in DERIVED_RULES),
    *(_retire(t, sql) for t, sql in DERIVED_RULES),
    RETIRE_DEAD_ENDPOINTS,
)


async def sync_derived_connections(db, tenant_id) -> None:
    """Bring a tenant's derived connections in line with its data (idempotent)."""
    from sqlalchemy import text

    params = {"tid": str(tenant_id)}
    for stmt in SYNC_STATEMENTS:
        await db.execute(text(stmt), params)


# ── Trace ────────────────────────────────────────────────────

MAX_DEPTH = 64
MAX_TRACE_ROWS = 5000


def trace_sql(direction: str) -> str:
    """Recursive walk from :id. upstream follows dest→source, downstream source→dest.

    Each row is one reached asset with the connection it was reached by
    (`from_id` is the asset it was reached from). A diamond can reach an
    asset twice; the caller keeps the shallowest.
    """
    if direction == "upstream":
        step, nxt = "c.dest_asset_id = w.asset_id", "c.source_asset_id"
    else:
        step, nxt = "c.source_asset_id = w.asset_id", "c.dest_asset_id"
    return f"""
    WITH RECURSIVE walk(asset_id, from_id, depth, path, conn_id, via_cable_id, connection_type) AS (
        SELECT CAST(:id AS uuid), NULL::uuid, 0, ARRAY[CAST(:id AS uuid)], NULL::uuid, NULL::uuid, NULL::varchar
        UNION ALL
        SELECT {nxt}, w.asset_id, w.depth + 1, w.path || {nxt}, c.id, c.via_cable_id, c.connection_type
        FROM walk w
        JOIN net_connections c ON {step}
        WHERE c.tenant_id = :tid AND c.deleted_at IS NULL AND c.design_id IS NULL
          AND w.depth < :max_depth
          AND NOT ({nxt} = ANY(w.path))
    )
    SELECT w.asset_id, w.from_id, w.depth, w.conn_id, w.via_cable_id, w.connection_type,
           a.asset_code, a.asset_type, a.name, a.lifecycle_status,
           ST_X(ST_PointOnSurface(a.geom)) AS lng, ST_Y(ST_PointOnSurface(a.geom)) AS lat,
           cb.asset_code AS cable_code, cb.cable_category, cb.length_m::float8 AS cable_length_m
    FROM walk w
    JOIN net_assets a ON a.id = w.asset_id AND a.deleted_at IS NULL AND a.tenant_id = :tid
    LEFT JOIN net_cables cb ON cb.id = w.via_cable_id AND cb.deleted_at IS NULL
    ORDER BY w.depth, a.asset_code
    LIMIT :cap
    """


CABLE_GEOMETRY_SQL = """
SELECT id::text AS id, asset_code, cable_category, ST_AsGeoJSON(geom, 7) AS geojson
FROM net_cables WHERE id = ANY(:ids) AND tenant_id = :tid AND deleted_at IS NULL
"""


def shallowest(rows: list[Any]) -> list[Any]:
    """Keep each asset once, at the first (shallowest) depth it was reached."""
    seen: set[Any] = set()
    out = []
    for r in rows:
        if r.asset_id in seen:
            continue
        seen.add(r.asset_id)
        out.append(r)
    return out


# ── Utilisation ──────────────────────────────────────────────
# Needs the asset aliased as `a`; add UTIL_JOINS to the FROM clause.

UTIL_JOINS = """
LEFT JOIN LATERAL (
    SELECT count(*) AS n_children,
           coalesce(sum(ch.capacity) FILTER (WHERE ch.asset_type = 'FAT'), 0) AS fat_ports
    FROM net_connections k
    JOIN net_assets ch ON ch.id = k.dest_asset_id AND ch.deleted_at IS NULL
    WHERE k.source_asset_id = a.id AND k.deleted_at IS NULL AND k.design_id IS NULL
) kids ON true
LEFT JOIN LATERAL (
    SELECT count(*) AS pon_total, count(*) FILTER (WHERE p.status = 'USED') AS pon_used
    FROM net_ports p WHERE p.asset_id = a.id AND p.port_type = 'PON'
) pons ON true
"""

_COUNTED = "('FAT', 'SPLITTER', 'ODF', 'ENCLOSURE')"
_RECORDED = ("coalesce(a.used_capacity, CASE WHEN a.attributes->>'number_customer' ~ '^[0-9]+$' "
             "THEN (a.attributes->>'number_customer')::int END)")

UTIL_CAPACITY = "(CASE WHEN a.asset_type = 'OLT' AND pons.pon_total > 0 THEN pons.pon_total ELSE a.capacity END)"

UTIL_USED = f"""(CASE
    WHEN a.asset_type = 'OLT' AND pons.pon_total > 0 THEN pons.pon_used
    WHEN a.asset_type = 'FDT' AND kids.fat_ports > 0 THEN kids.fat_ports
    WHEN a.asset_type IN {_COUNTED} AND kids.n_children > 0 THEN kids.n_children
    ELSE {_RECORDED}
END)"""

UTIL_BASIS = f"""(CASE
    WHEN a.asset_type = 'OLT' AND pons.pon_total > 0 THEN 'ports'
    WHEN a.asset_type = 'FDT' AND kids.fat_ports > 0 THEN 'fat_ports'
    WHEN a.asset_type IN {_COUNTED} AND kids.n_children > 0 THEN 'connections'
    WHEN {_RECORDED} IS NOT NULL THEN 'recorded'
    ELSE 'none'
END)"""

WARN_PCT = 70
CRITICAL_PCT = 90


def util_state(capacity: int | None, used: int | None) -> tuple[float | None, str]:
    """(percent, state). State: ok | warning | critical | full | unknown."""
    if not capacity or used is None:
        return None, "unknown"
    pct = round(100.0 * used / capacity, 1)
    if used > capacity:
        return pct, "full"
    if pct >= CRITICAL_PCT:
        return pct, "critical"
    if pct >= WARN_PCT:
        return pct, "warning"
    return pct, "ok"


# ── Fibres ───────────────────────────────────────────────────

def fibre_colour(n: int) -> tuple[str, str]:
    """TIA-598 colour (name, hex) of position n (1-based) in its group of 12."""
    return TIA_598_COLOURS[(n - 1) % len(TIA_598_COLOURS)]


def fibres_for(fiber_count: int | None, stored: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Every fibre of a cable: stored rows where recorded, FREE otherwise."""
    out = []
    for n in range(1, (fiber_count or 0) + 1):
        tube = (n - 1) // FIBRES_PER_TUBE + 1
        pos = (n - 1) % FIBRES_PER_TUBE + 1
        colour, hex_ = fibre_colour(pos)
        tube_colour, tube_hex = fibre_colour(tube)
        rec = stored.get(n, {})
        out.append({
            "fiber_no": n, "tube_no": tube, "position": pos,
            "colour": colour, "colour_hex": hex_, "tube_colour": tube_colour, "tube_colour_hex": tube_hex,
            "status": rec.get("status", "FREE"), "recorded": n in stored,
        })
    return out
