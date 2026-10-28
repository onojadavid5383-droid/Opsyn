# ============================================================
# OPSYN NETWORK ATTRIBUTES — app/modules/network/attributes.py
#
# Per-type attribute schemas for net_assets.attributes and
# net_cables.attributes (Network GIS plan, Phase 2). ONE registry drives:
#   - API validation      create / update of assets and cables
#   - upload validation   the same fields are the optional upload columns,
#                         coerced from Excel cells by the same rules
#   - the UI              GET /network/catalogue serves these specs; the
#                         inspector renders and edits attributes from them
#
# Keys not in a type's spec are kept untouched (engine outputs arrive with
# their own fields; upload-era links live under legacy_*). Only known keys
# are type-checked, so nothing an import carried is ever silently dropped.
# ============================================================

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from app.modules.network.asset_types import ASSET_TYPES

MAX_TEXT = 200


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str                            # text | int | number | bool | enum
    unit: str | None = None
    options: tuple[str, ...] = field(default_factory=tuple)
    min: float | None = None
    help: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["options"] = list(self.options)
        return d


def _t(key: str, label: str, help: str | None = None) -> FieldSpec:
    return FieldSpec(key, label, "text", help=help)


def _i(key: str, label: str, unit: str | None = None, min: float = 0) -> FieldSpec:
    return FieldSpec(key, label, "int", unit=unit, min=min)


def _n(key: str, label: str, unit: str | None = None, min: float = 0) -> FieldSpec:
    return FieldSpec(key, label, "number", unit=unit, min=min)


def _e(key: str, label: str, *options: str) -> FieldSpec:
    return FieldSpec(key, label, "enum", options=options)


def _b(key: str, label: str) -> FieldSpec:
    return FieldSpec(key, label, "bool")


SPLIT_RATIOS = ("1:2", "1:4", "1:8", "1:16", "1:32", "1:64")
MOUNTS = ("POLE", "WALL", "GROUND", "HANDHOLE", "MANHOLE", "INDOOR")
OWNERSHIP = ("OWNED", "LEASED", "SHARED", "THIRD_PARTY")

_ADDRESS = _t("address", "Address")
_VENDOR = _t("vendor", "Vendor")
_MODEL = _t("model", "Model")
_STRUCTURE = _t("structure_name", "Mounted on", help="Pole, handhole or wall the device is fixed to")

ASSET_ATTRIBUTES: dict[str, tuple[FieldSpec, ...]] = {
    "POP": (_ADDRESS, _b("backup_power", "Backup power"), _i("rack_count", "Racks")),
    "SITE": (_ADDRESS, _e("site_class", "Site class", "HUB", "POP", "EXCHANGE", "DATA_CENTRE")),
    "OLT": (_VENDOR, _MODEL, _t("ip_address", "Management IP"), _i("number_of_odf", "ODFs"),
            _n("uplink_gbps", "Uplink", unit="Gbps")),
    "ROOM": (_ADDRESS, _t("floor", "Floor")),
    "RACK": (_t("room", "Room"), _t("row", "Row")),
    "ROUTER": (_VENDOR, _MODEL, _t("ip_address", "Management IP")),
    "SWITCH": (_VENDOR, _MODEL, _t("ip_address", "Management IP")),
    "WDM": (_VENDOR, _e("wdm_kind", "WDM type", "CWDM", "DWDM", "COMBINER")),
    "ODF": (_t("rack", "Rack"), _e("connector", "Connector", "SC_APC", "SC_UPC", "LC_APC", "LC_UPC")),
    "CABINET": (_i("number_tray", "Splice trays"),
                _e("cabinet_kind", "Cabinet type", "STREET", "INDOOR", "POLE_MOUNTED")),
    "FDT": (_e("splitter_ratio", "Splitter ratio", *SPLIT_RATIOS),
            _e("pon_architecture", "PON architecture", "SINGLE", "DUAL"),
            _e("mount", "Mounting", *MOUNTS), _STRUCTURE),
    "FAT": (_e("splitter_ratio", "Splitter ratio", *SPLIT_RATIOS),
            _t("parent_fdt_code", "Fed from FDT"), _t("wing", "Wing"), _i("sequence", "Position in wing", min=1),
            _e("mount", "Mounting", *MOUNTS), _STRUCTURE),
    "SPLITTER": (_i("input_ports", "Input ports", min=1), _i("output_ports", "Output ports", min=1),
                 _e("split_ratio", "Split ratio", *SPLIT_RATIOS),
                 _e("splitter_level", "Level", "First-Level", "Second-Level"),
                 _e("splitter_type", "Architecture", "PCC", "Legacy"),
                 _i("number_customer", "Customers served")),
    "CLOSURE": (_e("closure_kind", "Closure type", "DOME", "INLINE"),
                _i("tray_count", "Splice trays"), _e("mount", "Mounting", *MOUNTS), _STRUCTURE),
    "ENCLOSURE": (_e("enclosure_kind", "Enclosure type", "WALL_BOX", "TERMINAL_BOX", "PEDESTAL"),
                  _e("mount", "Mounting", *MOUNTS)),
    "POLE": (_n("height_m", "Height", unit="m"),
             _e("material", "Material", "CONCRETE", "WOOD", "STEEL", "COMPOSITE"),
             _e("ownership", "Ownership", *OWNERSHIP), _t("owner", "Owner"), _b("existing", "Existing structure")),
    "MANHOLE": (_n("depth_m", "Depth", unit="m"), _e("cover_kind", "Cover", "CAST_IRON", "COMPOSITE", "CONCRETE"),
                _e("ownership", "Ownership", *OWNERSHIP), _t("owner", "Owner")),
    "HANDHOLE": (_t("size", "Size", help="e.g. 600 x 600"), _e("ownership", "Ownership", *OWNERSHIP),
                 _t("owner", "Owner")),
    "ONU": (_t("serial_number", "Serial number"), _VENDOR, _MODEL,
            _t("customer_ref", "Customer reference")),
    "CUSTOMER_ENDPOINT": (_ADDRESS, _t("customer_ref", "Customer reference"),
                          _e("building_type", "Building", "SDU", "MDU", "BUSINESS", "INSTITUTION")),
}

CABLE_ATTRIBUTES: tuple[FieldSpec, ...] = (
    _e("cable_type", "Cable type", "ADSS", "FIGURE_8", "DUCT", "ARMOURED", "INDOOR", "FLAT_DROP"),
    _i("tube_count", "Loose tubes"),
    _e("ownership", "Ownership", *OWNERSHIP),
    _t("drum_ref", "Drum reference"),
)

assert set(ASSET_ATTRIBUTES) == set(ASSET_TYPES), "every asset type needs an attribute spec"

_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


def coerce(spec: FieldSpec, raw: Any) -> tuple[Any, str | None]:
    """(value, error). Blank → (None, None): every attribute is optional."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None, None
    try:
        if spec.kind == "text":
            s = str(raw).strip()
            if len(s) > MAX_TEXT:
                return None, f"{spec.label} is longer than {MAX_TEXT} characters"
            return s, None
        if spec.kind == "bool":
            if isinstance(raw, bool):
                return raw, None
            s = str(raw).strip().lower()
            if s in _TRUE:
                return True, None
            if s in _FALSE:
                return False, None
            return None, f"{spec.label} must be yes or no (got '{raw}')"
        if spec.kind == "enum":
            s = str(raw).strip()
            for opt in spec.options:
                if s.lower() == opt.lower():
                    return opt, None
            return None, f"{spec.label} must be one of {', '.join(spec.options)} (got '{raw}')"
        if spec.kind in ("int", "number"):
            if isinstance(raw, bool):
                raise ValueError
            num = float(str(raw).strip())
            if not math.isfinite(num):
                raise ValueError
            if spec.kind == "int":
                if num != int(num):
                    return None, f"{spec.label} must be a whole number (got '{raw}')"
                num = int(num)
            if spec.min is not None and num < spec.min:
                return None, f"{spec.label} must be at least {spec.min:g} (got {num:g})"
            return num, None
    except (TypeError, ValueError):
        return None, f"{spec.label} must be a number (got '{raw}')"
    return None, f"{spec.label} has an unsupported type"


def validate_attributes(specs: tuple[FieldSpec, ...], attrs: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Coerce the known keys; keep unknown keys as they are.

    Returns (clean, errors). Known keys that come out blank are removed, so
    clearing a field in the UI deletes it rather than storing "".
    """
    by_key = {s.key: s for s in specs}
    clean: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    for key, raw in attrs.items():
        spec = by_key.get(key)
        if spec is None:
            clean[key] = raw
            continue
        value, err = coerce(spec, raw)
        if err:
            errors.append({"field": key, "error": err})
        elif value is not None:
            clean[key] = value
    return clean, errors


def asset_specs(asset_type: str) -> tuple[FieldSpec, ...]:
    return ASSET_ATTRIBUTES.get(asset_type, ())
