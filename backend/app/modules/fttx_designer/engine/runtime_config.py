"""Shared mutable run-scoped overrides for the small set of module-level
tunables the original single-file script mutated via ``globals()[key] = ...``
inside ``_apply_config_to_globals()``/``_restore_globals()`` (ported to
``pipeline.py``).

In the original monolith every pipeline function lived in ONE module, so
mutating ``globals()`` there was visible to literally every function in the
file for the rest of that run. Splitting the pipeline into separate modules
breaks that silently: a Python module's ``globals()`` is private to that
module, so ``pipeline.py`` mutating ITS OWN globals() would be invisible to
``fat_generation.py``/``homepass_assignment.py``/etc. — a run-configured
``max_box_to_customer_distance`` would quietly have no effect outside
``pipeline.py`` itself.

This module is the fix: a single shared namespace every pipeline module
reads through qualified attribute access (``runtime_config.
MAX_BOX_TO_CUSTOMER_DISTANCE`` — never ``from .config import
MAX_BOX_TO_CUSTOMER_DISTANCE``, which would bind an import-time snapshot
that later mutation can't reach), so ``pipeline.py`` mutating THIS module's
attributes is visible everywhere, exactly reproducing the original
single-file behavior.

Exactly the 8 keys ``_apply_config_to_globals()`` overrides in the source —
no more, no less. Every other module-level constant in ``config.py`` is a
true immutable constant (never touched by that function) and is safe to
import by bare name as usual.

Defaults mirror ``config.py``'s own module-level constants exactly once, at
import time; ``_apply_config_to_globals()`` overwrites them per-run from
``FTTXConfig``, ``_restore_globals()`` puts these exact defaults back
afterward.
"""

from __future__ import annotations

from . import config as _config

MAX_BOX_TO_BOX_DISTANCE = _config.MAX_BOX_TO_BOX_DISTANCE
MAX_BOX_TO_CUSTOMER_DISTANCE = _config.MAX_BOX_TO_CUSTOMER_DISTANCE
DROP_LENGTH_TOLERANCE = _config.DROP_LENGTH_TOLERANCE
SNAP_OFFSET_DISTANCE = _config.SNAP_OFFSET_DISTANCE
FAT_OFFSET_RADIUS = _config.FAT_OFFSET_RADIUS
SPLITTER_PATTERN = _config.SPLITTER_PATTERN
HOMEPASS_FIELD_NAME = _config.HOMEPASS_FIELD_NAME
PROJECT_ABBREVIATION = _config.PROJECT_ABBREVIATION
