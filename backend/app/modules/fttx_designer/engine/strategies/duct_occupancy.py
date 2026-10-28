"""Verbatim port of ``DuctOccupancyLedger`` from
``FTTx Designer — dual PON integrated.py``.

No logic changes from the source script. Despite its docstring calling
itself "Persistent GeoPackage-backed", the implementation is plain stdlib
``sqlite3`` against a single custom table (``duct_occupancy``) in whatever
file ``gpkg_path`` points at — it never touches OGR/GeoPackage-specific
conventions or any QGIS API. That makes it fully portable as-is; no
Postgres redesign is needed to port the *logic* (an earlier planning pass
assumed otherwise). The one genuine web-deployment question this raises —
where does ``gpkg_path`` point when the pipeline runs in a stateless
backend worker instead of a desktop QGIS session with a fixed project
directory? — is a Phase 3 integration concern (a persistent volume path,
or swapping the sqlite3 calls here for a Postgres table, if concurrent
multi-worker access turns out to matter), not something this port decides
unilaterally.

The one ``geometry_compat`` dependency this class has —
``route.geometry.asWkt(3)`` — needed a small fidelity fix made alongside
this port: ``QgsGeometry.asWkt()`` previously took no arguments; real
QGIS's ``asWkt(precision)`` accepts an optional rounding-precision digit
count, now supported via Shapely's ``wkt.dumps(geom,
rounding_precision=n)``.
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
from typing import Dict, List, Optional

from ..domain import DuctRoute
from ..perf_logger import PerformanceLogger


class DuctOccupancyLedger:
    """Persistent GeoPackage-backed ledger tracking duct way occupancy
    across multiple design runs.

    Schema (SQLite table ``duct_occupancy``)
    ----------------------------------------
    route_id       TEXT PRIMARY KEY  — stable DR-NNNN identifier
    geom_wkt       TEXT              — WKT of the duct route geometry
                                       used for spatial lookup on re-run
    duct_ways      INTEGER           — total ways in this duct
    occupied       INTEGER           — ways currently in use
    duct_type      TEXT
    duct_diameter  INTEGER
    installation   TEXT
    first_run_ts   TEXT              — ISO-8601 timestamp of first run
    last_run_ts    TEXT              — ISO-8601 timestamp of most recent run
    metadata       TEXT              — JSON blob for future extension

    Usage
    -----
    ::

        ledger = DuctOccupancyLedger(path, logger)
        ledger.open()

        # Before routing: load existing occupancy into DuctRoute objects
        ledger.apply_to_routes(routes)

        # After routing: write new/updated routes back
        ledger.save_routes(routes)

        ledger.close()

    Thread safety
    -------------
    Not thread-safe.  All ledger calls are made from the main pipeline
    thread (the QThread worker), never from UI thread.
    """

    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS duct_occupancy (
        route_id      TEXT PRIMARY KEY,
        geom_wkt      TEXT NOT NULL,
        duct_ways     INTEGER NOT NULL DEFAULT 4,
        occupied      INTEGER NOT NULL DEFAULT 0,
        duct_type     TEXT NOT NULL DEFAULT 'HDPE',
        duct_diameter INTEGER NOT NULL DEFAULT 50,
        installation  TEXT NOT NULL DEFAULT 'direct_buried',
        first_run_ts  TEXT NOT NULL,
        last_run_ts   TEXT NOT NULL,
        metadata      TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_duct_occupancy_route
        ON duct_occupancy (route_id);
    """

    GEOM_SNAP_TOLERANCE = 2.0   # metres — routes within this distance are
                                 # treated as the same physical duct

    def __init__(self, gpkg_path: str, logger: 'PerformanceLogger'):
        self._path   = gpkg_path
        self._logger = logger
        self._conn:  Optional[sqlite3.Connection] = None
        self._cursor: Optional[sqlite3.Cursor]    = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open (or create) the GeoPackage SQLite database."""
        try:
            existed = os.path.exists(self._path)
            self._conn   = sqlite3.connect(self._path)
            self._cursor = self._conn.cursor()
            self._cursor.executescript(self.TABLE_DDL)
            self._conn.commit()
            if existed:
                self._logger.log(
                    f"OccupancyLedger: opened existing ledger at '{self._path}' "
                    f"({self._record_count()} records)"
                )
            else:
                self._logger.log(
                    f"OccupancyLedger: created new ledger at '{self._path}'"
                )
        except Exception as e:
            self._logger.log(f"WARNING [LEDGER_OPEN_FAIL]: {e} — occupancy disabled for this run.")
            self._conn   = None
            self._cursor = None

    def close(self) -> None:
        """Commit and close the database connection."""
        if self._conn:
            try:
                self._conn.commit()
                self._conn.close()
            except Exception as e:
                self._logger.log(f"WARNING [LEDGER_CLOSE_FAIL]: {e}")
            finally:
                self._conn   = None
                self._cursor = None

    def is_open(self) -> bool:
        return self._conn is not None

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def apply_to_routes(self, routes: List['DuctRoute']) -> int:
        """Load persisted occupancy into each DuctRoute.

        Matches routes by ``route_id`` first (exact), then falls back to
        WKT geometry proximity for routes that were generated on a
        previous run before stable IDs were assigned.

        Returns the number of routes whose occupancy was updated from the
        ledger (useful for logging).
        """
        if not self.is_open():
            return 0

        rows = self._cursor.execute(
            "SELECT route_id, geom_wkt, duct_ways, occupied FROM duct_occupancy"
        ).fetchall()

        # Build lookup dicts
        by_id: Dict[str, tuple] = {r[0]: r for r in rows}

        updated = 0
        for route in routes:
            if route.route_id in by_id:
                _, _, db_ways, db_occ = by_id[route.route_id]
                route.duct_ways = db_ways
                route.occupied  = min(db_occ, db_ways)
                updated += 1
            else:
                # Geometry fallback — compare WKT start/end point proximity
                route_wkt = route.geometry.asWkt(3) if route.geometry else ""
                matched = self._match_by_geom(route_wkt, rows)
                if matched:
                    _, _, db_ways, db_occ = matched
                    route.duct_ways = db_ways
                    route.occupied  = min(db_occ, db_ways)
                    updated += 1

        self._logger.log(
            f"OccupancyLedger.apply_to_routes: {updated}/{len(routes)} routes "
            f"had persisted occupancy loaded"
        )
        return updated

    def save_routes(self, routes: List['DuctRoute']) -> int:
        """Write all DuctRoute occupancy values to the ledger.

        Uses UPSERT (INSERT OR REPLACE) so each run is idempotent — running
        the same design twice does not double-count occupancy.

        Returns number of rows written.
        """
        if not self.is_open():
            return 0

        now_ts = datetime.datetime.utcnow().isoformat()
        written = 0

        for route in routes:
            wkt = route.geometry.asWkt(3) if route.geometry else ""
            try:
                # Check if row exists to preserve first_run_ts
                existing = self._cursor.execute(
                    "SELECT first_run_ts FROM duct_occupancy WHERE route_id = ?",
                    (route.route_id,)
                ).fetchone()
                first_ts = existing[0] if existing else now_ts

                self._cursor.execute(
                    """INSERT OR REPLACE INTO duct_occupancy
                       (route_id, geom_wkt, duct_ways, occupied,
                        duct_type, duct_diameter, installation,
                        first_run_ts, last_run_ts, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        route.route_id,
                        wkt,
                        route.duct_ways,
                        route.occupied,
                        route.duct_type,
                        route.duct_diameter,
                        route.installation_method,
                        first_ts,
                        now_ts,
                        json.dumps({"spare_pct": route.spare_pct,
                                    "status": route.status}),
                    )
                )
                written += 1
            except Exception as e:
                self._logger.log(
                    f"WARNING [LEDGER_WRITE_FAIL]: route {route.route_id}: {e}"
                )

        self._conn.commit()
        self._logger.log(
            f"OccupancyLedger.save_routes: {written}/{len(routes)} routes saved "
            f"to ledger"
        )
        return written

    def get_available_ways(self, route_id: str) -> Optional[int]:
        """Return spare ways for a known route, or None if not in ledger."""
        if not self.is_open():
            return None
        row = self._cursor.execute(
            "SELECT duct_ways, occupied FROM duct_occupancy WHERE route_id = ?",
            (route_id,)
        ).fetchone()
        if row:
            return max(0, row[0] - row[1])
        return None

    def increment_occupied(self, route_id: str, cable_ways: int = 1) -> bool:
        """Increment occupied count for a route by ``cable_ways``.

        Called when a new cable is assigned to an existing duct segment.
        Fails gracefully (logs warning, returns False) if the duct is
        already at capacity or the route is not in the ledger.
        """
        if not self.is_open():
            return False
        row = self._cursor.execute(
            "SELECT duct_ways, occupied FROM duct_occupancy WHERE route_id = ?",
            (route_id,)
        ).fetchone()
        if not row:
            return False
        ways, occ = row
        new_occ = occ + cable_ways
        if new_occ > ways:
            self._logger.log(
                f"WARNING [DUCT_AT_CAPACITY]: route {route_id} — "
                f"{occ}/{ways} ways used, cannot add {cable_ways} more."
            )
            return False
        self._cursor.execute(
            "UPDATE duct_occupancy SET occupied = ? WHERE route_id = ?",
            (new_occ, route_id)
        )
        return True

    def summary(self) -> Dict[str, int]:
        """Return aggregate occupancy statistics for logging/BOQ."""
        if not self.is_open():
            return {}
        rows = self._cursor.execute(
            "SELECT SUM(duct_ways), SUM(occupied), COUNT(*) FROM duct_occupancy"
        ).fetchone()
        if not rows or rows[2] == 0:
            return {"routes": 0, "total_ways": 0, "occupied_ways": 0, "spare_ways": 0}
        total_ways, occupied, n = rows
        return {
            "routes":        n,
            "total_ways":    total_ways or 0,
            "occupied_ways": occupied    or 0,
            "spare_ways":    max(0, (total_ways or 0) - (occupied or 0)),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _record_count(self) -> int:
        try:
            return self._cursor.execute(
                "SELECT COUNT(*) FROM duct_occupancy"
            ).fetchone()[0]
        except Exception:
            return 0

    def _match_by_geom(
        self,
        target_wkt: str,
        rows: list,
    ) -> Optional[tuple]:
        """Fallback geometry match — compare first/last point of WKT strings.

        WKT format for a linestring: ``LineString (x1 y1, x2 y2, ...)``
        We extract the first and last coordinate pair and compare numerically.
        Avoids full geometry parsing for performance on large ledgers.
        """
        def _extract_endpoints(wkt: str):
            try:
                coords_str = wkt.split("(", 1)[1].rstrip(")")
                coords = [c.strip().split() for c in coords_str.split(",")]
                if len(coords) < 2:
                    return None, None
                first = (float(coords[0][0]),  float(coords[0][1]))
                last  = (float(coords[-1][0]), float(coords[-1][1]))
                return first, last
            except Exception:
                return None, None

        t_first, t_last = _extract_endpoints(target_wkt)
        if t_first is None:
            return None

        tol = self.GEOM_SNAP_TOLERANCE

        def _near(a, b):
            return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol

        for row in rows:
            r_first, r_last = _extract_endpoints(row[1])
            if r_first is None:
                continue
            # Match if both endpoints align (same or reversed direction)
            if (_near(t_first, r_first) and _near(t_last, r_last)) or \
               (_near(t_first, r_last)  and _near(t_last, r_first)):
                return row
        return None
