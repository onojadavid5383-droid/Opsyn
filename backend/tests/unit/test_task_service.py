# ============================================================
# OPSYN — tests/unit/test_task_service.py   (I.1.1)
# Unit tests for TaskWorkflowService methods.
# All DB calls are mocked — no PostgreSQL required.
# Run: pytest tests/unit/test_task_service.py -v
# ============================================================

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# conftest.py sets env vars before any import
from fastapi import HTTPException


# ── Helpers ───────────────────────────────────────────────────

def _make_user(role_level: int = 3, dept_id: uuid.UUID | None = None) -> MagicMock:
    user = MagicMock()
    user.id         = uuid.uuid4()
    user.username   = "test.user"
    user.tenant_id  = uuid.uuid4()
    user.is_active  = True
    user.role       = MagicMock()
    user.role.level = role_level
    profile = MagicMock()
    profile.department_id = dept_id or uuid.uuid4()
    user.staff_profile    = profile
    return user


def _make_task(
    status:          str  = "in_progress",
    pipeline_stage:  str  = "in_progress",
    task_scope:      str  = "internal",
    is_deleted:      bool = False,
    assignee_id:     uuid.UUID | None = None,
    dept_id:         uuid.UUID | None = None,
    project_id:      uuid.UUID | None = None,
    assignee_confirmed_done: bool = False,
    creator_approved_done:   bool = False,
) -> MagicMock:
    task = MagicMock()
    task.id                        = uuid.uuid4()
    task.ticket_number             = "TSK-2026-0001"
    task.title                     = "Test task"
    task.status                    = status
    task.pipeline_stage            = pipeline_stage
    task.task_scope                = task_scope
    task.is_deleted                = is_deleted
    task.assignee_user_id          = assignee_id or uuid.uuid4()
    task.department_id             = dept_id or uuid.uuid4()
    task.project_id                = project_id
    task.created_by                = uuid.uuid4()
    task.previous_state            = None
    task.assignee_confirmed_done   = assignee_confirmed_done
    task.creator_approved_done     = creator_approved_done
    task.is_reopened               = False
    task.deletion_reason           = None
    return task


def _make_db(task: MagicMock | None = None) -> AsyncMock:
    """Return an AsyncMock database session that yields the given task."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = task
    result.scalar_one.return_value         = task
    db.execute.return_value                = result
    db.flush                               = AsyncMock()
    db.add                                 = MagicMock()
    return db


# ── push_back_task: argument validation ───────────────────────

@pytest.mark.asyncio
async def test_push_back_rejects_empty_reason():
    from app.modules.tasks.service import TaskWorkflowService
    svc    = TaskWorkflowService()
    db     = _make_db()
    caller = _make_user(role_level=5)
    with pytest.raises(HTTPException) as exc:
        await svc.push_back_task(db, uuid.uuid4(), "", caller)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_push_back_rejects_short_reason():
    from app.modules.tasks.service import TaskWorkflowService
    svc    = TaskWorkflowService()
    db     = _make_db()
    caller = _make_user(role_level=5)
    with pytest.raises(HTTPException) as exc:
        await svc.push_back_task(db, uuid.uuid4(), "short", caller)
    assert exc.value.status_code == 422
    assert "10 characters" in exc.value.detail


@pytest.mark.asyncio
async def test_push_back_forbidden_if_not_assignee_and_low_role():
    from app.modules.tasks.service import TaskWorkflowService
    caller = _make_user(role_level=1)
    task   = _make_task(assignee_id=uuid.uuid4())   # different UUID = not assignee
    db     = _make_db(task)
    svc    = TaskWorkflowService()
    with pytest.raises(HTTPException) as exc:
        await svc.push_back_task(db, task.id, "A" * 20, caller)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_push_back_allowed_if_assignee():
    """Assignee (level 1) should be allowed to push back."""
    from app.modules.tasks.service import TaskWorkflowService
    caller = _make_user(role_level=1)
    task   = _make_task(assignee_id=caller.id)
    db     = _make_db(task)

    # Mock _reload so we don't hit DB again
    svc = TaskWorkflowService()
    svc._reload = AsyncMock(return_value=task)

    # Mock the notification helpers
    with (
        patch("app.modules.tasks.service._notify",             new_callable=AsyncMock),
        patch("app.modules.tasks.service._notify_department",  new_callable=AsyncMock),
        patch("app.modules.tasks.service._get_dept_manager",   new_callable=AsyncMock, return_value=None),
        patch("app.modules.tasks.service._log_audit_event",    new_callable=AsyncMock),
    ):
        result = await svc.push_back_task(db, task.id, "A valid reason here!", caller)
    assert result is task


@pytest.mark.asyncio
async def test_push_back_allowed_if_manager():
    """Level 3+ user that is not the assignee should still be able to push back."""
    from app.modules.tasks.service import TaskWorkflowService
    caller = _make_user(role_level=3)
    task   = _make_task(assignee_id=uuid.uuid4())   # different user
    db     = _make_db(task)

    svc = TaskWorkflowService()
    svc._reload = AsyncMock(return_value=task)

    with (
        patch("app.modules.tasks.service._notify",            new_callable=AsyncMock),
        patch("app.modules.tasks.service._notify_department", new_callable=AsyncMock),
        patch("app.modules.tasks.service._get_dept_manager",  new_callable=AsyncMock, return_value=None),
        patch("app.modules.tasks.service._log_audit_event",   new_callable=AsyncMock),
    ):
        result = await svc.push_back_task(db, task.id, "B" * 15, caller)
    assert result is task


# ── reopen_task: state validation ────────────────────────────

@pytest.mark.asyncio
async def test_reopen_non_archived_task_raises_422():
    from app.modules.tasks.service import TaskWorkflowService
    caller = _make_user(role_level=5)
    task   = _make_task(pipeline_stage="in_progress")
    db     = _make_db(task)
    svc    = TaskWorkflowService()
    with pytest.raises(HTTPException) as exc:
        await svc.reopen_task(db, task.id, caller)
    assert exc.value.status_code == 422
    assert "archived" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_reopen_forbidden_for_non_creator_low_role():
    from app.modules.tasks.service import TaskWorkflowService
    caller = _make_user(role_level=2)
    task   = _make_task(pipeline_stage="archive")
    task.created_by = uuid.uuid4()    # not the caller
    db     = _make_db(task)
    svc    = TaskWorkflowService()
    with pytest.raises(HTTPException) as exc:
        await svc.reopen_task(db, task.id, caller)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_reopen_allowed_for_creator():
    from app.modules.tasks.service import TaskWorkflowService
    caller = _make_user(role_level=2)
    task   = _make_task(pipeline_stage="archive")
    task.created_by = caller.id      # same user = creator
    db     = _make_db(task)
    svc    = TaskWorkflowService()
    svc._reload = AsyncMock(return_value=task)

    with (
        patch("app.modules.tasks.service._notify",           new_callable=AsyncMock),
        patch("app.modules.tasks.service._get_dept_manager", new_callable=AsyncMock, return_value=None),
        patch("app.modules.tasks.service._log_audit_event",  new_callable=AsyncMock),
    ):
        result = await svc.reopen_task(db, task.id, caller)
    assert result is task


@pytest.mark.asyncio
async def test_reopen_sets_is_reopened_flag():
    from app.modules.tasks.service import TaskWorkflowService
    caller = _make_user(role_level=4)
    task   = _make_task(pipeline_stage="archive")
    task.created_by = uuid.uuid4()   # not caller, but roleLevel 4 is sufficient
    db     = _make_db(task)
    svc    = TaskWorkflowService()
    svc._reload = AsyncMock(return_value=task)

    with (
        patch("app.modules.tasks.service._notify",           new_callable=AsyncMock),
        patch("app.modules.tasks.service._get_dept_manager", new_callable=AsyncMock, return_value=None),
        patch("app.modules.tasks.service._log_audit_event",  new_callable=AsyncMock),
    ):
        await svc.reopen_task(db, task.id, caller)
    assert task.is_reopened is True
    assert task.pipeline_stage == "in_progress"
    assert task.assignee_confirmed_done is False
    assert task.creator_approved_done is False


# ── soft_delete: reason validation ───────────────────────────

@pytest.mark.asyncio
async def test_soft_delete_rejects_empty_reason():
    from app.modules.tasks.service import TaskWorkflowService
    caller = _make_user(role_level=5)
    task   = _make_task()
    db     = _make_db(task)
    svc    = TaskWorkflowService()
    with pytest.raises(HTTPException) as exc:
        await svc.soft_delete(db, task.id, "", caller)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_soft_delete_rejects_short_reason():
    from app.modules.tasks.service import TaskWorkflowService
    caller = _make_user(role_level=5)
    task   = _make_task()
    db     = _make_db(task)
    svc    = TaskWorkflowService()
    with pytest.raises(HTTPException) as exc:
        await svc.soft_delete(db, task.id, "too short", caller)
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_soft_delete_already_deleted_raises_422():
    from app.modules.tasks.service import TaskWorkflowService
    caller = _make_user(role_level=5)
    task   = _make_task(is_deleted=True)
    db     = _make_db(task)
    svc    = TaskWorkflowService()
    with pytest.raises(HTTPException) as exc:
        await svc.soft_delete(db, task.id, "A" * 20, caller)
    assert exc.value.status_code == 422


# ── _generate_ticket_number: format check ────────────────────

@pytest.mark.asyncio
async def test_ticket_number_format():
    from app.modules.tasks.service import _generate_ticket_number
    import datetime as dt
    year = dt.datetime.utcnow().year

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = 0
    db.execute.return_value = result

    ticket = await _generate_ticket_number(db)
    assert ticket.startswith(f"TSK-{year}-")
    seq = ticket.split("-")[-1]
    assert seq.isdigit() and len(seq) == 4


@pytest.mark.asyncio
async def test_ticket_number_increments():
    from app.modules.tasks.service import _generate_ticket_number
    import datetime as dt
    year = dt.datetime.utcnow().year

    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = 41   # last seq was 41
    db.execute.return_value = result

    ticket = await _generate_ticket_number(db)
    assert ticket == f"TSK-{year}-0042"


# ── _task_snapshot: output shape ─────────────────────────────

def test_task_snapshot_includes_required_keys():
    from app.modules.tasks.service import _task_snapshot
    task = _make_task()
    snap = _task_snapshot(task)
    for key in ("id", "title", "status", "pipeline_stage", "task_scope",
                "is_deleted", "is_reopened", "assignee_confirmed_done", "creator_approved_done"):
        assert key in snap, f"Missing key: {key}"
