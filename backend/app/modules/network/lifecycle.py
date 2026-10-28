# ============================================================
# OPSYN NETWORK LIFECYCLE — app/modules/network/lifecycle.py
#
# The one lifecycle definition for every network object (assets and
# cables, live or in a design). No module may invent its own status set:
# read it from here. Mirrored for the frontend in
# frontend/shared-types/index.ts (NetLifecycleStatus) — keep both in step.
#
# A lifecycle change is only legal along TRANSITIONS; anything else is a
# 409 from the API. Promotion (Phase 10) moves a row along this graph and
# never copies it.
# ============================================================

from __future__ import annotations

LIFECYCLE_STATES: tuple[str, ...] = (
    "DRAFT",
    "PLANNED",
    "DESIGNED",
    "UNDER_REVIEW",
    "APPROVED",
    "CONSTRUCTION",
    "INSTALLED",
    "TESTING",
    "VERIFIED",
    "ACTIVE",
    "FAULTY",
    "RETIRED",
    "REJECTED",
)

# Allowed next states. RETIRED is terminal.
TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT":        frozenset({"PLANNED", "DESIGNED"}),
    "PLANNED":      frozenset({"DRAFT", "DESIGNED"}),
    "DESIGNED":     frozenset({"PLANNED", "UNDER_REVIEW"}),
    "UNDER_REVIEW": frozenset({"APPROVED", "REJECTED"}),
    "REJECTED":     frozenset({"DESIGNED", "RETIRED"}),
    "APPROVED":     frozenset({"CONSTRUCTION"}),
    "CONSTRUCTION": frozenset({"INSTALLED"}),
    "INSTALLED":    frozenset({"TESTING"}),
    "TESTING":      frozenset({"VERIFIED", "FAULTY", "INSTALLED"}),
    "VERIFIED":     frozenset({"ACTIVE"}),
    "ACTIVE":       frozenset({"FAULTY", "RETIRED"}),
    "FAULTY":       frozenset({"ACTIVE", "RETIRED"}),
    "RETIRED":      frozenset(),
}

# What NETWORK map mode shows (together with design_id IS NULL).
LIVE_STATES: tuple[str, ...] = ("ACTIVE", "FAULTY", "VERIFIED")

# Rows imported from the pre-existing upload tables are running plant.
IMPORTED_DEFAULT_STATE = "ACTIVE"
# A manually created live asset starts as planned work.
MANUAL_DEFAULT_STATE = "PLANNED"


def can_transition(current: str, target: str) -> bool:
    """True if `current` → `target` is an allowed lifecycle move.

    Staying in the same state is not a transition and returns False, so a
    no-op PATCH never counts as a lifecycle change.
    """
    return target in TRANSITIONS.get(current, frozenset())


assert set(TRANSITIONS) == set(LIFECYCLE_STATES), "every state needs a transition entry"
assert all(t <= set(LIFECYCLE_STATES) for t in TRANSITIONS.values()), "unknown target state"
