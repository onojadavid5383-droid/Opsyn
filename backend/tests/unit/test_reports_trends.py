# ============================================================
# OPSYN — tests/unit/test_reports_trends.py
# GET /reports/trends pure logic: window validation, SQL whitelisting,
# gap handling (count → 0, ratio → null), breakdown alignment, and the
# 0086 migration's place in the revision chain. No database required.
# ============================================================

import datetime
import pathlib
import re

import pytest
from fastapi import HTTPException

from app.modules.reports.trends import (
    BUCKETS, METRICS, series_sql, shape_breakdown, shape_points, validate_window,
)


class TestValidateWindow:

    def test_accepts_every_metric_on_default_window(self):
        for metric in METRICS:
            assert validate_window(metric, "day", 30) is METRICS[metric]

    @pytest.mark.parametrize("metric,bucket,days", [
        ("not_a_metric", "day", 30),
        ("outages_opened", "month", 30),
        ("outages_opened", "hour", 15),     # hour max is 14
        ("outages_opened", "day", 0),
        ("outages_opened", "day", 181),     # day max is 180
    ])
    def test_rejects_bad_input_with_422(self, metric, bucket, days):
        with pytest.raises(HTTPException) as exc:
            validate_window(metric, bucket, days)
        assert exc.value.status_code == 422


class TestSeriesSql:

    def test_only_whitelisted_values_are_interpolated(self):
        # The tenant id and window length must be bound parameters.
        for metric, defn in METRICS.items():
            for bucket in BUCKETS:
                sql = series_sql(defn, metric, bucket, with_breakdown=False)
                assert ":tid" in sql and ":days" in sql

    def test_snapshot_metrics_read_the_snapshot_table(self):
        sql = series_sql(METRICS["port_utilisation_pct"], "port_utilisation_pct", "day",
                         with_breakdown=False)
        assert "ops_metric_snapshots" in sql
        assert "metric_key = 'port_utilisation_pct'" in sql
        # Ratio of sums, not an average of percentages
        assert "SUM(numerator)" in sql and "SUM(denominator)" in sql

    def test_breakdown_query_groups_by_split_column(self):
        sql = series_sql(METRICS["outages_opened"], "outages_opened", "day", with_breakdown=True)
        assert "severity AS k" in sql and "GROUP BY 1, 2" in sql


def _t(day: int) -> datetime.datetime:
    return datetime.datetime(2026, 9, day)


class TestShapePoints:

    def test_count_metric_fills_gaps_with_zero(self):
        points = shape_points([(_t(1), 3), (_t(2), None)], fill_zero=True)
        assert [p["value"] for p in points] == [3, 0]

    def test_ratio_metric_keeps_gaps_null(self):
        points = shape_points([(_t(1), 97.456), (_t(2), None)], fill_zero=False)
        assert [p["value"] for p in points] == [97.46, None]

    def test_timestamps_are_utc_iso(self):
        (point,) = shape_points([(_t(1), 1)], fill_zero=True)
        assert point["t"] == "2026-09-01T00:00:00+00:00"


class TestShapeBreakdown:

    def test_aligns_rows_to_buckets_and_zero_fills(self):
        points = shape_points([(_t(1), 2), (_t(2), 1)], fill_zero=True)
        rows = [(_t(1), "critical", 2), (_t(2), "warning", 1)]
        assert shape_breakdown(points, rows) == {"critical": [2, 0], "warning": [0, 1]}

    def test_ignores_rows_outside_the_window(self):
        points = shape_points([(_t(2), 1)], fill_zero=True)
        assert shape_breakdown(points, [(_t(1), "high", 5)]) == {}


def test_migration_0086_follows_0085():
    versions = pathlib.Path(__file__).parents[2] / "alembic" / "versions"
    text = next(versions.glob("0086_*.py")).read_text(encoding="utf-8")
    assert re.search(r"^revision\s*=\s*'0086'", text, re.MULTILINE)
    assert re.search(r"^down_revision\s*=\s*'0085'", text, re.MULTILINE)
