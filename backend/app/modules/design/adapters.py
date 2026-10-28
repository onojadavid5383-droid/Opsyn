# ============================================================
# OPSYN DESIGN ADAPTERS — app/modules/design/adapters.py
#
# Output adapter (Network GIS plan §3.6): the FTTx engine's output layers
# (WGS84 GeoJSON, as the run task stores them) → working-set rows. Pure: no
# database, no engine import, so the mapping has a golden test
# (tests/unit/test_auto_design.py). It is the mirror of hydrator.py, which
# reads these same rows back into engine objects — the attribute keys
# written here are the ones the hydrator reads.
#
#   fdt            → FDT     capacity = profile FDT customers; used = customers
#   fat            → FAT     capacity = ports (8); used = customers; attributes
#                            parent_fdt_code, wing, sequence, splitter_ratio,
#                            engine_splitter_type (e.g. 1x9, kept verbatim)
#                  → SPLITTER child of each FAT (its tap/terminal splitter)
#   closure        → CLOSURE capacity = feed capacity
#   pole_output    → POLE    existing = at an input pole's position
#   b2b            → BOX_TO_BOX cable, ROAD_GRAPH
#   b2c            → DROP cable, DIRECT (the engine runs drops straight to
#                            the premises; the far end is the customer, D5)
#   closure_cable  → CLOSURE_FDT cable, ROAD_GRAPH
#   feeder         → FEEDER cable, ROAD_GRAPH (starts at a pickup point,
#                            an input, not an asset)
#   FAT.parent_fdt, FDT.closure_name → FEED connections
# pickup_point, boq, boq_fdt are not network rows: the BOQ goes to the
# version's boq_snapshot, pickups stay inputs.
# ============================================================

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.modules.network.attributes import SPLIT_RATIOS

LIFECYCLE = "DESIGNED"
EXISTING_POLE_TOLERANCE_M = 1.0

AssetKey = tuple[str, str]           # (asset_type, asset_code)


@dataclass
class AssetRow:
    key: AssetKey
    lng: float
    lat: float
    name: str = ""
    capacity: int | None = None
    used_capacity: int | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    parent: AssetKey | None = None

    @property
    def asset_type(self) -> str:
        return self.key[0]

    @property
    def asset_code(self) -> str:
        return self.key[1]


@dataclass
class CableRow:
    asset_code: str
    cable_category: str
    coordinates: list[list[float]]
    route_method: str = "ROAD_GRAPH"
    fiber_count: int | None = None
    source: AssetKey | None = None
    dest: AssetKey | None = None
    name: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Adapted:
    assets: list[AssetRow] = field(default_factory=list)
    cables: list[CableRow] = field(default_factory=list)
    links: list[tuple[AssetKey, AssetKey]] = field(default_factory=list)     # FEED source → dest
    warnings: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for a in self.assets:
            out[a.asset_type] = out.get(a.asset_type, 0) + 1
        for c in self.cables:
            out[c.cable_category] = out.get(c.cable_category, 0) + 1
        return out


def _features(layers: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return list((layers.get(key) or {}).get("features") or [])


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _int(v: Any) -> int | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if math.isfinite(f) else None


def _digits(v: Any) -> int | None:
    """'24C', '8core_road_run', 12 → 24, 8, 12; nothing numeric → None."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return int(v) if v > 0 else None
    m = re.search(r"(\d+)", _s(v))
    return int(m.group(1)) if m and int(m.group(1)) > 0 else None


def _point(f: dict[str, Any]) -> tuple[float, float] | None:
    g = f.get("geometry") or {}
    if g.get("type") != "Point":
        return None
    x, y = g["coordinates"][:2]
    return float(x), float(y)


def _line(f: dict[str, Any]) -> list[list[float]] | None:
    """A cable's coordinates as one line; parts of a multi-line joined in order."""
    g = f.get("geometry") or {}
    if g.get("type") == "LineString":
        coords = [list(map(float, c[:2])) for c in g["coordinates"]]
    elif g.get("type") == "MultiLineString":
        coords = []
        for part in g["coordinates"]:
            for c in part:
                pt = list(map(float, c[:2]))
                if not coords or coords[-1] != pt:
                    coords.append(pt)
    else:
        return None
    distinct = {tuple(c) for c in coords}
    return coords if len(distinct) >= 2 else None


def _metres(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Short-distance equirectangular metres; plenty for a 1 m tolerance."""
    lat = math.radians((a[1] + b[1]) / 2)
    dx = math.radians(b[0] - a[0]) * math.cos(lat) * 6_371_000
    dy = math.radians(b[1] - a[1]) * 6_371_000
    return math.hypot(dx, dy)


def _splitter_ports(engine_type: str) -> int | None:
    m = re.fullmatch(r"\s*1\s*[x:]\s*(\d+)\s*", engine_type or "")
    return int(m.group(1)) if m else None


def adapt_engine_output(
    layers: dict[str, Any],
    *,
    fdt_capacity: int,
    fat_ports: int,
    pon_architecture: str,
    cascade: str,
    input_poles: list[tuple[float, float, str | None]] = (),
) -> Adapted:
    """Engine output layers → rows. ``input_poles``: (lng, lat, live asset
    code or None) of every pole the run was given, to mark existing poles."""
    out = Adapted()
    seen: set[AssetKey] = set()
    by_name: dict[str, AssetKey] = {}

    def add(row: AssetRow) -> AssetRow | None:
        if row.key in seen:
            out.warnings.append(f"{row.asset_type} {row.asset_code} appears twice in the engine output; kept the first")
            return None
        seen.add(row.key)
        out.assets.append(row)
        by_name.setdefault(row.asset_code, row.key)
        return row

    # ── Devices ──────────────────────────────────────────────
    for f in _features(layers, "fdt"):
        p, pt = f.get("properties") or {}, _point(f)
        code = _s(p.get("Name")) or _s(p.get("fdt_code"))
        if not pt or not code:
            out.warnings.append(f"An FDT without a name or position was skipped ({code or 'unnamed'})")
            continue
        attrs = {"pon_architecture": "DUAL" if pon_architecture == "dual_pon" else "SINGLE",
                 "pon_count": _int(p.get("pon_count")), "closure_name": _s(p.get("closure_name")) or None,
                 "road_name": _s(p.get("road_name")) or None, "structure_name": _s(p.get("structure_name")) or None,
                 "fdt_serial": _s(p.get("fdt_serial")) or None}
        if attrs["structure_name"]:
            attrs["mount"] = "POLE"
        add(AssetRow(key=("FDT", code), lng=pt[0], lat=pt[1], name=code, capacity=fdt_capacity,
                     used_capacity=_int(p.get("total_customers")) or 0,
                     attributes={k: v for k, v in attrs.items() if v is not None}))

    for f in _features(layers, "fat"):
        p, pt = f.get("properties") or {}, _point(f)
        code = _s(p.get("Name")) or _s(p.get("fat_full_code"))
        if not pt or not code:
            out.warnings.append(f"A FAT without a name or position was skipped ({code or 'unnamed'})")
            continue
        engine_split = _s(p.get("splitter_type"))
        ports = _splitter_ports(engine_split)
        ratio = f"1:{ports}" if ports and f"1:{ports}" in SPLIT_RATIOS else None
        seq = _int(p.get("fat_sequence")) or _int(p.get("cascade_order"))
        attrs = {"parent_fdt_code": _s(p.get("parent_fdt")) or None, "wing": _s(p.get("wing")) or None,
                 "sequence": seq if seq and seq >= 1 else None, "splitter_ratio": ratio,
                 "engine_splitter_type": engine_split or None, "structure_name": _s(p.get("structure_name")) or None,
                 "road_name": _s(p.get("road_name")) or None, "allocation_type": _s(p.get("allocation_type")) or None}
        if attrs["structure_name"]:
            attrs["mount"] = "POLE"
        customers = _int(p.get("total_customers")) or 0
        fat = add(AssetRow(key=("FAT", code), lng=pt[0], lat=pt[1], name=code, capacity=fat_ports,
                           used_capacity=customers, attributes={k: v for k, v in attrs.items() if v is not None}))
        if fat and ports:
            add(AssetRow(key=("SPLITTER", f"{code}-SPL"), lng=pt[0], lat=pt[1], name=f"{code} splitter",
                         capacity=ports, used_capacity=customers, parent=fat.key,
                         attributes={"input_ports": 1, "output_ports": ports, "splitter_level": "Second-Level",
                                     "splitter_type": "Legacy" if cascade == "legacy" else "PCC",
                                     "number_customer": customers, "engine_splitter_type": engine_split,
                                     **({"split_ratio": ratio} if ratio else {})}))

    for f in _features(layers, "closure"):
        p, pt = f.get("properties") or {}, _point(f)
        code = _s(p.get("Name"))
        if not pt or not code:
            out.warnings.append("A closure without a name or position was skipped")
            continue
        add(AssetRow(key=("CLOSURE", code), lng=pt[0], lat=pt[1], name=code,
                     capacity=_int(p.get("feed_capacity")), used_capacity=_int(p.get("total_FDT")),
                     attributes={k: v for k, v in {"closure_kind": "DOME", "road_name": _s(p.get("road_name")) or None,
                                                   "pickup_name": _s(p.get("pickup_name")) or None}.items() if v}))

    for f in _features(layers, "pole_output"):
        p, pt = f.get("properties") or {}, _point(f)
        code = _s(p.get("Name")) or _s(p.get("Tag"))
        if not pt or not code:
            continue
        match = next((pole for pole in input_poles if _metres(pt, (pole[0], pole[1])) <= EXISTING_POLE_TOLERANCE_M), None)
        attrs: dict[str, Any] = {"existing": match is not None}
        if match and match[2]:
            attrs["live_asset_code"] = match[2]
        if _s(p.get("Original_Name")):
            attrs["original_name"] = _s(p.get("Original_Name"))
        add(AssetRow(key=("POLE", code), lng=pt[0], lat=pt[1], name=code, attributes=attrs))

    # ── Connections: FDT feeds its FATs, a closure feeds its FDTs ──
    for a in out.assets:
        if a.asset_type == "FAT" and a.attributes.get("parent_fdt_code"):
            src = ("FDT", a.attributes["parent_fdt_code"])
            if src in seen:
                out.links.append((src, a.key))
            else:
                out.warnings.append(f"FAT {a.asset_code} names FDT {src[1]}, which is not in the output")
        if a.asset_type == "FDT" and a.attributes.get("closure_name"):
            src = ("CLOSURE", a.attributes["closure_name"])
            if src in seen:
                out.links.append((src, a.key))

    # ── Cables ───────────────────────────────────────────────
    codes: set[str] = set()

    def cable(f: dict[str, Any], category: str, code: str, **kw: Any) -> None:
        coords = _line(f)
        if coords is None:
            out.warnings.append(f"{category.replace('_', ' ').lower()} cable {code or '(unnamed)'} has no length "
                                "(both ends at the same spot), so it was not drawn")
            return
        base = code or f"{category}-{len(out.cables) + 1}"
        unique, n = base, 1
        while unique in codes:               # drops to a multi-unit homepass share a name stem
            n += 1
            unique = f"{base}-{n}"
        codes.add(unique)
        out.cables.append(CableRow(asset_code=unique, cable_category=category, coordinates=coords, name=code, **kw))

    def ref(name: Any) -> AssetKey | None:
        return by_name.get(_s(name))

    for f in _features(layers, "b2b"):
        p = f.get("properties") or {}
        cable(f, "BOX_TO_BOX", _s(p.get("name")), fiber_count=_digits(p.get("cable_type")),
              source=ref(p.get("start_device")), dest=ref(p.get("end_device")),
              attributes={k: v for k, v in {"fdt_code": _s(p.get("fdt_id")), "wing": _s(p.get("wing")),
                                            "tap_sequence": _s(p.get("tap_sequence")), "cable_type": _s(p.get("cable_type")),
                                            "cable_arch": _s(p.get("cable_arch"))}.items() if v})
    for f in _features(layers, "b2c"):
        p = f.get("properties") or {}
        cable(f, "DROP", _s(p.get("name")), route_method="DIRECT", source=ref(p.get("fat_name")),
              attributes={"customer_id": _int(p.get("customer_id"))})
    for f in _features(layers, "closure_cable"):
        p = f.get("properties") or {}
        cable(f, "CLOSURE_FDT", _s(p.get("name")), fiber_count=_digits(p.get("cable_capacity")),
              source=ref(p.get("start_device")) or ref(p.get("closure_name")), dest=ref(p.get("end_device")) or ref(p.get("fdt_id")),
              attributes={k: v for k, v in {"closure_name": _s(p.get("closure_name")), "fdt_code": _s(p.get("fdt_id")),
                                            "cascade_group": _s(p.get("cascade_group"))}.items() if v})
    for f in _features(layers, "feeder"):
        p = f.get("properties") or {}
        cable(f, "FEEDER", _s(p.get("name")), fiber_count=_int(p.get("total_core")) or None,
              source=ref(p.get("start_device")), dest=ref(p.get("end_device")),
              attributes={k: v for k, v in {"pickup": _s(p.get("start_device")), "active_core": _int(p.get("active_core")),
                                            "redundant_core": _int(p.get("redundant_core")),
                                            "cable_type": _s(p.get("cable_type"))}.items() if v})
    return out
