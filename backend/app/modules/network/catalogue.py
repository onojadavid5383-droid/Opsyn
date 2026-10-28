# ============================================================
# OPSYN NETWORK CATALOGUE — app/modules/network/catalogue.py
#
# GET /network/catalogue: everything the UI needs to know about what can
# be stored — asset types and cable categories with their code prefixes,
# capacity meaning and attribute fields, plus the enum vocabularies. The
# frontend builds its inspector sections, edit forms and registry filters
# from this, so it never keeps a second copy of the schema.
# ============================================================

from __future__ import annotations

from typing import Any

from app.modules.network.asset_types import (
    ASSET_TYPES, CABLE_CATEGORIES, CONNECTION_TYPES, CREATION_METHODS, FIBER_STATUSES,
    INSTALLATION_TYPES, ROUTE_METHODS, TIER_LABELS, TIERS,
)
from app.modules.network.attributes import ASSET_ATTRIBUTES, CABLE_ATTRIBUTES
from app.modules.network.codes import PAD
from app.modules.network.lifecycle import LIFECYCLE_STATES, LIVE_STATES, TRANSITIONS
from app.modules.network.topology import CRITICAL_PCT, WARN_PCT


def build_catalogue() -> dict[str, Any]:
    return {
        "tiers": [{"key": t, "label": TIER_LABELS[t]} for t in TIERS],
        "asset_types": [
            {
                "code": t.code, "label": t.label, "tier": t.tier, "min_zoom": t.min_zoom,
                "code_prefix": t.code_prefix, "code_example": f"{t.code_prefix}-{1:0{PAD}d}",
                "capacity_label": t.capacity_label,
                "attributes": [f.as_dict() for f in ASSET_ATTRIBUTES[t.code]],
            }
            for t in ASSET_TYPES.values()
        ],
        "cable_categories": [
            {
                "code": c.code, "label": c.label, "min_zoom": c.min_zoom,
                "code_prefix": c.code_prefix, "code_example": f"{c.code_prefix}-{1:0{PAD}d}",
                "attributes": [f.as_dict() for f in CABLE_ATTRIBUTES],
            }
            for c in CABLE_CATEGORIES.values()
        ],
        "lifecycle_states": list(LIFECYCLE_STATES),
        "live_states": list(LIVE_STATES),
        "transitions": {k: sorted(v) for k, v in TRANSITIONS.items()},
        "creation_methods": list(CREATION_METHODS),
        "route_methods": list(ROUTE_METHODS),
        "installation_types": list(INSTALLATION_TYPES),
        "connection_types": list(CONNECTION_TYPES),
        "fiber_statuses": list(FIBER_STATUSES),
        "utilisation_thresholds": {"warning": WARN_PCT, "critical": CRITICAL_PCT},
    }
