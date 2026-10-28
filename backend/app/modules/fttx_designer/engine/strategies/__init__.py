"""Deployment-strategy implementations ported from
``FTTx Designer — dual PON integrated.py``'s ``DeploymentStrategy`` Protocol
and its four concrete strategies (Aerial/Underground/Drainage/Hybrid),
selected per-run by ``_get_strategy(config)``.

Kept as their own subpackage — mirroring ``repair/``'s rationale (see that
subpackage's docstring) — because each strategy is a self-contained,
deployment-type-specific bundle (structure loading, cable/duct routing, BOQ
population, extra output layers) that the shared pipeline in
``pipeline.py`` calls through one common interface, never reaching into a
strategy's internals directly.

``base.py`` holds the ``DeploymentStrategy`` Protocol itself (dependency-
light, so every concrete strategy module can import it without pulling in
its siblings). ``aerial.py`` is the first concrete strategy ported — it
wraps existing, already-ported functions unchanged, no new logic.
Underground/Drainage/Hybrid (plus the GeoPackage-backed
``DuctOccupancyLedger``, which needs its own porting decision — see the
plan's Phase 3 notes on a Postgres-backed replacement) are ported in a
later sub-phase; ``_get_strategy`` (the dispatcher) is added once all four
exist.
"""
