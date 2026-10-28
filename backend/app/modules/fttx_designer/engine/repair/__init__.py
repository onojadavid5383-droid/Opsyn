"""Repair/rebalance passes ported from
``FTTx Designer — dual PON integrated.py``, kept as their own subpackage —
deliberately, per the integration plan (§8) — as a signal: CLAUDE.md flags
these functions as tightly coupled to the invariants earlier pipeline
stages produce, so this boundary tells future maintainers "these files
change together or not at all," and gives any regression-test harness a
natural place to apply extra scrutiny.
"""
