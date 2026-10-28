"""Verbatim port of the exception hierarchy from
``FTTx Designer — dual PON integrated.py``. Pure Python, zero QGIS
dependency in the source already.
"""

from __future__ import annotations


class FTTXError(Exception):
    """Base exception for FTTX design errors"""
    pass


class LayerNotFoundError(FTTXError):
    """Raised when required layer is not found"""
    pass


class CRSError(FTTXError):
    """Raised when CRS is invalid"""
    pass


class ValidationError(FTTXError):
    """Raised when validation fails"""
    pass


class DesignCancelledError(FTTXError):
    """Raised from inside run_fttx_design's _update_progress checkpoint when
    a cancellation was requested. Cooperative cancellation only — never a
    forced task termination — so it's always raised at an existing progress
    checkpoint between pipeline stages, letting the same try/finally in
    run_fttx_design close the occupancy ledger and run log exactly as it
    would on any other exception path. In the web port this is what
    POST /fttx-designer/runs/{run_id}/cancel's cooperative-cancellation flag
    triggers, replacing the PyQt GUI's Cancel button."""
    pass
