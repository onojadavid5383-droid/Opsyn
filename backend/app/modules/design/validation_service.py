# ============================================================
# OPSYN DESIGN VALIDATION SERVICE — app/modules/design/validation_service.py
#
# Structured issues for a design's working set (plan §VALIDATION CONTRACT):
# {id, severity ERROR|WARNING|INFO, code, rule, message, asset_id,
#  cable_id, geometry, metadata}. Every run replaces the design's issues.
#
# The FTTx engine's own validators are hard gates inside a run (they raise
# on the first violation), so this service applies the engine's RULE VALUES
# — from the design's FTTXConfig and capacity profile — to every object and
# reports all of them:
#
#   DROP_TOO_LONG       drop cable > max_box_to_customer_distance (+tol)  ERROR
#   B2B_TOO_LONG        box-to-box / distribution > max_box_to_box        ERROR
#   FAT_OVER_CAPACITY   FAT customers > its ports (or the engine's 8)     ERROR
#   FDT_TOO_MANY_FATS   FATs fed > profile.max_fat_per_fdt                ERROR
#   FDT_OVER_CAPACITY   customers under an FDT > profile.max_fdt_capacity ERROR
#   WING_TOO_LONG       FATs in one wing > profile.max_fat_per_wing       ERROR
#   FAT_NOT_FED         FAT with no FDT feeding it                        ERROR
#   FDT_NOT_FED         FDT with nothing feeding it                       WARNING
#   CABLE_UNLINKED      cable with an end not attached to an asset        WARNING
#                       (a drop needs only its FAT end; a feeder from a
#                       named pickup point only its closure end)
#   HAND_DRAWN_ROUTE    cable geometry drawn by hand, not road-routed     WARNING
#   OUTSIDE_BOUNDARY    asset / cable outside the design boundary         WARNING
#   HOMEPASS_UNREACHED  homepasses beyond drop reach of every FAT         WARNING
#   NO_BOUNDARY / NO_ROADS / EMPTY_DESIGN                                  INFO
#
# A design can be submitted for review only with no ERRORs (Phase 9).
# ============================================================

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fttx_designer.config_io import config_from_dict
from app.modules.fttx_designer.engine.config import MAX_CUSTOMERS_PER_FAT, get_capacity_profile

SEVERITY_ORDER = {"ERROR": 0, "WARNING": 1, "INFO": 2}


def _issue(severity: str, code: str, message: str, *, rule: str | None = None, asset_id: Any = None,
           cable_id: Any = None, geom: str | None = None, **meta: Any) -> dict[str, Any]:
    return {"severity": severity, "code": code, "rule": rule, "message": message,
            "asset_id": str(asset_id) if asset_id else None, "cable_id": str(cable_id) if cable_id else None,
            "geometry": json.loads(geom) if geom else None, "metadata": meta}


async def run_checks(db: AsyncSession, tid: uuid.UUID, design: Any) -> list[dict[str, Any]]:
    cfg = config_from_dict(design.engine_config or {})
    profile = get_capacity_profile(cfg.pon_architecture)
    p = {"d": design.id, "tid": tid}
    issues: list[dict[str, Any]] = []

    counts = (await db.execute(text("""
        SELECT (SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL) AS assets,
               (SELECT count(*) FROM net_cables WHERE design_id = :d AND deleted_at IS NULL) AS cables,
               (SELECT count(*) FROM design_inputs WHERE design_id = :d AND layer_key = 'road') AS roads,
               (SELECT boundary IS NOT NULL FROM designs WHERE id = :d) AS has_boundary
    """), p)).one()
    if not counts.has_boundary:
        issues.append(_issue("INFO", "NO_BOUNDARY", "No boundary is drawn yet; the design area is not defined."))
    if not counts.roads:
        issues.append(_issue("INFO", "NO_ROADS", "No roads are uploaded; cables cannot be routed along roads."))
    if not counts.assets and not counts.cables:
        issues.append(_issue("INFO", "EMPTY_DESIGN", "The design has no assets or cables yet."))
        return issues

    # ── Cable lengths (engine distance rules) ────────────────
    drop_max = cfg.max_box_to_customer_distance + cfg.drop_length_tolerance
    b2b_max = cfg.max_box_to_box_distance + cfg.drop_length_tolerance
    for r in (await db.execute(text("""
        SELECT id, asset_code, cable_category, length_m::float8 AS len, route_method,
               source_asset_id, dest_asset_id, ST_AsGeoJSON(geom, 7) AS g, attributes->>'pickup' AS pickup
        FROM net_cables WHERE design_id = :d AND tenant_id = :tid AND deleted_at IS NULL
    """), p)).all():
        if r.cable_category == "DROP" and (r.len or 0) > drop_max:
            issues.append(_issue("ERROR", "DROP_TOO_LONG",
                                 f"Drop {r.asset_code} is {r.len:.0f} m; the limit is {cfg.max_box_to_customer_distance:.0f} m.",
                                 rule="max_box_to_customer_distance", cable_id=r.id, geom=r.g, length_m=r.len, limit_m=drop_max))
        if r.cable_category in ("BOX_TO_BOX", "DISTRIBUTION") and (r.len or 0) > b2b_max:
            issues.append(_issue("ERROR", "B2B_TOO_LONG",
                                 f"{r.asset_code} runs {r.len:.0f} m between boxes; the limit is {cfg.max_box_to_box_distance:.0f} m.",
                                 rule="max_box_to_box_distance", cable_id=r.id, geom=r.g, length_m=r.len, limit_m=b2b_max))
        # A drop's far end is the customer's premises (not an asset, D5); a feeder
        # starting at a named pickup point taps the backbone there (an input)
        if r.cable_category == "DROP":
            unlinked = not r.source_asset_id
        elif r.cable_category == "FEEDER" and r.pickup:
            unlinked = not r.dest_asset_id
        else:
            unlinked = not r.source_asset_id or not r.dest_asset_id
        if unlinked:
            issues.append(_issue("WARNING", "CABLE_UNLINKED",
                                 f"{r.asset_code} is not attached to an asset at {'either end' if not r.source_asset_id and not r.dest_asset_id else 'one end'}.",
                                 cable_id=r.id, geom=r.g))
        if r.route_method == "MANUAL_GEOMETRY":
            issues.append(_issue("WARNING", "HAND_DRAWN_ROUTE",
                                 f"{r.asset_code} is drawn by hand, not routed along the roads; check its length before ordering cable.",
                                 rule="route_method", cable_id=r.id, geom=r.g))

    # ── FAT / FDT capacity and feeding (engine capacity profile) ──
    fed = (await db.execute(text("""
        WITH fat AS (
            SELECT a.id, a.asset_code, a.capacity, a.attributes,
                   coalesce(a.used_capacity, CASE WHEN a.attributes->>'customers' ~ '^[0-9]+$'
                                                   THEN (a.attributes->>'customers')::int END, 0) AS customers,
                   ST_AsGeoJSON(a.geom, 7) AS g,
                   (SELECT f.id FROM net_connections k JOIN net_assets f ON f.id = k.source_asset_id
                    WHERE k.dest_asset_id = a.id AND k.deleted_at IS NULL AND f.asset_type = 'FDT' LIMIT 1) AS fdt_id,
                   (SELECT f.id FROM net_assets f WHERE f.design_id = a.design_id AND f.asset_type = 'FDT'
                      AND f.deleted_at IS NULL AND lower(f.asset_code) = lower(a.attributes->>'parent_fdt_code') LIMIT 1) AS fdt_by_code
            FROM net_assets a
            WHERE a.design_id = :d AND a.tenant_id = :tid AND a.asset_type = 'FAT' AND a.deleted_at IS NULL
        )
        SELECT *, coalesce(fdt_id, fdt_by_code) AS feeder FROM fat
    """), p)).all()
    per_fdt: dict[Any, list[Any]] = {}
    for f in fed:
        limit = f.capacity or MAX_CUSTOMERS_PER_FAT
        if f.customers > limit:
            issues.append(_issue("ERROR", "FAT_OVER_CAPACITY",
                                 f"{f.asset_code} serves {f.customers} customers; it has {limit} ports.",
                                 rule="fat_capacity", asset_id=f.id, geom=f.g, customers=f.customers, limit=limit))
        if f.feeder is None:
            issues.append(_issue("ERROR", "FAT_NOT_FED", f"{f.asset_code} is not fed by any FDT.", asset_id=f.id, geom=f.g))
        else:
            per_fdt.setdefault(f.feeder, []).append(f)

    for r in (await db.execute(text("""
        SELECT a.id, a.asset_code, ST_AsGeoJSON(a.geom, 7) AS g,
               EXISTS (SELECT 1 FROM net_connections k WHERE k.dest_asset_id = a.id AND k.deleted_at IS NULL) AS has_feed
        FROM net_assets a WHERE a.design_id = :d AND a.tenant_id = :tid AND a.asset_type = 'FDT' AND a.deleted_at IS NULL
    """), p)).all():
        fats = per_fdt.get(r.id, [])
        if len(fats) > profile.max_fat_per_fdt:
            issues.append(_issue("ERROR", "FDT_TOO_MANY_FATS",
                                 f"{r.asset_code} feeds {len(fats)} FATs; the limit is {profile.max_fat_per_fdt}.",
                                 rule="max_fat_per_fdt", asset_id=r.id, geom=r.g, fats=len(fats), limit=profile.max_fat_per_fdt))
        customers = sum(f.customers for f in fats)
        if customers > profile.max_fdt_capacity:
            issues.append(_issue("ERROR", "FDT_OVER_CAPACITY",
                                 f"{r.asset_code} serves {customers} customers; its limit is {profile.max_fdt_capacity}.",
                                 rule="max_fdt_capacity", asset_id=r.id, geom=r.g, customers=customers, limit=profile.max_fdt_capacity))
        wings: dict[str, int] = {}
        for f in fats:
            w = str((f.attributes or {}).get("wing") or "")
            if w:
                wings[w] = wings.get(w, 0) + 1
        for w, n in sorted(wings.items()):
            if n > profile.max_fat_per_wing:
                issues.append(_issue("ERROR", "WING_TOO_LONG",
                                     f"Wing {w} of {r.asset_code} has {n} FATs; the limit is {profile.max_fat_per_wing}.",
                                     rule="max_fat_per_wing", asset_id=r.id, geom=r.g, wing=w, fats=n))
        if not r.has_feed:
            issues.append(_issue("WARNING", "FDT_NOT_FED", f"Nothing recorded feeds {r.asset_code}.", asset_id=r.id, geom=r.g))

    # ── Boundary ─────────────────────────────────────────────
    if counts.has_boundary:
        for r in (await db.execute(text("""
            SELECT 'asset' AS kind, a.id, a.asset_code, ST_AsGeoJSON(a.geom, 7) AS g
            FROM net_assets a JOIN designs d ON d.id = a.design_id
            WHERE a.design_id = :d AND a.tenant_id = :tid AND a.deleted_at IS NULL AND NOT ST_Covers(d.boundary, a.geom)
            UNION ALL
            SELECT 'cable', c.id, c.asset_code, ST_AsGeoJSON(c.geom, 7)
            FROM net_cables c JOIN designs d ON d.id = c.design_id
            WHERE c.design_id = :d AND c.tenant_id = :tid AND c.deleted_at IS NULL AND NOT ST_Covers(d.boundary, c.geom)
        """), p)).all():
            issues.append(_issue("WARNING", "OUTSIDE_BOUNDARY", f"{r.asset_code} lies outside the design boundary.",
                                 asset_id=r.id if r.kind == "asset" else None,
                                 cable_id=r.id if r.kind == "cable" else None, geom=r.g))

    # ── Homepasses out of drop reach (only once FATs exist) ──
    if fed:
        unreached = (await db.execute(text("""
            SELECT count(*) AS n, ST_AsGeoJSON(ST_Collect(h.geom), 7) AS g
            FROM design_inputs h
            WHERE h.design_id = :d AND h.layer_key = 'homepass'
              AND NOT EXISTS (
                  SELECT 1 FROM net_assets f
                  WHERE f.design_id = :d AND f.asset_type = 'FAT' AND f.deleted_at IS NULL
                    AND ST_DWithin(f.geom::geography, h.geom::geography, :reach))
        """), {**p, "reach": cfg.max_box_to_customer_distance})).one()
        if unreached.n:
            issues.append(_issue("WARNING", "HOMEPASS_UNREACHED",
                                 f"{unreached.n} homepasses are more than {cfg.max_box_to_customer_distance:.0f} m from every FAT.",
                                 rule="max_box_to_customer_distance", geom=unreached.g, count=int(unreached.n)))

    issues.sort(key=lambda i: (SEVERITY_ORDER[i["severity"]], i["code"], i["message"]))
    return issues


async def validate(db: AsyncSession, tid: uuid.UUID, design: Any) -> dict[str, Any]:
    """Run every check, replace the stored issues, return them with a summary."""
    issues = await run_checks(db, tid, design)
    await db.execute(text("DELETE FROM design_validation_issues WHERE design_id = :d AND tenant_id = :tid"),
                     {"d": design.id, "tid": tid})
    for i in issues:
        await db.execute(text("""
            INSERT INTO design_validation_issues
                (tenant_id, design_id, version_id, severity, code, rule, message, asset_id, cable_id, geom, metadata)
            VALUES (:tid, :d, :v, :severity, :code, :rule, :message, CAST(:asset_id AS uuid), CAST(:cable_id AS uuid),
                    CASE WHEN CAST(:g AS text) IS NULL THEN NULL ELSE ST_SetSRID(ST_GeomFromGeoJSON(CAST(:g AS text)), 4326) END,
                    CAST(:meta AS jsonb))
        """), {"tid": tid, "d": design.id, "v": design.current_version_id, "severity": i["severity"], "code": i["code"],
               "rule": i["rule"], "message": i["message"], "asset_id": i["asset_id"], "cable_id": i["cable_id"],
               "g": json.dumps(i["geometry"]) if i["geometry"] else None, "meta": json.dumps(i["metadata"], default=str)})
    rows = await stored_issues(db, tid, design.id)
    summary = {**summarise(rows), "validated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    # The run is recorded on the current version, so "validated, no issues" is visible too
    # Merged, not replaced: an auto design version also keeps the engine's own findings there
    await db.execute(text("""
        UPDATE design_versions SET validation_summary = coalesce(validation_summary, '{}'::jsonb) || CAST(:s AS jsonb)
        WHERE id = :v
    """), {"s": json.dumps(summary), "v": design.current_version_id})
    return {"issues": rows, "summary": summary, "engine_findings": await engine_findings(db, design.current_version_id)}


async def engine_findings(db: AsyncSession, version_id: Any) -> list[dict[str, Any]]:
    """The FTTx engine's own findings from the run that produced this version (auto designs only)."""
    if not version_id:
        return []
    got = (await db.execute(text("SELECT validation_summary->'engine_findings' FROM design_versions WHERE id = :v"),
                            {"v": version_id})).scalar_one_or_none()
    return got or []


async def stored_issues(db: AsyncSession, tid: uuid.UUID, design_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (await db.execute(text("""
        SELECT id, severity, code, rule, message, asset_id, cable_id, ST_AsGeoJSON(geom, 7) AS g, metadata, created_at
        FROM design_validation_issues WHERE design_id = :d AND tenant_id = :tid
        ORDER BY CASE severity WHEN 'ERROR' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END, code, message
    """), {"d": design_id, "tid": tid})).all()
    return [{"id": str(r.id), "severity": r.severity, "code": r.code, "rule": r.rule, "message": r.message,
             "asset_id": str(r.asset_id) if r.asset_id else None, "cable_id": str(r.cable_id) if r.cable_id else None,
             "geometry": json.loads(r.g) if r.g else None, "metadata": r.metadata or {},
             "created_at": r.created_at.isoformat()} for r in rows]


def summarise(issues: list[dict[str, Any]]) -> dict[str, int]:
    out = {"errors": 0, "warnings": 0, "info": 0}
    for i in issues:
        out[{"ERROR": "errors", "WARNING": "warnings", "INFO": "info"}[i["severity"]]] += 1
    return out
