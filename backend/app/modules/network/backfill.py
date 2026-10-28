# ============================================================
# OPSYN NETWORK BACKFILL — app/modules/network/backfill.py
#
# Copies the uploaded FTTH assets (olts, cabinets, splitter_boxes) into
# net_assets. Used twice:
#   - migration 0087, once, for every tenant (tenant filter = NULL)
#   - POST /network/assets/sync-uploaded, for the caller's tenant, until
#     Phase 2 makes the upload commit write net_assets directly
#
# Idempotent: every row is keyed by (tenant_id, source_table, source_id),
# so a re-run updates instead of duplicating. A source row that has been
# soft-deleted (or no longer exists) soft-deletes its mirror.
#
# Since Phase 2 the upload commit and bulk deletion call mirror_uploaded()
# themselves (dual-write), so the endpoint is only needed to repair drift.
#
# Nothing is guessed. The uploaded splitter → cabinet and splitter →
# parent-splitter links are kept as attributes.legacy_* references;
# they become real topology (net_connections) in Phase 3. parent_id is
# NOT set from them — a splitter box with its own coordinates is placed
# beside its cabinet, not inside it, and parent_id means containment.
#
# If a live asset of the same type already holds the code (e.g. created
# by hand), the uploaded row is skipped and counted, never overwritten.
#
# Migration 0087 imports BACKFILL_STATEMENTS from here. Changing what they
# do means writing a new migration, not editing these in place.
# ============================================================

from __future__ import annotations

from dataclasses import dataclass

# (source table, asset type, code column, SELECT of the mapped columns)
_SOURCES: tuple[tuple[str, str, str, str], ...] = (
    (
        "olts", "OLT", "name",
        """
        SELECT s.tenant_id, s.name AS asset_code, s.name AS name,
               s.location_description AS description, s.location AS geom,
               NULL::int AS capacity,
               jsonb_strip_nulls(jsonb_build_object(
                   'number_of_odf', s.number_of_odf,
                   'legacy_upload_session_id', s.upload_session_id::text
               )) AS attributes,
               s.id AS source_id, s.created_by, s.created_at
        FROM olts s
        """,
    ),
    (
        "cabinets", "CABINET", "cabinet_id",
        """
        SELECT s.tenant_id, s.cabinet_id AS asset_code, s.cabinet_id AS name,
               NULL::text AS description, s.location AS geom,
               s.capacity AS capacity,
               jsonb_strip_nulls(jsonb_build_object(
                   'number_tray', s.number_tray,
                   'legacy_upload_session_id', s.upload_session_id::text
               )) AS attributes,
               s.id AS source_id, s.created_by, s.created_at
        FROM cabinets s
        """,
    ),
    (
        "splitter_boxes", "SPLITTER", "box_id",
        """
        SELECT s.tenant_id, s.box_id AS asset_code, s.box_id AS name,
               NULL::text AS description, s.location AS geom,
               s.output_ports AS capacity,
               jsonb_strip_nulls(jsonb_build_object(
                   'input_ports', s.input_ports,
                   'output_ports', s.output_ports,
                   'split_ratio', '1:' || s.output_ports,
                   'splitter_level', s.splitter_level,
                   'splitter_type', s.splitter_type,
                   'number_customer', s.number_customer,
                   'legacy_upload_session_id', s.upload_session_id::text
               )) AS attributes,
               s.id AS source_id, s.created_by, s.created_at
        FROM splitter_boxes s
        """,
    ),
)

# :tid is NULL for "every tenant" (the migration) or one tenant's id.
_TENANT_FILTER = "(CAST(:tid AS uuid) IS NULL OR s.tenant_id = CAST(:tid AS uuid))"


def _upsert(source_table: str, asset_type: str, select_sql: str) -> str:
    return f"""
    WITH src AS (
        {select_sql}
        WHERE NOT s.is_deleted AND {_TENANT_FILTER}
    )
    INSERT INTO net_assets (
        tenant_id, asset_code, asset_type, name, description, geom,
        lifecycle_status, creation_method, capacity, attributes,
        source_table, source_id, created_by, created_at, updated_at
    )
    SELECT src.tenant_id, src.asset_code, '{asset_type}', src.name, src.description, src.geom,
           'ACTIVE', 'IMPORTED', src.capacity, src.attributes,
           '{source_table}', src.source_id, src.created_by, src.created_at, now()
    FROM src
    WHERE NOT EXISTS (
        SELECT 1 FROM net_assets n
        WHERE n.tenant_id  = src.tenant_id
          AND n.asset_type = '{asset_type}'
          AND n.asset_code = src.asset_code
          AND n.design_id  IS NULL
          AND n.deleted_at IS NULL
          AND (n.source_table IS DISTINCT FROM '{source_table}' OR n.source_id <> src.source_id)
    )
    ON CONFLICT (tenant_id, source_table, source_id) WHERE source_table IS NOT NULL
    DO UPDATE SET
        asset_code  = EXCLUDED.asset_code,
        name        = EXCLUDED.name,
        description = EXCLUDED.description,
        geom        = EXCLUDED.geom,
        capacity    = EXCLUDED.capacity,
        attributes  = net_assets.attributes || EXCLUDED.attributes,
        deleted_at  = NULL,
        deleted_by  = NULL,
        updated_at  = now()
    """


def _retire_orphans(source_table: str) -> str:
    """Soft-delete mirrors whose source row is soft-deleted or gone."""
    return f"""
    UPDATE net_assets n
    SET deleted_at = now(), updated_at = now()
    WHERE n.source_table = '{source_table}'
      AND n.deleted_at IS NULL
      AND (CAST(:tid AS uuid) IS NULL OR n.tenant_id = CAST(:tid AS uuid))
      AND NOT EXISTS (
          SELECT 1 FROM {source_table} s
          WHERE s.id = n.source_id AND NOT s.is_deleted
      )
    """


# Refresh the splitter's references to its cabinet / parent splitter.
_LINK_REFERENCES = """
UPDATE net_assets n
SET attributes = (n.attributes - 'legacy_cabinet_asset_id' - 'legacy_cabinet_code'
                               - 'legacy_parent_splitter_asset_id' - 'legacy_parent_splitter_code')
               || jsonb_strip_nulls(jsonb_build_object(
                    'legacy_cabinet_asset_id',         c.id::text,
                    'legacy_cabinet_code',             c.asset_code,
                    'legacy_parent_splitter_asset_id', p.id::text,
                    'legacy_parent_splitter_code',     p.asset_code
                  ))
FROM splitter_boxes s
LEFT JOIN net_assets c ON c.source_table = 'cabinets'       AND c.source_id = s.cabinet_id         AND c.deleted_at IS NULL
LEFT JOIN net_assets p ON p.source_table = 'splitter_boxes' AND p.source_id = s.parent_splitter_id AND p.deleted_at IS NULL
WHERE n.source_table = 'splitter_boxes'
  AND n.source_id = s.id
  AND n.deleted_at IS NULL
  AND (CAST(:tid AS uuid) IS NULL OR n.tenant_id = CAST(:tid AS uuid))
"""

BACKFILL_STATEMENTS: tuple[str, ...] = (
    *(_upsert(t, a, sql) for t, a, _code, sql in _SOURCES),
    *(_retire_orphans(t) for t, _a, _code, _sql in _SOURCES),
    _LINK_REFERENCES,
)


def _skipped_sql(source_table: str, asset_type: str, code_column: str) -> str:
    """Live source rows with no mirror because another asset holds the code."""
    return f"""
    SELECT '{source_table}' AS source_table, s.{code_column} AS asset_code
    FROM {source_table} s
    WHERE NOT s.is_deleted AND {_TENANT_FILTER}
      AND NOT EXISTS (
          SELECT 1 FROM net_assets n
          WHERE n.source_table = '{source_table}' AND n.source_id = s.id AND n.deleted_at IS NULL
      )
    """


SKIPPED_SQL: str = " UNION ALL ".join(_skipped_sql(t, a, c) for t, a, c, _sql in _SOURCES)

COUNT_SQL = """
SELECT source_table, count(*) AS n
FROM net_assets
WHERE source_table IN ('olts', 'cabinets', 'splitter_boxes')
  AND deleted_at IS NULL
  AND (CAST(:tid AS uuid) IS NULL OR tenant_id = CAST(:tid AS uuid))
GROUP BY source_table
"""


@dataclass
class BackfillResult:
    mirrored: dict[str, int]
    skipped: list[dict[str, str]]


async def mirror_uploaded(db, tenant_id) -> None:
    """Re-mirror one tenant's uploaded OLT/cabinet/splitter rows.

    Called by the upload commit and the bulk deletion (Phase 2 dual-write),
    inside their savepoint, so the live tables and net_assets change
    together or not at all.
    """
    from sqlalchemy import text

    params = {"tid": str(tenant_id)}
    for stmt in BACKFILL_STATEMENTS:
        await db.execute(text(stmt), params)
    # Uploaded splitter links become connections (Phase 3)
    from app.modules.network.topology import sync_derived_connections
    await sync_derived_connections(db, tenant_id)


async def run_backfill(db, tenant_id) -> BackfillResult:
    """Run the backfill for one tenant inside the caller's transaction."""
    from sqlalchemy import text

    params = {"tid": str(tenant_id)}
    await mirror_uploaded(db, tenant_id)
    counts = {r.source_table: r.n for r in (await db.execute(text(COUNT_SQL), params)).all()}
    skipped = [
        {"source_table": r.source_table, "asset_code": r.asset_code}
        for r in (await db.execute(text(SKIPPED_SQL), params)).all()
    ]
    return BackfillResult(
        mirrored={t: counts.get(t, 0) for t, *_ in _SOURCES},
        skipped=skipped,
    )
