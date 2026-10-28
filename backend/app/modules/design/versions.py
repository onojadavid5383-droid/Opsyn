# ============================================================
# OPSYN DESIGN VERSIONS — app/modules/design/versions.py
# Network GIS Phase 8: no design state is ever lost.
#
# A design has one CURRENT version: its working set, inputs, boundary and
# settings, which edits change. Freezing a version stores all of that in
# its snapshot (gzip JSON, format 2) and it never changes again; a new
# current version then starts from the same state. Freezing happens:
#   save       a person names the current state (POST …/versions)
#   checkpoint before anything that would overwrite state: replacing or
#              removing inputs, an auto design, an import, a restore
# and restore puts a frozen version's state back as a NEW version
# (creation_method RESTORED) — the state it replaces is frozen first, so
# restoring is itself undoable by restoring again.
#
# Snapshot format 2: assets, cables, connections and inputs as full rows
# (to_jsonb, geometry as hex EWKB so jsonb_populate_record reads it back),
# plus boundary (hex EWKB) and engine_config. Format 1 (Phase 5, working
# set only, GeoJSON geometry) is still read.
#
# Compare matches features across versions by (kind, type, code) — ids
# change between engine runs, codes are stable — and reports added,
# removed, moved (with the distance) and changed (fields, cable length).
# ============================================================

from __future__ import annotations

import datetime
import gzip
import json
import math
import uuid
from typing import Any

from fastapi import HTTPException, status
from shapely import wkb
from shapely.geometry import mapping
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design import audit
from app.modules.design.models import Design, DesignVersion

FORMAT = 2
TABLES = ("net_assets", "net_cables", "net_connections")
GEOM = {"net_assets": ("geom", "design_geom", "asbuilt_geom"), "net_cables": ("geom", "design_geom", "asbuilt_geom"),
        "net_connections": (),
        "design_inputs": ("geom",)}
MOVED_M = 0.5
ASSET_FIELDS = ("name", "capacity", "used_capacity", "lifecycle_status", "attributes", "parent_id")
CABLE_FIELDS = ("name", "fiber_count", "route_method", "lifecycle_status", "attributes")


def _bad(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


# ── Snapshots ────────────────────────────────────────────────

async def _rows(db: AsyncSession, table: str, design_id: uuid.UUID) -> list[dict[str, Any]]:
    geoms = "".join(f" || jsonb_build_object('{c}', encode(ST_AsEWKB(t.{c}), 'hex'))" for c in GEOM[table])
    live = " AND t.deleted_at IS NULL" if table != "design_inputs" else ""
    return list((await db.execute(text(f"SELECT to_jsonb(t){geoms} FROM {table} t WHERE t.design_id = :d{live} ORDER BY t.id"),
                                  {"d": design_id})).scalars())


async def take(db: AsyncSession, design: Design) -> tuple[bytes, dict[str, int]]:
    """The design's whole current state, compressed, and what it holds."""
    payload: dict[str, Any] = {"format": FORMAT}
    for t in (*TABLES, "design_inputs"):
        payload[t.replace("net_", "")] = await _rows(db, t, design.id)
    payload["boundary"] = (await db.execute(text("SELECT encode(ST_AsEWKB(boundary), 'hex') FROM designs WHERE id = :d"),
                                            {"d": design.id})).scalar_one()
    payload["engine_config"] = design.engine_config or {}
    counts = {"assets": len(payload["assets"]), "cables": len(payload["cables"]),
              "connections": len(payload["connections"]), "inputs": len(payload["design_inputs"])}
    for a in payload["assets"]:
        counts[a["asset_type"]] = counts.get(a["asset_type"], 0) + 1
    counts["cable_m"] = round(sum(float(c.get("length_m") or 0) for c in payload["cables"]), 1)
    return gzip.compress(json.dumps(payload, default=str).encode()), counts


def unpack(snapshot: bytes) -> dict[str, Any]:
    p = json.loads(gzip.decompress(snapshot))
    p.setdefault("design_inputs", None)            # format 1: working set only
    return p


def _geojson(value: Any) -> dict[str, Any] | None:
    """A snapshot geometry — hex EWKB (format 2) or GeoJSON (format 1) — as GeoJSON."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return mapping(wkb.loads(bytes.fromhex(value)))


def _hex(value: Any) -> Any:
    """A snapshot geometry as hex EWKB (what jsonb_populate_record reads)."""
    if isinstance(value, dict):
        from shapely.geometry import shape
        return wkb.dumps(shape(value), hex=True, srid=4326)
    return value


# ── The current version and freezing ────────────────────────

async def current(db: AsyncSession, design: Design) -> DesignVersion | None:
    return await db.get(DesignVersion, design.current_version_id) if design.current_version_id else None


async def freeze(db: AsyncSession, design: Design, label: str | None = None) -> DesignVersion | None:
    """Store the current state in the current version (once; it is then immutable)."""
    v = await current(db, design)
    if v is None:
        return None
    if v.snapshot is None:
        v.snapshot, v.snapshot_counts = await take(db, design)
        v.frozen_at = datetime.datetime.now(datetime.timezone.utc)
    if label:
        v.label = label[:200]
    await db.flush()
    return v


async def start(db: AsyncSession, tid: uuid.UUID, design: Design, method: str, label: str | None,
                parent: DesignVersion | None, actor: Any) -> DesignVersion:
    """A new current version. The edit log belonged to the one before."""
    from app.modules.design.operations import clear_log
    no = (await db.execute(text("SELECT coalesce(max(version_no), 0) + 1 FROM design_versions WHERE design_id = :d"),
                           {"d": design.id})).scalar_one()
    v = DesignVersion(tenant_id=tid, design_id=design.id, version_no=no, parent_version_id=parent.id if parent else None,
                      creation_method=method, label=label[:200] if label else None, created_by=getattr(actor, "id", None))
    db.add(v)
    await db.flush()
    design.current_version_id = v.id
    await clear_log(db, design.id)
    await db.flush()
    return v


async def _has_state(db: AsyncSession, design_id: uuid.UUID) -> bool:
    return bool((await db.execute(text("""
        SELECT EXISTS (SELECT 1 FROM net_assets WHERE design_id = :d AND deleted_at IS NULL)
            OR EXISTS (SELECT 1 FROM net_cables WHERE design_id = :d AND deleted_at IS NULL)
            OR EXISTS (SELECT 1 FROM design_inputs WHERE design_id = :d)
    """), {"d": design_id})).scalar_one())


async def checkpoint(db: AsyncSession, tid: uuid.UUID, design: Design, reason: str, actor: Any) -> DesignVersion | None:
    """Before an overwrite: freeze what is there (if anything) and carry on in a new version."""
    if not await _has_state(db, design.id):
        return None
    before = await freeze(db, design)
    if before is not None and before.label is None:
        before.label = reason[:200]
    return await start(db, tid, design, "MANUAL", None, before, actor)


# ── API operations ───────────────────────────────────────────

async def _version(db: AsyncSession, design: Design, no: int) -> DesignVersion:
    v = (await db.execute(select(DesignVersion).where(DesignVersion.design_id == design.id,
                                                      DesignVersion.version_no == no))).scalar_one_or_none()
    if v is None:
        raise _bad(f"This design has no version {no}", status.HTTP_404_NOT_FOUND)
    return v


def _out(v: DesignVersion, current_id: Any, by: dict[Any, str]) -> dict[str, Any]:
    return {
        "id": str(v.id), "version_no": v.version_no, "label": v.label, "creation_method": v.creation_method,
        "created_at": v.created_at.isoformat(), "created_by": by.get(v.created_by),
        "is_current": v.id == current_id, "frozen": v.snapshot is not None,
        "frozen_at": v.frozen_at.isoformat() if v.frozen_at else None,
        "parent_version_id": str(v.parent_version_id) if v.parent_version_id else None,
        "counts": v.snapshot_counts, "validation": {k: v.validation_summary.get(k) for k in ("errors", "warnings", "validated_at")}
        if v.validation_summary else None,
    }


async def list_versions(db: AsyncSession, tid: uuid.UUID, design: Design) -> list[dict[str, Any]]:
    rows = (await db.execute(select(DesignVersion).where(DesignVersion.design_id == design.id)
                             .order_by(DesignVersion.version_no.desc()))).scalars().all()
    users = {r.id: r.label for r in (await db.execute(text("""
        SELECT u.id, coalesce(nullif(trim(sp.first_name || ' ' || sp.last_name), ''), u.username) AS label FROM users u
        LEFT JOIN staff_profiles sp ON sp.user_id = u.id WHERE u.id = ANY(:ids)
    """), {"ids": [r.created_by for r in rows if r.created_by]})).all()} if any(r.created_by for r in rows) else {}
    out = [_out(v, design.current_version_id, users) for v in rows]
    for o in out:          # the current version's counts are live
        if o["is_current"]:
            o["counts"] = await _live_counts(db, design.id)
    return out


async def _live_counts(db: AsyncSession, design_id: uuid.UUID) -> dict[str, Any]:
    r = (await db.execute(text("""
        SELECT (SELECT count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL) AS assets,
               (SELECT count(*) FROM net_cables WHERE design_id = :d AND deleted_at IS NULL) AS cables,
               (SELECT count(*) FROM net_connections WHERE design_id = :d AND deleted_at IS NULL) AS connections,
               (SELECT count(*) FROM design_inputs WHERE design_id = :d) AS inputs,
               (SELECT coalesce(round(sum(length_m)::numeric, 1), 0)::float8 FROM net_cables WHERE design_id = :d AND deleted_at IS NULL) AS cable_m
    """), {"d": design_id})).one()
    out: dict[str, Any] = dict(r._mapping)
    for t, n in (await db.execute(text("SELECT asset_type, count(*) FROM net_assets WHERE design_id = :d AND deleted_at IS NULL "
                                       "GROUP BY 1"), {"d": design_id})).all():
        out[t] = int(n)
    return out


async def save(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, label: str) -> dict[str, Any]:
    from app.modules.design.service import ensure_editable
    ensure_editable(design)
    label = (label or "").strip()
    if not label:
        raise _bad("Give the version a name")
    saved = await freeze(db, design, label)
    if saved is None:
        raise _bad("This design has no version to save", status.HTTP_409_CONFLICT)
    await start(db, tid, design, "MANUAL", None, saved, caller)
    await audit.summary(db, tid, design.id, "version_saved", caller, None,
                        {"version_no": saved.version_no, "label": label, "counts": saved.snapshot_counts})
    return {"saved": _out(saved, design.current_version_id, {}), "versions": await list_versions(db, tid, design)}


def _features_from(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """A snapshot's assets and cables as map features (the same properties as the working set)."""
    feats = []
    for a in payload.get("assets") or []:
        feats.append({"type": "Feature", "geometry": _geojson(a.get("geom")), "properties": {
            "kind": "asset", "id": a["id"], "asset_code": a["asset_code"], "asset_type": a["asset_type"],
            "name": a.get("name") or "", "lifecycle_status": a.get("lifecycle_status"),
            "creation_method": a.get("creation_method"), "capacity": a.get("capacity"),
            "used_capacity": a.get("used_capacity"), "attributes": a.get("attributes") or {}, "parent_id": a.get("parent_id")}})
    for c in payload.get("cables") or []:
        feats.append({"type": "Feature", "geometry": _geojson(c.get("geom")), "properties": {
            "kind": "cable", "id": c["id"], "asset_code": c["asset_code"], "cable_category": c["cable_category"],
            "name": c.get("name") or "", "lifecycle_status": c.get("lifecycle_status"), "fiber_count": c.get("fiber_count"),
            "length_m": float(c["length_m"]) if c.get("length_m") is not None else None,
            "route_method": c.get("route_method"), "attributes": c.get("attributes") or {}}})
    return feats


async def version_features(db: AsyncSession, tid: uuid.UUID, design: Design, no: int) -> dict[str, Any]:
    v = await _version(db, design, no)
    if v.id == design.current_version_id or v.snapshot is None:
        if v.id != design.current_version_id:
            raise _bad(f"Version {no} was never frozen, so its state wasn't kept", status.HTTP_409_CONFLICT)
        payload = {"assets": await _rows(db, "net_assets", design.id), "cables": await _rows(db, "net_cables", design.id)}
    else:
        payload = unpack(v.snapshot)
    return {"type": "FeatureCollection", "version_no": no, "features": _features_from(payload)}


# ── Compare ──────────────────────────────────────────────────

def _key(f: dict[str, Any]) -> tuple[str, str, str]:
    p = f["properties"]
    return (p["kind"], p.get("asset_type") or p.get("cable_category") or "", p["asset_code"])


def _metres(a: list[float], b: list[float]) -> float:
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot(math.radians(b[0] - a[0]) * math.cos(lat), math.radians(b[1] - a[1])) * 6_371_000


def compare_features(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> dict[str, Any]:
    """added / removed / moved / changed between two feature lists (pure; unit-tested)."""
    a = {_key(f): f for f in old}
    b = {_key(f): f for f in new}
    added = [b[k] for k in b if k not in a]
    removed = [a[k] for k in a if k not in b]
    moved, changed = [], []
    for k in a.keys() & b.keys():
        fa, fb = a[k], b[k]
        pa, pb = fa["properties"], fb["properties"]
        if pa["kind"] == "asset":
            ca, cb = fa["geometry"]["coordinates"], fb["geometry"]["coordinates"]
            d = _metres(ca, cb) if fa["geometry"]["type"] == fb["geometry"]["type"] == "Point" else 0.0
            if d > MOVED_M:
                moved.append({"kind": "asset", "code": pa["asset_code"], "type": pa["asset_type"], "id": pb["id"],
                              "from": ca, "to": cb, "distance_m": round(d, 1)})
            fields = [f for f in ASSET_FIELDS if f != "parent_id" and pa.get(f) != pb.get(f)]
        else:
            fields = [f for f in CABLE_FIELDS if pa.get(f) != pb.get(f)]
            if fa["geometry"] != fb["geometry"]:
                fields.append("geometry")
        if fields:
            entry = {"kind": pa["kind"], "code": pa["asset_code"], "id": pb["id"], "fields": fields,
                     "before": {f: pa.get(f) for f in fields if f != "geometry"},
                     "after": {f: pb.get(f) for f in fields if f != "geometry"}}
            if pa["kind"] == "cable":
                entry["length_before_m"], entry["length_after_m"] = pa.get("length_m"), pb.get("length_m")
                if "geometry" in fields:
                    entry["geometry_before"] = fa["geometry"]
            changed.append(entry)
    return {"added": added, "removed": removed, "moved": moved, "changed": changed,
            "counts": {"added": len(added), "removed": len(removed), "moved": len(moved), "changed": len(changed)}}


async def compare(db: AsyncSession, tid: uuid.UUID, design: Design, a: int, b: int) -> dict[str, Any]:
    if a == b:
        raise _bad("Pick two different versions")
    fa = await version_features(db, tid, design, a)
    fb = await version_features(db, tid, design, b)
    return {"from": a, "to": b, **compare_features(fa["features"], fb["features"])}


# ── Restore ──────────────────────────────────────────────────

async def _insert(db: AsyncSession, table: str, rows: list[dict[str, Any]]) -> None:
    for c in GEOM[table]:
        for r in rows:
            if c in r:
                r[c] = _hex(r[c])
    if table == "net_assets":
        ids = {r["id"] for r in rows}
        rows = sorted(rows, key=lambda r: 1 if r.get("parent_id") in ids else 0)
    for r in rows:
        await db.execute(text(f"INSERT INTO {table} SELECT * FROM jsonb_populate_record(NULL::{table}, CAST(:r AS jsonb))"),
                         {"r": json.dumps(r, default=str)})


async def restore(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design, no: int) -> dict[str, Any]:
    from app.modules.design import validation_service
    from app.modules.design.service import ensure_editable
    ensure_editable(design)
    target = await _version(db, design, no)
    if target.id == design.current_version_id:
        raise _bad(f"Version {no} is the current version", status.HTTP_409_CONFLICT)
    if target.snapshot is None:
        raise _bad(f"Version {no} was never frozen, so there is nothing to restore", status.HTTP_409_CONFLICT)
    payload = unpack(target.snapshot)

    # What is there now is kept first
    replaced = await freeze(db, design)
    if replaced is not None and replaced.label is None:
        replaced.label = f"Before restoring version {no}"
    await audit.bulk(db)
    for t in ("net_connections", "net_cables", "net_assets"):
        await db.execute(text(f"DELETE FROM {t} WHERE design_id = :d"), {"d": design.id})
    if payload.get("design_inputs") is not None:
        await db.execute(text("DELETE FROM design_inputs WHERE design_id = :d"), {"d": design.id})
        await _insert(db, "design_inputs", payload["design_inputs"])
    await _insert(db, "net_assets", payload.get("assets") or [])
    await _insert(db, "net_cables", payload.get("cables") or [])
    await _insert(db, "net_connections", payload.get("connections") or [])
    if "boundary" in payload:
        await db.execute(text("UPDATE designs SET boundary = CASE WHEN CAST(:b AS text) IS NULL THEN NULL "
                              "ELSE ST_GeomFromEWKB(decode(:b, 'hex')) END WHERE id = :d"),
                         {"b": payload["boundary"], "d": design.id})
        design.engine_config = payload.get("engine_config") or {}
    await audit.bulk(db, on=False)
    new = await start(db, tid, design, "RESTORED", f"Restored from version {no}", target, caller)
    design.status = "MODIFIED" if design.status not in ("DRAFT",) else design.status
    design.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.flush()
    await db.refresh(design)
    validation = await validation_service.validate(db, tid, design)
    await audit.summary(db, tid, design.id, "version_restored", caller,
                        {"version_no": replaced.version_no if replaced else None},
                        {"restored_from": no, "version_no": new.version_no, "counts": target.snapshot_counts})
    return {"version_no": new.version_no, "restored_from": no, "kept_as": replaced.version_no if replaced else None,
            "validation": validation["summary"], "inputs_restored": payload.get("design_inputs") is not None}
