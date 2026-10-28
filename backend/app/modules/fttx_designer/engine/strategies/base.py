"""Verbatim port of the ``DeploymentStrategy`` Protocol from
``FTTx Designer — dual PON integrated.py``.

No logic changes from the source script — only the QGIS types (now from
``engine.geometry_compat``) and cross-module imports. A ``Protocol`` has no
runtime behavior of its own; this module exists purely so every concrete
strategy (``aerial.py`` and, in a later sub-phase, underground/drainage/
hybrid) can import the same interface without a circular dependency on
each other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Protocol

if TYPE_CHECKING:
    from ..config import CapacityProfile, FTTXConfig
    from ..domain import FAT, FDT, CableSegment, DomeClosure, Homepass, SupportStructure
    from ..cable_routing import CableRouter
    from ..domain import RoadSegment
    from ..geometry_compat import QgsCoordinateReferenceSystem, QgsVectorLayer
    from ..perf_logger import PerformanceLogger
    from ..spatial_utils import DistanceCalculator


class DeploymentStrategy(Protocol):
    """Interface every deployment mode must satisfy.

    The pipeline in ``run_fttx_design`` calls these four methods in order,
    allowing the strategy to control structure loading, cable routing, BOQ
    population, and any mode-specific output layers — without touching the
    shared topology, FAT/FDT placement, or clustering logic.

    Phases 3+ provide concrete implementations for Underground, Drainage,
    and Hybrid.  Phase 2 provides ``AerialStrategy`` which wraps the existing
    aerial functions unchanged.
    """

    def load_structures(
        self,
        layers: Dict[str, 'QgsVectorLayer'],
        roads: Dict[int, 'RoadSegment'],
        dist_calc: 'DistanceCalculator',
        config: 'FTTXConfig',
        logger: 'PerformanceLogger',
    ) -> List['SupportStructure']:
        """Return the support structures that FATs and FDTs will snap to."""
        ...

    def route_cable(
        self,
        fdts: List['FDT'],
        cable_router: 'CableRouter',
        logger: 'PerformanceLogger',
        profile: Optional['CapacityProfile'] = None,
    ) -> List['CableSegment']:
        """Route box-to-box distribution cables and return the segments."""
        ...

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
        """Populate all BOQ layers for this deployment mode."""
        ...

    def create_extra_output_layers(
        self,
        crs: 'QgsCoordinateReferenceSystem',
        project: 'object',
        config: 'FTTXConfig',
    ) -> Dict[str, 'QgsVectorLayer']:
        """Return any deployment-specific output layers (merged with base layers).
        Return empty dict if no extra layers are needed (e.g. Aerial)."""
        ...
