# ============================================================
# OPSYN NETWORK ASSET TYPES — app/modules/network/asset_types.py
#
# The registry of what can live in net_assets / net_cables, and at which
# zoom each kind appears on the map. The GIS layer registry
# (app/modules/gis/layer_registry.py) and the MVT tile query both read
# min_zoom from here, so the layer panel and the tiles can never disagree
# about what is visible.
#
# Zoom bands (Network GIS plan §3.8):
#   ≤ 11   POP / OLT / cabinet / FDT and the feeder
#   12–14  + FAT, closures, splitters, poles, distribution cables
#   15–17  + drops, ONUs, customer endpoints
#   ≥ 18   + assets contained in another asset (parent_id set)
#
# Tier groups the types for the layer panel and gives each group its own
# marker colour on the map; the type itself is carried by the glyph.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass

TIERS: tuple[str, ...] = ("core", "distribution", "civil", "customer")

TIER_LABELS: dict[str, str] = {
    "core":         "Core and active equipment",
    "distribution": "Distribution",
    "civil":        "Civil and support structures",
    "customer":     "Customer premises",
}


@dataclass(frozen=True)
class AssetType:
    code: str
    label: str
    tier: str
    min_zoom: int
    # Prefix for generated codes (FAT → FAT-0014), see codes.py
    code_prefix: str
    # What net_assets.capacity counts for this type; None = not used
    capacity_label: str | None = None


ASSET_TYPES: dict[str, AssetType] = {t.code: t for t in (
    AssetType("POP",               "POP",               "core",         0, "POP"),
    AssetType("SITE",              "Site",              "core",         0, "SITE"),
    AssetType("OLT",               "OLT",               "core",         0, "OLT",  "PON ports"),
    AssetType("ROOM",              "Equipment room",    "core",        12, "ROOM"),
    AssetType("RACK",              "Rack",              "core",        12, "RACK", "Rack units"),
    AssetType("ROUTER",            "Router",            "core",        12, "RTR",  "Ports"),
    AssetType("SWITCH",            "Switch",            "core",        12, "SW",   "Ports"),
    AssetType("WDM",               "WDM",               "core",        12, "WDM",  "Channels"),
    AssetType("ODF",               "ODF",               "core",         8, "ODF",  "Ports"),
    AssetType("CABINET",           "Cabinet",           "distribution", 8, "CAB",  "Fibre capacity"),
    AssetType("FDT",               "FDT",               "distribution", 8, "FDT",  "Customer ports"),
    AssetType("FAT",               "FAT",               "distribution", 12, "FAT", "Customer ports"),
    AssetType("SPLITTER",          "Splitter",          "distribution", 12, "SPL", "Output ports"),
    AssetType("CLOSURE",           "Closure",           "distribution", 12, "CLS", "Splice capacity"),
    AssetType("ENCLOSURE",         "Enclosure",         "distribution", 12, "ENC", "Ports"),
    AssetType("POLE",              "Pole",              "civil",        13, "POLE"),
    AssetType("MANHOLE",           "Manhole",           "civil",        13, "MH"),
    AssetType("HANDHOLE",          "Handhole",          "civil",        13, "HH"),
    AssetType("ONU",               "ONU",               "customer",     15, "ONU", "LAN ports"),
    AssetType("CUSTOMER_ENDPOINT", "End point",         "customer",     15, "EP"),
)}

ASSET_TYPE_CODES: tuple[str, ...] = tuple(ASSET_TYPES)

# Contained assets (a splitter inside a cabinet, a card in a rack) only
# appear once the map is close enough to separate them from their parent.
CONTAINED_MIN_ZOOM = 18


@dataclass(frozen=True)
class CableCategory:
    code: str
    label: str
    min_zoom: int
    code_prefix: str


CABLE_CATEGORIES: dict[str, CableCategory] = {c.code: c for c in (
    CableCategory("FEEDER",       "Feeder",         0, "FDR"),
    CableCategory("PICKUP",       "Pickup",         8, "PKP"),
    CableCategory("CLOSURE_FDT",  "Closure to FDT", 8, "CFD"),
    CableCategory("DISTRIBUTION", "Distribution",  12, "DST"),
    CableCategory("BOX_TO_BOX",   "Box to box",    12, "B2B"),
    CableCategory("DROP",         "Drop",          15, "DRP"),
    CableCategory("INTERNAL",     "Internal",      18, "INT"),
)}

CABLE_CATEGORY_CODES: tuple[str, ...] = tuple(CABLE_CATEGORIES)

CREATION_METHODS: tuple[str, ...] = ("AUTO", "MANUAL", "IMPORTED", "FIELD")

# How a cable's geometry was produced. ROAD_GRAPH is the default for every
# infrastructure-to-infrastructure connection (Dijkstra over the road
# graph); MANUAL_GEOMETRY marks a free-drawn line and raises a validation
# warning once validation exists (Phase 4); IMPORTED is surveyed / as-built
# geometry brought in by upload (migration 0088) — real plant, so it is
# neither re-routed nor flagged. DIRECT is a straight line by design: the
# engine's drop cables, FAT straight to the premises (migration 0091).
ROUTE_METHODS: tuple[str, ...] = ("ROAD_GRAPH", "MANUAL_GEOMETRY", "IMPORTED", "DIRECT")

INSTALLATION_TYPES: tuple[str, ...] = (
    "AERIAL", "UNDERGROUND", "DUCT", "DIRECT_BURIED", "DRAINAGE", "INDOOR",
)

# How one asset feeds the next (net_connections.connection_type, Phase 3).
# Connections point downstream: source is nearer the OLT, dest nearer the
# customer.
CONNECTION_TYPES: tuple[str, ...] = ("FEED", "SPLIT", "SPLICE", "PATCH", "DROP", "UPLINK")

# Types a trace upstream is trying to reach.
ROOT_TYPES: tuple[str, ...] = ("OLT", "POP", "SITE")
# Types that count as a served customer in a downstream trace.
CUSTOMER_TYPES: tuple[str, ...] = ("ONU", "CUSTOMER_ENDPOINT")

# TIA-598 colour sequence for fibres and loose tubes (1 → 12, then repeats).
TIA_598_COLOURS: tuple[tuple[str, str], ...] = (
    ("Blue", "#1F5FD8"), ("Orange", "#F28A1E"), ("Green", "#2E9D4A"), ("Brown", "#8B5A2B"),
    ("Slate", "#708090"), ("White", "#F4F4F4"), ("Red", "#D62828"), ("Black", "#1A1A1A"),
    ("Yellow", "#F2C80F"), ("Violet", "#7B3FB8"), ("Rose", "#F08CB4"), ("Aqua", "#2EC4C8"),
)
FIBRES_PER_TUBE = 12
FIBER_STATUSES: tuple[str, ...] = ("FREE", "USED", "RESERVED", "FAULTY", "DARK")

PORT_TYPES: tuple[str, ...] = (
    "PON", "UPLINK", "SPLITTER_IN", "SPLITTER_OUT", "FAT_OUT", "ODF", "ETHERNET",
)
PORT_STATUSES: tuple[str, ...] = ("FREE", "USED", "RESERVED", "FAULTY")


def asset_types_visible_at(zoom: int) -> list[str]:
    """Asset type codes whose min_zoom is at or below `zoom`, in registry order."""
    return [t.code for t in ASSET_TYPES.values() if t.min_zoom <= zoom]


def cable_categories_visible_at(zoom: int) -> list[str]:
    """Cable category codes whose min_zoom is at or below `zoom`."""
    return [c.code for c in CABLE_CATEGORIES.values() if c.min_zoom <= zoom]


assert all(t.tier in TIERS for t in ASSET_TYPES.values()), "unknown tier"
_prefixes = [t.code_prefix for t in ASSET_TYPES.values()] + [c.code_prefix for c in CABLE_CATEGORIES.values()]
assert len(_prefixes) == len(set(_prefixes)), "code prefixes must be unique"
