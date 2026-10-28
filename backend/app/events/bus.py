# ============================================================
# OPSYN EVENT BUS — app/events/bus.py
# In-process async event emitter for domain events
# Triggers Celery tasks for email/notifications
# ============================================================

from __future__ import annotations
import asyncio
from typing import Callable, Any
from collections import defaultdict


class AsyncEventBus:
    """
    Lightweight async publish/subscribe event bus.
    Events are emitted after DB transactions commit.
    Handlers run as background asyncio tasks — failures don't affect the caller.
    """
    def __init__(self):
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def on(self, event: str, handler: Callable) -> None:
        """Register an async handler for an event."""
        self._handlers[event].append(handler)

    async def emit(self, event: str, payload: dict[str, Any]) -> None:
        """Emit an event to all registered handlers (non-blocking)."""
        for handler in self._handlers.get(event, []):
            asyncio.create_task(self._safe_call(handler, payload))

    @staticmethod
    async def _safe_call(handler: Callable, payload: dict) -> None:
        try:
            await handler(payload)
        except Exception as e:
            import structlog
            structlog.get_logger().error("event_handler_failed",
                                          handler=handler.__name__, error=str(e))


event_bus = AsyncEventBus()


# ── Register all handlers on startup ──────────────────────────
def register_handlers():
    from app.events.handlers import staff_created, role_changed, outage_logged, onboarding_approved
    from app.events.handlers.project_stage_advanced import handle_project_stage_advanced
    from app.events.handlers.project_stage_pushed_back import handle_project_stage_pushed_back
    event_bus.on("staff.created",             staff_created.handle)
    event_bus.on("staff.role_changed",        role_changed.handle)
    event_bus.on("outage.logged",             outage_logged.handle)
    event_bus.on("onboarding.approved",       onboarding_approved.handle)
    event_bus.on("project.stage_advanced",    handle_project_stage_advanced)
    event_bus.on("project.stage_pushed_back", handle_project_stage_pushed_back)
    event_bus.on("project.pipeline_started",  handle_project_stage_advanced)  # reuse for start event
