"""Shared Redis flag for cooperative FTTx design cancellation."""

from __future__ import annotations

import json

from app.core.celery_app import celery_app

_CANCEL_KEY_PREFIX = "fttx-design:cancel:"
_PROGRESS_KEY_PREFIX = "fttx-design:progress:"
_CANCEL_TTL_SECONDS = 24 * 60 * 60


def request_cancellation(task_id: str) -> None:
    celery_app.backend.client.set(
        f"{_CANCEL_KEY_PREFIX}{task_id}", "1", ex=_CANCEL_TTL_SECONDS,
    )


def cancellation_requested(task_id: str) -> bool:
    try:
        return bool(celery_app.backend.client.get(f"{_CANCEL_KEY_PREFIX}{task_id}"))
    except Exception:
        # A Redis blip should not turn a healthy design into a failed run.
        return False


def clear_cancellation(task_id: str) -> None:
    celery_app.backend.client.delete(f"{_CANCEL_KEY_PREFIX}{task_id}")


def report_progress(task_id: str, pct: int, message: str) -> None:
    payload = json.dumps({"pct": max(0, min(100, int(pct))), "message": str(message)[:200]})
    celery_app.backend.client.set(
        f"{_PROGRESS_KEY_PREFIX}{task_id}", payload, ex=_CANCEL_TTL_SECONDS,
    )


def read_progress(task_id: str) -> dict | None:
    try:
        raw = celery_app.backend.client.get(f"{_PROGRESS_KEY_PREFIX}{task_id}")
        if not raw:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) and isinstance(value.get("pct"), int) else None
    except Exception:
        return None


def clear_progress(task_id: str) -> None:
    celery_app.backend.client.delete(f"{_PROGRESS_KEY_PREFIX}{task_id}")
