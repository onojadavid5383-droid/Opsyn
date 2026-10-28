# ============================================================
# OPSYN FTTX DESIGNER TASK — app/tasks/fttx_design_run.py
# Celery task: run the FTTx Designer engine pipeline
# (app/modules/fttx_designer/engine/pipeline.run_fttx_design) for one
# fttx_design_runs row.
#
# Progress reporting split two ways, matching how Celery is already used
# elsewhere in this codebase (task_track_started=True in celery_app.py):
#   - Live, in-flight progress (0-100%, stage message) goes through
#     Celery's own task state (`self.update_state(state="PROGRESS", ...)`),
#     which is a cheap Redis write with no DB round-trip — this is what
#     `run_fttx_design()`'s `progress_callback` is wired to, called from
#     deep inside a long synchronous pipeline run where an async DB write
#     isn't reachable without nesting event loops.
#   - The DB row (`fttx_design_runs.status`/`progress_pct`/...) is only
#     touched at well-defined async checkpoints: once when the task starts
#     ("running") and once when it finishes ("completed"/"failed"). A
#     GET-status endpoint (router.py, next sub-phase) merges both: the DB
#     row for the authoritative final state, `AsyncResult(celery_task_id)`
#     for live percentage while a run is still in flight.
#
# Design runs (Network GIS Phase 5, run.design_id set by Auto design): once
# the output is stored, design.auto_design.apply_output() writes it into the
# design's working set as a new version. If that fails (the design went into
# review meanwhile, or a row was refused), the run is marked failed with the
# reason; its output stays stored and can be imported later.
# ============================================================

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any, Dict, Optional

from celery import shared_task
from sqlalchemy import select

from app.modules.fttx_designer.config_io import InvalidFttxConfigError, config_from_dict
from app.modules.fttx_designer.cancellation import (
    cancellation_requested, clear_cancellation, clear_progress, report_progress,
)
from app.modules.fttx_designer.engine.errors import DesignCancelledError, FTTXError
from app.modules.fttx_designer.engine.optical import evaluate_optical_design
from app.modules.fttx_designer.engine.pipeline import PipelineResult, run_fttx_design
from app.modules.fttx_designer.geojson_io import (
    GeoJsonLayerError, build_input_layers, json_safe, layer_to_geojson,
    layer_to_rows,
)
from app.modules.fttx_designer.models import FttxDesignRun, FttxDesignRunLayer, FttxDesignRunOutput
# The run's design_id / design_version_id foreign keys need these mapped in
# the worker process too (the API process maps them through main.py)
import app.modules.design.models  # noqa: E402,F401

logger = logging.getLogger(__name__)


@shared_task(name="fttx_designer.run_design", bind=True, max_retries=0)
def run_fttx_design_task(self, run_id: str) -> None:
    try:
        asyncio.run(_run(self, run_id))
    except Exception as exc:
        # Anything that escapes _run must not leave the run "queued" or
        # "running" for ever: record it on the row, then let Celery log it
        asyncio.run(_fail_unexpectedly(run_id, exc))
        raise


async def _fail_unexpectedly(run_id: str, exc: Exception) -> None:
    from sqlalchemy import text

    from app.tasks._db import make_task_session

    engine, db = await make_task_session()
    try:
        reason = (str(exc).strip().splitlines() or [type(exc).__name__])[0][:300]
        await db.execute(text("""
            UPDATE fttx_design_runs
            SET status = 'failed', progress_message = 'Failed', completed_at = now(),
                error_message = :m
            WHERE id = CAST(:id AS uuid) AND status IN ('queued', 'running', 'cancelling')
        """), {"id": run_id, "m": f"The run stopped unexpectedly: {reason}"})
        await db.commit()
    except Exception:
        logger.exception("Could not mark FTTx run %s as failed", run_id)
    finally:
        await db.close()
        await engine.dispose()


async def _run(task, run_id: str) -> None:
    from app.tasks._db import make_task_session

    engine, db = await make_task_session()
    try:
        run = await db.get(FttxDesignRun, run_id)
        if run is None:
            logger.error("FttxDesignRun %s not found — task aborted", run_id)
            return

        task_id = run.celery_task_id or getattr(task.request, "id", None)
        if task_id and cancellation_requested(task_id):
            await _mark_cancelled(db, run, "Design run cancelled before it started.")
            return

        run.celery_task_id = task_id
        run.status = "running"
        run.started_at = datetime.datetime.now(datetime.timezone.utc)
        run.error_message = None
        run.progress_pct = 0
        run.progress_message = "Starting"
        await db.commit()

        def _progress(pct: int, message: str = "") -> None:
            # Sync callback, invoked from deep inside the synchronous
            # run_fttx_design() call below — must never touch the async
            # `db` session (no event loop to await into here).
            if task_id:
                try:
                    report_progress(task_id, pct, message)
                except Exception:
                    logger.debug("Could not persist progress for FTTx task %s", task_id, exc_info=True)
            try:
                task.update_state(state="PROGRESS", meta={"pct": pct, "message": message})
            except Exception:
                pass  # progress reporting must never fail the run

        def _cancel_check() -> bool:
            return bool(task_id and cancellation_requested(task_id))

        def _input_progress(pct: int, message: str) -> None:
            _progress(pct, message)
            if _cancel_check():
                raise DesignCancelledError("Design run cancelled by user.")

        try:
            _progress(1, "Loading uploaded layers")
            layer_rows = (await db.execute(
                select(FttxDesignRunLayer).where(FttxDesignRunLayer.run_id == run.id)
            )).scalars().all()
            geojson_by_key: Dict[str, Any] = {row.layer_key: row.geojson for row in layer_rows}
            _progress(2, "Loading design configuration")
            config = config_from_dict(run.config)
            _progress(2, "Preparing uploaded network layers")
            layers, _target_crs = build_input_layers(geojson_by_key, progress_callback=_input_progress)
            result: PipelineResult = run_fttx_design(
                config=config, layers=layers, progress_callback=_progress,
                cancel_check=_cancel_check,
            )
        except DesignCancelledError as exc:
            await _mark_cancelled(db, run, str(exc), _read_exception_log(exc))
            return
        except (GeoJsonLayerError, InvalidFttxConfigError, FTTXError) as exc:
            await _mark_failed(db, run, str(exc), _read_exception_log(exc))
            return
        except Exception as exc:
            await _mark_failed(db, run, f"Unexpected error: {exc}", _read_exception_log(exc))
            logger.exception("FTTx design run %s failed unexpectedly", run_id)
            return

        if _cancel_check():
            await _mark_cancelled(db, run, "Design run cancelled by user.", _read_log_text(result))
            return

        output_layers_geojson = json_safe({
            key: layer_to_geojson(layer) for key, layer in result.output_layers.items()
        })
        boq_rows = layer_to_rows(result.output_layers["boq"]) if "boq" in result.output_layers else None
        boq_fdt_rows = layer_to_rows(result.output_layers["boq_fdt"]) if "boq_fdt" in result.output_layers else None

        output = FttxDesignRunOutput(
            run_id=run.id,
            tenant_id=run.tenant_id,
            output_layers=output_layers_geojson,
            boq_rows=boq_rows,
            boq_fdt_rows=boq_fdt_rows,
            optical_loss_summary=json_safe(result.optical_loss_summary),
            project_identity=json_safe(result.project_identity),
            log_text=_read_log_text(result),
        )
        # Validate every JSONB value with Python's strict encoder before the
        # asyncpg bind. The standard encoder otherwise emits bare Infinity /
        # NaN tokens, which PostgreSQL rejects with a vague JSON syntax error.
        for field_name in (
            "output_layers", "boq_rows", "boq_fdt_rows",
            "optical_loss_summary", "project_identity",
        ):
            value = json_safe(getattr(output, field_name))
            setattr(output, field_name, value)
            try:
                json.dumps(value, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"FTTx output field '{field_name}' is not valid JSON: {exc}"
                ) from exc
        if _cancel_check():
            await _mark_cancelled(db, run, "Design run cancelled before its outputs were saved.", _read_log_text(result))
            return
        db.add(output)

        if run.design_id is not None:
            # Keep the engine's output even if writing it into the design fails
            await db.commit()
            if _cancel_check():
                await _mark_cancelled(db, run, "Design run cancelled before its output was applied.", _read_log_text(result))
                return
            _progress(99, "Saving to the design")
            try:
                from app.modules.design.auto_design import DesignLocked, apply_output
                applied = await apply_output(
                    db, run.tenant_id, run.design_id, output=output, run=run, pole_fc=geojson_by_key.get("pole"),
                    method="AUTO", label="Auto design",
                )
            except DesignLocked as exc:
                await _mark_failed(db, run, str(exc))
                return
            except Exception as exc:
                logger.exception("Writing FTTx run %s into design %s failed", run_id, run.design_id)
                reason = (str(exc).strip().splitlines() or [type(exc).__name__])[0][:300]
                await _mark_failed(db, run, f"The engine finished, but its output could not be saved to the design: {reason}")
                return

        run.status = "completed"
        run.progress_pct = 100
        run.progress_message = "Completed"
        run.error_message = None
        run.result_summary = json_safe(_build_result_summary(result))
        if run.design_id is not None:
            run.result_summary = {**run.result_summary, "design": applied}
        run.completed_at = datetime.datetime.now(datetime.timezone.utc)
        await db.commit()

    finally:
        if 'task_id' in locals() and task_id:
            try:
                clear_cancellation(task_id)
                clear_progress(task_id)
            except Exception:
                logger.exception("Could not clear cancellation flag for FTTx run %s", run_id)
        await db.close()
        await engine.dispose()


async def _mark_failed(db, run: FttxDesignRun, message: str, log_text: Optional[str] = None) -> None:
    await db.rollback()
    run.status = "failed"
    run.error_message = message
    run.log_text = log_text
    run.progress_message = "Failed"
    run.completed_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()


async def _mark_cancelled(db, run: FttxDesignRun, message: str, log_text: Optional[str] = None) -> None:
    await db.rollback()
    run.status = "cancelled"
    run.error_message = message
    run.log_text = log_text
    run.progress_message = "Cancelled"
    run.completed_at = datetime.datetime.now(datetime.timezone.utc)
    await db.commit()


def _read_exception_log(exc: Exception) -> Optional[str]:
    """Read the flushed pipeline log attached before the exception escaped."""
    log_path = getattr(exc, "_fttx_log_path", None)
    if not log_path:
        return None
    try:
        with open(log_path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        logger.exception("Could not read failed FTTx run log at %s", log_path)
        return None


def _read_log_text(result: PipelineResult) -> Optional[str]:
    log_path = getattr(result.logger, "log_path", None)
    if not log_path:
        return None
    try:
        with open(log_path, encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


def _build_result_summary(result: PipelineResult) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "homepass_count": len(result.homepasses),
        "fat_count": len(result.fats),
        "fdt_count": len(result.fdts),
        "closure_count": len(result.closures),
        "structure_count": len(result.structures),
        "b2b_cable_count": len(result.b2b_cables),
        "b2c_cable_count": len(result.b2c_cables),
        "closure_cable_count": len(result.closure_cables),
        "pickup_cable_count": len(result.pickup_cables),
    }
    if result.optical_result is not None:
        overview = evaluate_optical_design(result.optical_result)
        summary["optical"] = {
            "total_customers": overview["total_customers"],
            "passed_customers": overview["passed_customers"],
            "marginal_customers": overview["marginal_customers"],
            "failed_customers": overview["failed_customers"],
            "invalid_customers": overview["invalid_customers"],
        }
    return summary
