# ============================================================
# OPSYN INFRASTRUCTURE — cascade soft-delete
# tests/integration/test_infra_cascade_delete.py
#
# Closes FTTX_INFRASTRUCTURE_FIXES.md "Remaining Issues" #2:
# "Missing Cascade Soft-Delete on Splitter Hierarchy".
#
# splitter_boxes.cabinet_id and splitter_boxes.parent_splitter_id are both
# ON DELETE SET NULL, and the deletion workflow soft-deletes rather than
# deleting, so neither FK ever fires. Before this change, deleting a cabinet
# left its splitters live and active but pointing at nothing, and deleting a
# First-Level splitter left its Second-Level children orphaned.
#
# These run against the real database via the db_session fixture rather than
# mocked, because the walk is a recursive query and a mock would only be
# asserting that the mock returns what it was told to.
# ============================================================

import uuid

import pytest
from sqlalchemy import select

from app.modules.infrastructure.deletion_service import (
    collect_cascade_targets,
    _MAX_CASCADE_DEPTH,
)
from app.modules.infrastructure.gis_utils import make_point
from app.modules.infrastructure.models import Cabinet, SplitterBox
from app.modules.tenants.models import Tenant


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════

@pytest.fixture
async def tenant(db_session):
    t = Tenant(name="Cascade Test", slug=f"cascade-{uuid.uuid4().hex[:12]}")
    db_session.add(t)
    await db_session.flush()
    return t


# Lagos, roughly. `location` is NOT NULL on all three asset tables, so it has
# to be built the same way upload_service builds it.
_LNG, _LAT = 3.3792, 6.5244


def _cabinet(tenant, cabinet_id="CAB-001"):
    return Cabinet(
        tenant_id=tenant.id,
        cabinet_id=cabinet_id,
        capacity=48,
        number_tray=4,
        longitude=_LNG,
        latitude=_LAT,
        location=make_point(_LNG, _LAT),
    )


def _splitter(tenant, box_id, level="Second-Level", stype="PCC",
              cabinet=None, parent=None):
    return SplitterBox(
        tenant_id=tenant.id,
        box_id=box_id,
        input_ports=1,
        output_ports=8,
        splitter_level=level,
        splitter_type=stype,
        longitude=_LNG,
        latitude=_LAT,
        location=make_point(_LNG, _LAT),
        cabinet_id=cabinet.id if cabinet else None,
        parent_splitter_id=parent.id if parent else None,
    )


# ══════════════════════════════════════════════════════════════
#  collect_cascade_targets
# ══════════════════════════════════════════════════════════════

class TestCascadeFromSplitter:

    @pytest.mark.asyncio
    async def test_first_level_takes_its_second_level_children(self, db_session, tenant):
        first = _splitter(tenant, "FL-001", level="First-Level")
        db_session.add(first)
        await db_session.flush()

        child_a = _splitter(tenant, "SL-001", parent=first)
        child_b = _splitter(tenant, "SL-002", parent=first)
        db_session.add_all([child_a, child_b])
        await db_session.flush()

        explicit, cascaded = await collect_cascade_targets(
            db_session, "splitter", [first.id], tenant.id
        )

        assert explicit == [first.id]
        assert set(cascaded) == {child_a.id, child_b.id}

    @pytest.mark.asyncio
    async def test_walks_more_than_one_level_down(self, db_session, tenant):
        """FL -> SL -> SL, three deep. A single-level query would stop early."""
        root = _splitter(tenant, "FL-D", level="First-Level")
        db_session.add(root)
        await db_session.flush()

        mid = _splitter(tenant, "SL-MID", parent=root)
        db_session.add(mid)
        await db_session.flush()

        leaf = _splitter(tenant, "SL-LEAF", parent=mid)
        db_session.add(leaf)
        await db_session.flush()

        _, cascaded = await collect_cascade_targets(
            db_session, "splitter", [root.id], tenant.id
        )

        assert set(cascaded) == {mid.id, leaf.id}

    @pytest.mark.asyncio
    async def test_leaf_splitter_has_nothing_to_cascade(self, db_session, tenant):
        leaf = _splitter(tenant, "SL-ALONE")
        db_session.add(leaf)
        await db_session.flush()

        _, cascaded = await collect_cascade_targets(
            db_session, "splitter", [leaf.id], tenant.id
        )
        assert cascaded == []

    @pytest.mark.asyncio
    async def test_already_deleted_children_are_not_reported(self, db_session, tenant):
        """A child soft-deleted in an earlier batch must not be counted again."""
        root = _splitter(tenant, "FL-GONE", level="First-Level")
        db_session.add(root)
        await db_session.flush()

        live = _splitter(tenant, "SL-LIVE", parent=root)
        dead = _splitter(tenant, "SL-DEAD", parent=root)
        dead.is_deleted = True
        db_session.add_all([live, dead])
        await db_session.flush()

        _, cascaded = await collect_cascade_targets(
            db_session, "splitter", [root.id], tenant.id
        )
        assert cascaded == [live.id]

    @pytest.mark.asyncio
    async def test_other_tenant_is_never_cascaded_into(self, db_session, tenant):
        """The FKs do not enforce tenancy; the walk has to."""
        other = Tenant(name="Other", slug=f"other-{uuid.uuid4().hex[:12]}")
        db_session.add(other)
        await db_session.flush()

        root = _splitter(tenant, "FL-ISO", level="First-Level")
        db_session.add(root)
        await db_session.flush()

        foreign_child = _splitter(other, "SL-FOREIGN", parent=root)
        db_session.add(foreign_child)
        await db_session.flush()

        _, cascaded = await collect_cascade_targets(
            db_session, "splitter", [root.id], tenant.id
        )
        assert foreign_child.id not in cascaded


class TestCascadeFromCabinet:

    @pytest.mark.asyncio
    async def test_cabinet_takes_mounted_splitters_and_their_descendants(
        self, db_session, tenant
    ):
        cab = _cabinet(tenant)
        db_session.add(cab)
        await db_session.flush()

        mounted = _splitter(tenant, "SL-MOUNTED", cabinet=cab)
        db_session.add(mounted)
        await db_session.flush()

        below = _splitter(tenant, "SL-BELOW", parent=mounted)
        db_session.add(below)
        await db_session.flush()

        explicit, cascaded = await collect_cascade_targets(
            db_session, "cabinet", [cab.id], tenant.id
        )

        assert explicit == [cab.id]
        assert set(cascaded) == {mounted.id, below.id}

    @pytest.mark.asyncio
    async def test_empty_cabinet_cascades_nothing(self, db_session, tenant):
        cab = _cabinet(tenant, "CAB-EMPTY")
        db_session.add(cab)
        await db_session.flush()

        _, cascaded = await collect_cascade_targets(
            db_session, "cabinet", [cab.id], tenant.id
        )
        assert cascaded == []


class TestCascadeEdgeCases:

    @pytest.mark.asyncio
    async def test_olt_has_no_children(self, db_session, tenant):
        _, cascaded = await collect_cascade_targets(
            db_session, "olt", [uuid.uuid4()], tenant.id
        )
        assert cascaded == []

    @pytest.mark.asyncio
    async def test_no_matches_is_a_no_op(self, db_session, tenant):
        explicit, cascaded = await collect_cascade_targets(
            db_session, "cabinet", [], tenant.id
        )
        assert explicit == []
        assert cascaded == []

    @pytest.mark.asyncio
    async def test_explicitly_named_rows_never_appear_as_cascaded(self, db_session, tenant):
        """Deleting a parent and its child in one file: the child is explicit.

        It must not also be reported as a cascade, or the audit count is
        inflated by every ancestor/descendant pair in the file.
        """
        parent = _splitter(tenant, "FL-BOTH", level="First-Level")
        db_session.add(parent)
        await db_session.flush()

        child = _splitter(tenant, "SL-BOTH", parent=parent)
        db_session.add(child)
        await db_session.flush()

        explicit, cascaded = await collect_cascade_targets(
            db_session, "splitter", [parent.id, child.id], tenant.id
        )

        assert set(explicit) == {parent.id, child.id}
        assert cascaded == []

    @pytest.mark.asyncio
    async def test_cascade_ids_are_deduplicated(self, db_session, tenant):
        """A diamond (two parents sharing a child) must report it once."""
        cab = _cabinet(tenant, "CAB-DIAMOND")
        db_session.add(cab)
        await db_session.flush()

        a = _splitter(tenant, "SL-A", cabinet=cab)
        b = _splitter(tenant, "SL-B", cabinet=cab)
        db_session.add_all([a, b])
        await db_session.flush()

        shared = _splitter(tenant, "SL-SHARED", parent=a)
        db_session.add(shared)
        await db_session.flush()
        # Make the second parent point at the same child.
        b.parent_splitter_id = shared.id
        await db_session.flush()

        _, cascaded = await collect_cascade_targets(
            db_session, "cabinet", [cab.id], tenant.id
        )
        assert len(cascaded) == len(set(cascaded))

    @pytest.mark.asyncio
    async def test_parent_cycle_terminates(self, db_session, tenant):
        """A corrupt A -> B -> A parent chain must not spin forever."""
        a = _splitter(tenant, "CYC-A", level="First-Level")
        db_session.add(a)
        await db_session.flush()

        b = _splitter(tenant, "CYC-B", parent=a)
        db_session.add(b)
        await db_session.flush()

        a.parent_splitter_id = b.id   # closes the loop
        await db_session.flush()

        # Depth cap is the backstop; assert it is bounded, not that it
        # resolves to a particular set.
        assert _MAX_CASCADE_DEPTH < 1000

        _, cascaded = await collect_cascade_targets(
            db_session, "splitter", [a.id], tenant.id
        )
        assert len(cascaded) <= _MAX_CASCADE_DEPTH * 2