"""Verbatim port of ``b2b_hop_limit`` and ``_b2b_endpoint`` from
``FTTx Designer — dual PON integrated.py`` — "[Fix 4] The one place any
box-to-box hop limit is decided", used by FDT borrow-candidate search, wing
chain repair, cable routing, and B2B validation alike. Its own docstring is
explicit that it reads the module global at CALL time, not import time,
because ``_apply_config_to_globals()`` rebinds ``MAX_BOX_TO_BOX_DISTANCE``
per run — exactly the runtime_config.py concern, so this reads
``runtime_config.MAX_BOX_TO_BOX_DISTANCE`` rather than a bare import.
Split into its own tiny module (like distance_oracle.py) because it is a
cross-cutting single-source-of-truth function with no natural single owner
among fdt_generation/repair/cable_routing/validation.
"""

from __future__ import annotations

from typing import Optional

from . import runtime_config as rc
from .config import MAX_FAT_TO_FAT_DISTANCE, STRICT_FAT_TO_FAT_HOP
from .geometry_compat import QgsPointXY


def b2b_hop_limit(hop_index: int) -> float:
    """[Fix 4] The one place any box-to-box hop limit is decided.

    ``hop_index`` is 0 for the FDT->FAT-01 hop and >= 1 for FAT->FAT hops,
    matching ``core_info['hop_seq'] - 1`` on the emitted cable.

    Reads the module globals at CALL time rather than caching a derived
    constant at import time. _apply_config_to_globals() rebinds
    MAX_BOX_TO_BOX_DISTANCE from the GUI on every run, so a precomputed
    B2B_HOP_LIMIT_* would silently keep enforcing the default 250 m while the
    operator believed they had changed it.
    """
    if hop_index == 0:
        return float(rc.MAX_BOX_TO_BOX_DISTANCE)
    return float(MAX_FAT_TO_FAT_DISTANCE if STRICT_FAT_TO_FAT_HOP
                 else rc.MAX_BOX_TO_BOX_DISTANCE)


def _b2b_endpoint(device) -> Optional[QgsPointXY]:
    """[Fix 5] The point a box-to-box cable actually terminates on.

    route_fdt_to_fats() routes to ``fat.offset_geometry`` (the frontage-offset
    position the FAT dot is drawn at) but every upstream check measured to
    ``snapped_geometry`` (the on-centreline projection). That is a systematic
    bias on every single hop. One convention now, and it is the one the cable
    is built against.

    FDTs have no frontage offset, so ``offset_geometry`` is absent and this
    falls through to ``snapped_geometry`` exactly as route_fdt_to_fats does.
    """
    if device is None:
        return None
    return (getattr(device, 'offset_geometry', None)
            or getattr(device, 'snapped_geometry', None)
            or getattr(device, 'geometry', None))
