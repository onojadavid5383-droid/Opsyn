"""Verbatim port of ``AerialStrategy`` from
``FTTx Designer — dual PON integrated.py``.

No logic changes from the source script — only the QGIS types and
cross-module imports. Thin wrappers around already-ported functions; the
source's own docstring on ``build_boq`` says it "delegates entirely to the
existing populate_boq_layer function" but the code actually calls
``populate_output_layers`` (which itself calls ``populate_boq_layer`` as
its last step, alongside writing the FDT/FAT/cable attribute layers) — a
pre-existing docstring/code mismatch in the source, not something
introduced by this port. Ported as written (calling
``populate_output_layers``), not as documented.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..cable_routing import CableRouter, route_fdt_to_fats
from ..config import (
    CapacityProfile,
    CascadeArchitecture,
    FTTXConfig,
    get_capacity_profile,
)
from ..domain import FAT, FDT, CableSegment, DomeClosure, Homepass, RoadSegment, SupportStructure
from ..errors import LayerNotFoundError
from ..geometry_compat import QgsCoordinateReferenceSystem, QgsVectorLayer
from ..output_layers import populate_output_layers
from ..perf_logger import PerformanceLogger
from ..spatial_utils import DistanceCalculator
from ..structures import _layer_to_structures
from ..cable_routing import route_legacy_fdt_to_fats_by_road


class AerialStrategy:
    """Concrete strategy for Aerial deployment.

    Thin wrappers around the existing aerial functions.  No logic changes —
    the main pipeline previously called these functions directly; now it calls
    them through the strategy interface so Underground/Hybrid can substitute
    their own implementations without touching the shared pipeline.
    """

    def __init__(self, cascade_architecture: 'CascadeArchitecture'):
        self._arch = cascade_architecture

    def load_structures(
        self,
        layers: Dict[str, 'QgsVectorLayer'],
        roads: Dict[int, 'RoadSegment'],
        dist_calc: 'DistanceCalculator',
        config: 'FTTXConfig',
        logger: 'PerformanceLogger',
    ) -> List['SupportStructure']:
        """Convert the pole layer into PoleStructure objects."""
        pole_layer = layers.get('pole')
        if not pole_layer:
            raise LayerNotFoundError("Pole layer not found in Aerial strategy.")
        structures = _layer_to_structures(pole_layer, "pole")
        logger.log(f"AerialStrategy: loaded {len(structures)} pole structures")
        return structures

    def route_cable(
        self,
        fdts: List['FDT'],
        cable_router: 'CableRouter',
        logger: 'PerformanceLogger',
        profile: Optional['CapacityProfile'] = None,
    ) -> List['CableSegment']:
        """Route using PCC or Legacy architecture, identical to original pipeline."""
        if self._arch == CascadeArchitecture.LEGACY:
            return route_legacy_fdt_to_fats_by_road(fdts, cable_router, logger)
        return route_fdt_to_fats(fdts, cable_router, logger, profile=profile)

    def build_boq(
        self,
        layers: Dict[str, 'QgsVectorLayer'],
        structures: List['SupportStructure'],
        b2b_cables: List['CableSegment'],
        fdts: List['FDT'],
        fats: List['FAT'],
        homepasses: List['Homepass'],
        closures: List['DomeClosure'],
        closure_cables: List['CableSegment'],
        pickup_cables: List['CableSegment'],
        config: 'FTTXConfig',
        logger: 'PerformanceLogger',
    ) -> None:
        """Delegate entirely to the existing populate_boq_layer function."""
        populate_output_layers(
            layers,
            layers['road'],
            layers['homepass'],
            layers.get('pole') or layers['road'],  # fallback — BOQ only reads pole count
            homepasses,
            fdts,
            fats,
            b2b_cables,
            [],          # b2c_cables passed separately after BOQ returns
            closures,
            closure_cables,
            pickup_cables,
            layers.get('pickup'),
            logger,
            coverage_pct=config.coverage_pct,
            cascade_architecture=self._arch,
            profile=get_capacity_profile(config.pon_architecture),
        )

    def create_extra_output_layers(
        self,
        crs: 'QgsCoordinateReferenceSystem',
        project: 'object',
        config: 'FTTXConfig',
    ) -> Dict[str, 'QgsVectorLayer']:
        """Aerial needs no extra output layers beyond the base set."""
        return {}
