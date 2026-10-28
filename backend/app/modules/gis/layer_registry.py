# ============================================================
# OPSYN GIS LAYER REGISTRY — app/modules/gis/layer_registry.py
#
# One server-side description of every map layer, served by GET /gis/layers
# and consumed by the frontend LayerPanel and MapLibre layer builder. The
# tile endpoint and this registry read the same min_zoom values
# (app/modules/network/asset_types.py), so a layer can never be listed as
# visible at a zoom where its tiles carry no features.
# ============================================================

from __future__ import annotations

from typing import Any

from app.modules.network.asset_types import (
    ASSET_TYPES, CABLE_CATEGORIES, CONTAINED_MIN_ZOOM, TIER_LABELS, TIERS,
)
from app.modules.network.lifecycle import LIFECYCLE_STATES, LIVE_STATES

# Tile group served at /gis/tiles/{group}/{z}/{x}/{y}.mvt, and the
# source-layer names inside each tile. Frontend constants must match.
NETWORK_GROUP = "network"
ASSETS_SOURCE_LAYER = "assets"
CABLES_SOURCE_LAYER = "cables"
TILE_GROUPS: tuple[str, ...] = (NETWORK_GROUP,)

TILE_MIN_ZOOM = 0
# Past this the client over-zooms the z-20 tiles: at 4096 extent a z-20
# tile resolves ~1 cm, far below GPS accuracy.
TILE_MAX_ZOOM = 20


def build_registry(
    asset_counts: dict[str, int], cable_counts: dict[str, int], revision: str,
) -> dict[str, Any]:
    """The /gis/layers payload. Counts are live-network features only."""
    groups: list[dict[str, Any]] = []
    for tier in TIERS:
        layers = [
            {
                "key": t.code, "label": t.label, "kind": "asset", "tier": tier,
                "min_zoom": t.min_zoom, "count": asset_counts.get(t.code, 0),
                "source_layer": ASSETS_SOURCE_LAYER,
            }
            for t in ASSET_TYPES.values() if t.tier == tier
        ]
        groups.append({"key": tier, "label": TIER_LABELS[tier], "kind": "asset", "layers": layers})
    groups.append({
        "key": "cables", "label": "Cables", "kind": "cable",
        "layers": [
            {
                "key": c.code, "label": c.label, "kind": "cable", "tier": "cables",
                "min_zoom": c.min_zoom, "count": cable_counts.get(c.code, 0),
                "source_layer": CABLES_SOURCE_LAYER,
            }
            for c in CABLE_CATEGORIES.values()
        ],
    })
    return {
        "revision": revision,
        "tiles": {
            "group": NETWORK_GROUP,
            "url_template": f"/gis/tiles/{NETWORK_GROUP}/{{z}}/{{x}}/{{y}}.mvt",
            "min_zoom": TILE_MIN_ZOOM,
            "max_zoom": TILE_MAX_ZOOM,
            "source_layers": {"assets": ASSETS_SOURCE_LAYER, "cables": CABLES_SOURCE_LAYER},
        },
        "contained_min_zoom": CONTAINED_MIN_ZOOM,
        "live_states": list(LIVE_STATES),
        "lifecycle_states": list(LIFECYCLE_STATES),
        "groups": groups,
    }
