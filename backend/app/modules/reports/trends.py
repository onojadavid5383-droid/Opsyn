# ============================================================
# OPSYN REPORTS — app/modules/reports/trends.py
# GET /reports/trends — bucketed time series for Command Center charts.
#
# Two kinds of metric:
#   * derived  — computed on the fly from timestamps that already exist on
#                their source tables (outages, tasks, customers).
#   * snapshot — read from ops_metric_snapshots, written hourly by
#                app/tasks/metric_snapshots.py, for metrics that only exist
#                as a live value (node availability, port utilisation).
#
# Every bucket in the requested window is returned. Count metrics fill empty
# buckets with 0; ratio/average metrics leave them null — "no resolutions
# that day" has no MTTR, and "no snapshot yet" has no availability. Charts
# must render a gap, never an invented value.
# ============================================================

from __future__ import annotations

import datetime
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.modules.staff.models import User

router = APIRouter()


# ── Buckets ──────────────────────────────────────────────────
# Whitelisted: these strings are interpolated into SQL, so they must never
# come from the request directly.
BUCKETS: dict[str, tuple[str, int]] = {
    # bucket: (postgres interval step, max window in days)
    "hour": ("1 hour", 14),
    "day":  ("1 day", 180),
    "week": ("1 week", 730),
}


@dataclass(frozen=True)
class MetricDef:
    unit:         str            # 'count' | 'hours' | 'percent'
    kind:         str            # 'derived' | 'snapshot'
    fill_zero:    bool           # count metrics: empty bucket = 0
    table:        str = ""
    ts_expr:      str = ""       # timestamptz expression the bucket is taken from
    value_expr:   str = ""       # aggregate over rows in a bucket
    where:        str = ""       # extra AND-ed filter
    breakdown:    str | None = None  # column to split series by


METRICS: dict[str, MetricDef] = {
    "outages_opened": MetricDef(
        unit="count", kind="derived", fill_zero=True,
        table="outage_incidents", ts_expr="created_at", value_expr="COUNT(*)",
        breakdown="severity",
    ),
    "outages_resolved": MetricDef(
        unit="count", kind="derived", fill_zero=True,
        table="outage_incidents", ts_expr="resolved_at", value_expr="COUNT(*)",
        where="resolved_at IS NOT NULL",
    ),
    "mttr_hours": MetricDef(
        unit="hours", kind="derived", fill_zero=False,
        table="outage_incidents", ts_expr="resolved_at",
        value_expr="AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600.0)",
        where="resolved_at IS NOT NULL",
    ),
    "tasks_created": MetricDef(
        unit="count", kind="derived", fill_zero=True,
        table="tasks", ts_expr="created_at", value_expr="COUNT(*)",
        where="is_deleted IS NOT TRUE",
    ),
    # Tasks have no single completion timestamp. assignee_done_at is set by the
    # "done" action; for tasks that reached done another way, the last
    # transition time (state_changed_at) is the best available signal while
    # they are still in 'done'. Archived tasks without assignee_done_at are
    # not counted — their completion time is no longer recoverable.
    "tasks_completed": MetricDef(
        unit="count", kind="derived", fill_zero=True,
        table="tasks",
        ts_expr="COALESCE(assignee_done_at, CASE WHEN status = 'done' THEN state_changed_at END)",
        value_expr="COUNT(*)",
        where="is_deleted IS NOT TRUE",
    ),
    "customers_added": MetricDef(
        unit="count", kind="derived", fill_zero=True,
        table="customers", ts_expr="created_at", value_expr="COUNT(*)",
        where="is_deleted IS NOT TRUE",
    ),
    "node_availability_pct": MetricDef(unit="percent", kind="snapshot", fill_zero=False),
    "port_utilisation_pct":  MetricDef(unit="percent", kind="snapshot", fill_zero=False),
}


def validate_window(metric: str, bucket: str, days: int) -> MetricDef:
    """Raise HTTP 422 for an unknown metric/bucket or an oversized window."""
    if metric not in METRICS:
        raise HTTPException(422, f"Unknown metric '{metric}'. Expected one of: {', '.join(METRICS)}")
    if bucket not in BUCKETS:
        raise HTTPException(422, f"Unknown bucket '{bucket}'. Expected one of: {', '.join(BUCKETS)}")
    max_days = BUCKETS[bucket][1]
    if not 1 <= days <= max_days:
        raise HTTPException(422, f"days must be between 1 and {max_days} for bucket '{bucket}'")
    return METRICS[metric]


def series_sql(defn: MetricDef, metric: str, bucket: str, *, with_breakdown: bool) -> str:
    """Build the bucketed query. Only whitelisted strings are interpolated."""
    step = BUCKETS[bucket][0]
    series = f"""
        SELECT generate_series(
            date_trunc('{bucket}', (now() AT TIME ZONE 'UTC') - make_interval(days => :days)),
            date_trunc('{bucket}',  now() AT TIME ZONE 'UTC'),
            interval '{step}'
        ) AS t
    """
    if defn.kind == "snapshot":
        agg = f"""
            SELECT date_trunc('{bucket}', captured_at AT TIME ZONE 'UTC') AS t,
                   CASE WHEN SUM(denominator) > 0
                        THEN SUM(numerator)::float / SUM(denominator) * 100 END AS v
            FROM ops_metric_snapshots
            WHERE tenant_id = :tid
              AND metric_key = '{metric}'
              AND captured_at >= now() - make_interval(days => :days + 7)
            GROUP BY 1
        """
        return f"WITH s AS ({series}), a AS ({agg}) SELECT s.t, a.v FROM s LEFT JOIN a ON a.t = s.t ORDER BY s.t"

    extra = f"AND {defn.where}" if defn.where else ""
    group_cols = "1, 2" if with_breakdown else "1"
    split_col = f", {defn.breakdown} AS k" if with_breakdown else ""
    agg = f"""
        SELECT date_trunc('{bucket}', ({defn.ts_expr}) AT TIME ZONE 'UTC') AS t{split_col},
               {defn.value_expr} AS v
        FROM {defn.table}
        WHERE tenant_id = :tid
          AND ({defn.ts_expr}) >= now() - make_interval(days => :days + 7)
          {extra}
        GROUP BY {group_cols}
    """
    if with_breakdown:
        return f"WITH a AS ({agg}) SELECT t, k, v FROM a"
    return f"WITH s AS ({series}), a AS ({agg}) SELECT s.t, a.v FROM s LEFT JOIN a ON a.t = s.t ORDER BY s.t"


def shape_points(rows, fill_zero: bool) -> list[dict]:
    """[(t, v)] → [{t, value}] with count metrics zero-filled and floats rounded."""
    points = []
    for t, v in rows:
        if v is None:
            value = 0 if fill_zero else None
        elif fill_zero:
            value = int(v)
        else:
            value = round(float(v), 2)
        points.append({"t": t.replace(tzinfo=datetime.timezone.utc).isoformat(), "value": value})
    return points


def shape_breakdown(points: list[dict], rows) -> dict[str, list[int]]:
    """Align (t, key, v) rows onto the main series' buckets, zero-filled."""
    index = {p["t"]: i for i, p in enumerate(points)}
    out: dict[str, list[int]] = {}
    for t, key, v in rows:
        iso = t.replace(tzinfo=datetime.timezone.utc).isoformat()
        if iso not in index:
            continue  # row falls in the lookback margin before the first bucket
        out.setdefault(key or "unknown", [0] * len(points))[index[iso]] = int(v or 0)
    return out


@router.get("/trends")
async def get_trends(
    metric: str = Query(..., description=f"One of: {', '.join(METRICS)}"),
    bucket: str = Query("day", description="hour | day | week"),
    days:   int = Query(30, description="Window length; max 14 (hour), 180 (day), 730 (week)"),
    db:     AsyncSession = Depends(get_db),
    # Same access level as GET /dashboard/summary: aggregate counts only, and
    # the Command Center is available to every authenticated user.
    caller: User = Depends(get_current_user),
):
    defn = validate_window(metric, bucket, days)
    params = {"tid": str(caller.tenant_id), "days": days}

    rows = (await db.execute(text(series_sql(defn, metric, bucket, with_breakdown=False)), params)).all()
    points = shape_points(rows, defn.fill_zero)

    data: dict = {
        "metric":  metric,
        "unit":    defn.unit,
        "bucket":  bucket,
        "days":    days,
        "points":  points,
        # Counts: a window of all-zero buckets is "nothing happened".
        # Ratios: any non-null bucket is real data, including a genuine 0%.
        "has_data": any(p["value"] for p in points) if defn.fill_zero
                    else any(p["value"] is not None for p in points),
    }

    if defn.breakdown:
        split_rows = (await db.execute(text(series_sql(defn, metric, bucket, with_breakdown=True)), params)).all()
        data["breakdown_by"] = defn.breakdown
        data["breakdown"] = shape_breakdown(points, split_rows)

    return {"success": True, "data": data}
