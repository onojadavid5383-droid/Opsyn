# ============================================================
# OPSYN DESIGN OPERATIONS — app/modules/design/operations.py
# Network GIS Phase 6, Track B: manual design (plan §3.7). Independent of
# auto design (Phase 5): only the Phase 4 container and services are shared.
#
#   ADD_ASSET        place a device (code generated if none given)
#   MOVE_ASSET       move it with its splitter children; its cables are
#                    recalculated locally (recalc.py, Phase 7): re-routed
#                    along the roads, drops redrawn straight; recalc=false
#                    only moves their ends
#   DELETE_ASSET     remove it with its children and connections; its
#                    cables too unless keep_cables
#   UPDATE_ATTRS     name, code, capacity, customers, attributes, fibres
#   DRAW_CABLE       between assets or points; route "road" (default) is
#                    the engine's Dijkstra over the design's roads, "straight"
#                    a direct line (DIRECT for drops, else hand-drawn). A
#                    feeding cable (box-to-box, distribution, closure-FDT,
#                    feeder) between two assets also records the FEED
#                    connection, and a FAT at its end takes the FDT that
#                    heads the chain as parent_fdt_code — so a hand-built
#                    PCC chain FDT → FAT → FAT validates like an engine one
#   EDIT_CABLE_GEOM  redraw a cable's line (hand-drawn from then on)
#   SPLIT_CABLE      cut a cable in two at a point, optionally placing a
#                    device (e.g. a closure) at the cut
#   EXTEND_CABLE     lengthen a cable from one end to an asset or point
#   CONNECT / DISCONNECT   FEED/SPLIT/SPLICE/PATCH/DROP/UPLINK links
#
# Every operation runs in one transaction and is logged in
# design_operations with the before and after images of every row it
# touched (Tracker). Undo writes the before images back, redo the after
# images: exact, deterministic, and on the server — so undo/redo survive a
# reload and never re-run routing. A new operation drops the redo branch;
# a new version (auto design, import) clears the log.
#
# Every answer (operation, undo, redo) carries deltas (Phase 7): the
# features to redraw and ids removed, BOQ lines changed, issues new and
# resolved — the client patches its cache from them.
# ============================================================

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any, Callable

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.design import recalc, routing_service, validation_service
from app.modules.design.models import Design
from app.modules.fttx_designer.engine.config import MAX_CUSTOMERS_PER_FAT
from app.modules.network.asset_types import ASSET_TYPES, CABLE_CATEGORIES, CONNECTION_TYPES
from app.modules.network.codes import next_codes

LIFECYCLE = "DESIGNED"
TABLES = ("net_assets", "net_cables", "net_connections")
# Geometry goes into row images as hex EWKB: to_jsonb() would write GeoJSON,
# which jsonb_populate_record() can't read back into a geometry column
GEOM_COLS = {"net_assets": ("geom", "design_geom", "asbuilt_geom"), "net_cables": ("geom", "design_geom", "asbuilt_geom"),
             "net_connections": ()}
FEEDING_CABLES = ("BOX_TO_BOX", "DISTRIBUTION", "CLOSURE_FDT", "FEEDER")
OP_LABEL = {
    "ADD_ASSET": "Add", "MOVE_ASSET": "Move", "DELETE_ASSET": "Delete", "UPDATE_ATTRS": "Edit details",
    "DRAW_CABLE": "Draw cable", "EDIT_CABLE_GEOM": "Redraw cable", "SPLIT_CABLE": "Split cable",
    "EXTEND_CABLE": "Extend cable", "CONNECT": "Connect", "DISCONNECT": "Disconnect", "DELETE_CABLE": "Delete cable",
}
_columns: dict[str, list[str]] = {}


def _bad(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def _uuid(v: Any, what: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(v))
    except (TypeError, ValueError):
        raise _bad(f"{what} is not a valid id") from None


# ── Row images ───────────────────────────────────────────────

async def _cols(db: AsyncSession, table: str) -> list[str]:
    if table not in _columns:
        _columns[table] = list((await db.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = :t AND table_schema = current_schema() "
            "ORDER BY ordinal_position"), {"t": table})).scalars())
    return _columns[table]


async def _rows(db: AsyncSession, table: str, ids: list[uuid.UUID]) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}
    geoms = "".join(f" || jsonb_build_object('{c}', encode(ST_AsEWKB(t.{c}), 'hex'))" for c in GEOM_COLS[table])
    got = (await db.execute(text(f"SELECT id, to_jsonb(t){geoms} AS row FROM {table} t WHERE id = ANY(:ids)"),
                            {"ids": list(ids)})).all()
    return {str(r.id): r.row for r in got}


class Tracker:
    """Before/after images of every row an operation touches."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.before: dict[str, dict[str, dict[str, Any]]] = {t: {} for t in TABLES}
        self.created: dict[str, set[str]] = {t: set() for t in TABLES}

    async def touch(self, table: str, ids: list[Any]) -> None:
        """Snapshot rows about to be changed or deleted (first snapshot wins)."""
        todo = [uuid.UUID(str(i)) for i in ids if i and str(i) not in self.before[table] and str(i) not in self.created[table]]
        self.before[table].update(await _rows(self.db, table, todo))

    def made(self, table: str, row_id: Any) -> None:
        self.created[table].add(str(row_id))

    async def patches(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """(forward, inverse). Each: delete ids, restore rows, update rows — per table."""
        fwd: dict[str, Any] = {"delete": {}, "restore": {}, "update": {}}
        inv: dict[str, Any] = {"delete": {}, "restore": {}, "update": {}}
        for t in TABLES:
            after_created = await _rows(self.db, t, list(self.created[t]))
            after_touched = await _rows(self.db, t, list(self.before[t]))
            deleted = [i for i in self.before[t] if i not in after_touched]
            updated = [i for i in self.before[t] if i in after_touched and after_touched[i] != self.before[t][i]]
            fwd["delete"][t] = deleted
            fwd["restore"][t] = list(after_created.values())
            fwd["update"][t] = [after_touched[i] for i in updated]
            inv["delete"][t] = list(after_created)
            inv["restore"][t] = [self.before[t][i] for i in deleted]
            inv["update"][t] = [self.before[t][i] for i in updated]
        return fwd, inv


def _parents_first(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = {r["id"] for r in rows}
    return sorted(rows, key=lambda r: 1 if r.get("parent_id") in ids else 0)


async def apply_patch(db: AsyncSession, patch: dict[str, Any]) -> None:
    """Delete, then restore (assets before cables before connections), then update."""
    for t in reversed(TABLES):
        ids = patch["delete"].get(t) or []
        if ids:
            await db.execute(text(f"DELETE FROM {t} WHERE id = ANY(:ids)"), {"ids": [uuid.UUID(i) for i in ids]})
    for t in TABLES:
        rows = patch["restore"].get(t) or []
        if t == "net_assets":
            rows = _parents_first(rows)
        for row in rows:
            await db.execute(text(f"INSERT INTO {t} SELECT * FROM jsonb_populate_record(NULL::{t}, CAST(:r AS jsonb))"),
                             {"r": json.dumps(row)})
    for t in TABLES:
        rows = patch["update"].get(t) or []
        if not rows:
            continue
        cols = [c for c in await _cols(db, t) if c != "id"]
        sets = ", ".join(f"{c} = r.{c}" for c in cols)
        for row in rows:
            await db.execute(text(f"UPDATE {t} SET {sets} FROM jsonb_populate_record(NULL::{t}, CAST(:r AS jsonb)) r "
                                  f"WHERE {t}.id = r.id"), {"r": json.dumps(row)})


# ── Lookups ──────────────────────────────────────────────────

async def _asset(db: AsyncSession, design: Design, asset_id: Any, *, live_ok: bool = False) -> Any:
    aid = _uuid(asset_id, "The asset")
    r = (await db.execute(text("""
        SELECT id, asset_code, asset_type, design_id, attributes, ST_X(ST_PointOnSurface(geom)) AS lng,
               ST_Y(ST_PointOnSurface(geom)) AS lat
        FROM net_assets WHERE id = :id AND tenant_id = :tid AND deleted_at IS NULL
          AND (design_id = :d OR (:live AND design_id IS NULL))
    """), {"id": aid, "tid": design.tenant_id, "d": design.id, "live": live_ok})).first()
    if r is None:
        raise _bad("That asset is not in this design" + (" or the live network" if live_ok else ""), status.HTTP_404_NOT_FOUND)
    return r


async def _cable(db: AsyncSession, design: Design, cable_id: Any) -> Any:
    cid = _uuid(cable_id, "The cable")
    r = (await db.execute(text("""
        SELECT id, asset_code, cable_category, route_method, source_asset_id, dest_asset_id, fiber_count,
               ST_AsGeoJSON(geom, 7) AS g
        FROM net_cables WHERE id = :id AND design_id = :d AND tenant_id = :tid AND deleted_at IS NULL
    """), {"id": cid, "d": design.id, "tid": design.tenant_id})).first()
    if r is None:
        raise _bad("That cable is not in this design", status.HTTP_404_NOT_FOUND)
    return r


def _point(p: dict[str, Any], what: str = "The point") -> tuple[float, float]:
    try:
        lng, lat = float(p["lng"]), float(p["lat"])
    except (KeyError, TypeError, ValueError):
        raise _bad(f"{what} needs lng and lat") from None
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        raise _bad(f"{what} is out of range")
    return lng, lat


async def _end(db: AsyncSession, design: Design, end: dict[str, Any] | None, label: str) -> tuple[float, float, Any]:
    """A cable end: an asset of the design (or live network) or a point. → (lng, lat, asset row | None)."""
    if not end:
        raise _bad(f"Give the cable's {label}")
    if end.get("asset_id"):
        a = await _asset(db, design, end["asset_id"], live_ok=True)
        return float(a.lng), float(a.lat), a
    lng, lat = _point(end, f"The cable's {label}")
    return lng, lat, None


async def _road_line(db: AsyncSession, design: Design, a: tuple[float, float], b: tuple[float, float]) -> list[list[float]]:
    """Road-graph route that starts and ends exactly at the two points."""
    r = await routing_service.route(db, design.tenant_id, design, {"lng": a[0], "lat": a[1]}, {"lng": b[0], "lat": b[1]})
    coords = [list(c) for c in r["geometry"]["coordinates"]]
    if coords[0] != [a[0], a[1]]:
        coords.insert(0, [a[0], a[1]])
    if coords[-1] != [b[0], b[1]]:
        coords.append([b[0], b[1]])
    return coords


def _dedupe(coords: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for c in coords:
        if not out or abs(out[-1][0] - c[0]) > 1e-9 or abs(out[-1][1] - c[1]) > 1e-9:
            out.append(c)
    if len(out) < 2:
        raise _bad("The two ends are at the same spot")
    return out


# ── Operations ───────────────────────────────────────────────

DEFAULT_CAPACITY = {"FAT": MAX_CUSTOMERS_PER_FAT}


async def _add_asset(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    t = str(p.get("asset_type") or "").upper()
    if t not in ASSET_TYPES:
        raise _bad(f"Unknown asset type '{t}'")
    lng, lat = _point(p)
    code = (p.get("asset_code") or "").strip() or (await next_codes(db, design.tenant_id, "asset", t))[0]
    if (await db.execute(text("SELECT 1 FROM net_assets WHERE design_id = :d AND asset_type = :t AND asset_code = :c "
                              "AND deleted_at IS NULL"), {"d": design.id, "t": t, "c": code})).first():
        raise _bad(f"{code} is already used in this design", status.HTTP_409_CONFLICT)
    parent = None
    if p.get("parent_id"):
        parent = (await _asset(db, design, p["parent_id"])).id
    aid = uuid.uuid4()
    attrs = dict(p.get("attributes") or {})
    await db.execute(text("""
        INSERT INTO net_assets (id, tenant_id, design_id, project_id, asset_code, asset_type, name, geom, parent_id,
                                capacity, used_capacity, lifecycle_status, creation_method, attributes, created_by)
        VALUES (:id, :tid, :d, :p, :code, :type, :name, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), :parent,
                :cap, :used, :life, 'MANUAL', CAST(:attrs AS jsonb), :by)
    """), {"id": aid, "tid": design.tenant_id, "d": design.id, "p": design.project_id, "code": code, "type": t,
           "name": p.get("name") or None, "lng": lng, "lat": lat, "parent": parent,
           "cap": p.get("capacity", DEFAULT_CAPACITY.get(t)), "used": p.get("used_capacity"), "life": LIFECYCLE,
           "attrs": json.dumps(attrs), "by": getattr(actor, "id", None)})
    tr.made("net_assets", aid)
    return {"label": f"Add {code}", "asset_id": str(aid), "asset_code": code}


async def _move_asset(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    a = await _asset(db, design, p.get("id"))
    lng, lat = _point(p)
    kids = list((await db.execute(text("SELECT id FROM net_assets WHERE parent_id = :id AND design_id = :d"),
                                  {"id": a.id, "d": design.id})).scalars())
    cables = (await db.execute(text("""
        SELECT id, source_asset_id, dest_asset_id FROM net_cables
        WHERE design_id = :d AND deleted_at IS NULL AND (source_asset_id = :id OR dest_asset_id = :id)
    """), {"id": a.id, "d": design.id})).all()
    await tr.touch("net_assets", [a.id, *kids])
    await tr.touch("net_cables", [c.id for c in cables])
    pt = "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)"
    await db.execute(text(f"UPDATE net_assets SET geom = {pt}, updated_at = now() WHERE id = ANY(:ids)"),
                     {"lng": lng, "lat": lat, "ids": [a.id, *kids]})
    if p.get("recalc", True):
        rerouted = await recalc.reroute(db, design, tr, [a.id, *kids])
        return {"label": f"Move {a.asset_code}", "asset_id": str(a.id), "cables_followed": len(rerouted),
                "rerouted": rerouted}
    for c in cables:
        if c.source_asset_id == a.id:
            await db.execute(text(f"UPDATE net_cables SET geom = ST_SetPoint(geom, 0, {pt}), updated_at = now() WHERE id = :id"),
                             {"lng": lng, "lat": lat, "id": c.id})
        if c.dest_asset_id == a.id:
            await db.execute(text(f"UPDATE net_cables SET geom = ST_SetPoint(geom, ST_NPoints(geom) - 1, {pt}), "
                                  "updated_at = now() WHERE id = :id"), {"lng": lng, "lat": lat, "id": c.id})
    return {"label": f"Move {a.asset_code}", "asset_id": str(a.id), "cables_followed": len(cables)}


async def _delete_asset(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    a = await _asset(db, design, p.get("id"))
    kids = list((await db.execute(text("SELECT id FROM net_assets WHERE parent_id = :id AND design_id = :d"),
                                  {"id": a.id, "d": design.id})).scalars())
    ids = [a.id, *kids]
    links = list((await db.execute(text("""
        SELECT id FROM net_connections WHERE source_asset_id = ANY(:ids) OR dest_asset_id = ANY(:ids)
    """), {"ids": ids})).scalars())
    cables = list((await db.execute(text("""
        SELECT id FROM net_cables WHERE design_id = :d AND (source_asset_id = ANY(:ids) OR dest_asset_id = ANY(:ids))
    """), {"ids": ids, "d": design.id})).scalars())
    # The FATs this FDT headed lose it as their parent
    orphans = list((await db.execute(text("""
        SELECT id FROM net_assets WHERE design_id = :d AND asset_type = 'FAT'
          AND lower(attributes->>'parent_fdt_code') = lower(:code)
    """), {"d": design.id, "code": a.asset_code})).scalars()) if a.asset_type == "FDT" else []
    await tr.touch("net_assets", [*ids, *orphans])
    await tr.touch("net_connections", links)
    await tr.touch("net_cables", cables)
    if orphans:
        await db.execute(text("UPDATE net_assets SET attributes = attributes - 'parent_fdt_code' WHERE id = ANY(:ids)"),
                         {"ids": orphans})
    if cables and not p.get("keep_cables"):
        await db.execute(text("DELETE FROM net_cables WHERE id = ANY(:ids)"), {"ids": cables})
    await db.execute(text("DELETE FROM net_assets WHERE id = ANY(:ids)"), {"ids": ids})
    return {"label": f"Delete {a.asset_code}", "removed_cables": 0 if p.get("keep_cables") else len(cables)}


ASSET_FIELDS = ("name", "asset_code", "capacity", "used_capacity")
CABLE_FIELDS = ("name", "asset_code", "fiber_count", "cable_category")


async def _update_attrs(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    target = p.get("target", "asset")
    changes = dict(p.get("changes") or {})
    if target == "asset":
        row = await _asset(db, design, p.get("id"))
        table, fields = "net_assets", ASSET_FIELDS
    elif target == "cable":
        row = await _cable(db, design, p.get("id"))
        table, fields = "net_cables", CABLE_FIELDS
        if "cable_category" in changes and changes["cable_category"] not in CABLE_CATEGORIES:
            raise _bad(f"Unknown cable category '{changes['cable_category']}'")
    else:
        raise _bad("target must be asset or cable")
    unknown = set(changes) - set(fields) - {"attributes"}
    if unknown:
        raise _bad(f"These can't be changed here: {', '.join(sorted(unknown))}")
    for k in ("capacity", "used_capacity", "fiber_count"):
        if k in changes and changes[k] is not None and (not isinstance(changes[k], int) or changes[k] < 0):
            raise _bad(f"{k} must be a whole number of 0 or more")
    if "asset_code" in changes and not str(changes["asset_code"] or "").strip():
        raise _bad("The code can't be empty")
    await tr.touch(table, [row.id])
    sets, params = [], {"id": row.id}
    for k in fields:
        if k in changes:
            sets.append(f"{k} = :{k}")
            params[k] = changes[k].strip() if isinstance(changes[k], str) else changes[k]
    if "attributes" in changes:
        # Merged: a key set to null is removed
        sets.append("attributes = jsonb_strip_nulls(attributes || CAST(:attrs AS jsonb))")
        params["attrs"] = json.dumps(changes["attributes"] or {})
    if not sets:
        raise _bad("Nothing to change")
    try:
        async with db.begin_nested():
            await db.execute(text(f"UPDATE {table} SET {', '.join(sets)}, updated_at = now() WHERE id = :id"), params)
    except Exception as exc:
        if "uq_" in str(exc):
            raise _bad(f"{changes.get('asset_code')} is already used", status.HTTP_409_CONFLICT) from None
        raise
    return {"label": f"Edit {row.asset_code}"}


async def _feed_link(db: AsyncSession, design: Design, tr: Tracker, src: Any, dst: Any, cable_id: uuid.UUID | None,
                     actor: Any) -> None:
    """Record src FEEDs dst (once), and give a FAT its chain's FDT."""
    exists = (await db.execute(text("""
        SELECT 1 FROM net_connections WHERE source_asset_id = :s AND dest_asset_id = :t AND deleted_at IS NULL
    """), {"s": src.id, "t": dst.id})).first()
    if not exists:
        kid = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO net_connections (id, tenant_id, design_id, source_asset_id, dest_asset_id, via_cable_id,
                                         connection_type, lifecycle_status, created_by)
            VALUES (:id, :tid, :d, :s, :t, :c, 'FEED', :life, :by)
        """), {"id": kid, "tid": design.tenant_id, "d": design.id, "s": src.id, "t": dst.id, "c": cable_id,
               "life": LIFECYCLE, "by": getattr(actor, "id", None)})
        tr.made("net_connections", kid)
    if dst.asset_type == "FAT" and dst.design_id is not None:
        head = src.asset_code if src.asset_type == "FDT" else (src.attributes or {}).get("parent_fdt_code")
        if head and (dst.attributes or {}).get("parent_fdt_code") != head:
            await tr.touch("net_assets", [dst.id])
            await db.execute(text("""
                UPDATE net_assets SET attributes = attributes || jsonb_build_object('parent_fdt_code', CAST(:h AS text))
                WHERE id = :id
            """), {"h": head, "id": dst.id})


async def _draw_cable(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    cat = str(p.get("cable_category") or "").upper()
    if cat not in CABLE_CATEGORIES:
        raise _bad(f"Unknown cable category '{cat}'")
    a_lng, a_lat, a = await _end(db, design, p.get("from"), "start")
    b_lng, b_lat, b = await _end(db, design, p.get("to"), "end")
    route = p.get("route") or ("straight" if cat == "DROP" else "road")
    if route == "road":
        coords, method = await _road_line(db, design, (a_lng, a_lat), (b_lng, b_lat)), "ROAD_GRAPH"
    elif route == "straight":
        coords, method = [[a_lng, a_lat], [b_lng, b_lat]], ("DIRECT" if cat == "DROP" else "MANUAL_GEOMETRY")
    else:
        raise _bad("route must be road or straight")
    coords = _dedupe(coords)
    code = (p.get("asset_code") or "").strip() or (await next_codes(db, design.tenant_id, "cable", cat))[0]
    fibres = p.get("fiber_count")
    if fibres is not None and (not isinstance(fibres, int) or fibres < 1):
        raise _bad("fiber_count must be 1 or more")
    cid = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO net_cables (id, tenant_id, design_id, project_id, asset_code, cable_category, name, geom, fiber_count,
                                installation_type, route_method, source_asset_id, dest_asset_id, lifecycle_status,
                                creation_method, attributes, created_by)
        VALUES (:id, :tid, :d, :p, :code, :cat, :name, ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), :fibres,
                :inst, :method, :src, :dst, :life, 'MANUAL', CAST(:attrs AS jsonb), :by)
    """), {"id": cid, "tid": design.tenant_id, "d": design.id, "p": design.project_id, "code": code, "cat": cat,
           "name": p.get("name") or None, "g": json.dumps({"type": "LineString", "coordinates": coords}),
           "fibres": fibres, "inst": p.get("installation_type") or "AERIAL", "method": method,
           "src": a.id if a else None, "dst": b.id if b else None, "life": LIFECYCLE,
           "attrs": json.dumps(p.get("attributes") or {}), "by": getattr(actor, "id", None)})
    tr.made("net_cables", cid)
    if cat in FEEDING_CABLES and a is not None and b is not None and a.id != b.id:
        await _feed_link(db, design, tr, a, b, cid, actor)
    length = (await db.execute(text("SELECT length_m::float8 FROM net_cables WHERE id = :id"), {"id": cid})).scalar_one()
    return {"label": f"Draw {code}", "cable_id": str(cid), "asset_code": code, "length_m": length, "route_method": method}


async def _delete_cable(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    c = await _cable(db, design, p.get("id"))
    links = list((await db.execute(text("SELECT id FROM net_connections WHERE via_cable_id = :id"), {"id": c.id})).scalars())
    await tr.touch("net_cables", [c.id])
    await tr.touch("net_connections", links)
    await db.execute(text("DELETE FROM net_cables WHERE id = :id"), {"id": c.id})
    return {"label": f"Delete {c.asset_code}"}


async def _edit_cable_geom(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    c = await _cable(db, design, p.get("id"))
    raw = p.get("coordinates")
    if not isinstance(raw, list):
        raise _bad("coordinates must be a list of [lng, lat]")
    coords = _dedupe([list(_point({"lng": x[0], "lat": x[1]})) for x in raw if isinstance(x, (list, tuple)) and len(x) >= 2])
    await tr.touch("net_cables", [c.id])
    method = "DIRECT" if c.cable_category == "DROP" and len(coords) == 2 else "MANUAL_GEOMETRY"
    await db.execute(text("""
        UPDATE net_cables SET geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), route_method = :m, updated_at = now()
        WHERE id = :id
    """), {"g": json.dumps({"type": "LineString", "coordinates": coords}), "m": method, "id": c.id})
    return {"label": f"Redraw {c.asset_code}"}


async def _split_cable(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    c = await _cable(db, design, p.get("id"))
    lng, lat = _point(p)
    f = (await db.execute(text("""
        SELECT ST_LineLocatePoint(geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)) FROM net_cables WHERE id = :id
    """), {"lng": lng, "lat": lat, "id": c.id})).scalar_one()
    if f <= 0.01 or f >= 0.99:
        raise _bad("Pick a point along the cable, not at its end")
    await tr.touch("net_cables", [c.id])
    new_asset = None
    if p.get("insert_asset_type"):
        cut = (await db.execute(text("""
            SELECT ST_X(ST_LineInterpolatePoint(geom, :f)), ST_Y(ST_LineInterpolatePoint(geom, :f)) FROM net_cables WHERE id = :id
        """), {"f": f, "id": c.id})).one()
        added = await _add_asset(db, design, tr, {"asset_type": p["insert_asset_type"], "lng": cut[0], "lat": cut[1]}, actor)
        new_asset = uuid.UUID(added["asset_id"])
    code = (await next_codes(db, design.tenant_id, "cable", c.cable_category))[0]
    bid = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO net_cables (id, tenant_id, design_id, project_id, asset_code, cable_category, geom, fiber_count,
                                installation_type, route_method, source_asset_id, dest_asset_id, lifecycle_status,
                                creation_method, attributes, created_by)
        SELECT :bid, tenant_id, design_id, project_id, :code, cable_category, ST_LineSubstring(geom, :f, 1), fiber_count,
               installation_type, route_method, :cut, dest_asset_id, lifecycle_status, 'MANUAL',
               attributes || jsonb_build_object('split_from', asset_code), :by
        FROM net_cables WHERE id = :id
    """), {"bid": bid, "code": code, "f": f, "cut": new_asset, "id": c.id, "by": getattr(actor, "id", None)})
    tr.made("net_cables", bid)
    await db.execute(text("UPDATE net_cables SET geom = ST_LineSubstring(geom, 0, :f), dest_asset_id = :cut, "
                          "updated_at = now() WHERE id = :id"), {"f": f, "cut": new_asset, "id": c.id})
    return {"label": f"Split {c.asset_code}", "cable_id": str(bid), "asset_code": code,
            "asset_id": str(new_asset) if new_asset else None}


async def _extend_cable(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    c = await _cable(db, design, p.get("id"))
    t_lng, t_lat, target = await _end(db, design, p.get("to"), "new end")
    coords = json.loads(c.g)["coordinates"]
    end = p.get("end")
    if end not in ("start", "end"):         # the end nearest the target
        d0 = (coords[0][0] - t_lng) ** 2 + (coords[0][1] - t_lat) ** 2
        d1 = (coords[-1][0] - t_lng) ** 2 + (coords[-1][1] - t_lat) ** 2
        end = "start" if d0 < d1 else "end"
    tip = coords[0] if end == "start" else coords[-1]
    if (p.get("route") or "road") == "road":
        seg = await _road_line(db, design, (tip[0], tip[1]), (t_lng, t_lat))
    else:
        seg = [tip, [t_lng, t_lat]]
    merged = _dedupe(list(reversed(seg)) + coords[1:] if end == "start" else coords[:-1] + seg)
    await tr.touch("net_cables", [c.id])
    ref = "source_asset_id" if end == "start" else "dest_asset_id"
    await db.execute(text(f"""
        UPDATE net_cables SET geom = ST_SetSRID(ST_GeomFromGeoJSON(:g), 4326), {ref} = :a, updated_at = now(),
               route_method = CASE WHEN :road THEN route_method ELSE 'MANUAL_GEOMETRY' END
        WHERE id = :id
    """), {"g": json.dumps({"type": "LineString", "coordinates": merged}), "a": target.id if target else None,
           "road": (p.get("route") or "road") == "road", "id": c.id})
    if target is not None and c.cable_category in FEEDING_CABLES:
        other = c.dest_asset_id if end == "start" else c.source_asset_id
        if other:
            o = await _asset(db, design, other, live_ok=True)
            src, dst = (target, o) if end == "start" else (o, target)
            await _feed_link(db, design, tr, src, dst, c.id, actor)
    return {"label": f"Extend {c.asset_code}"}


async def _connect(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    src = await _asset(db, design, p.get("source_id"), live_ok=True)
    dst = await _asset(db, design, p.get("dest_id"))
    if src.id == dst.id:
        raise _bad("An asset can't feed itself")
    ctype = p.get("connection_type") or "FEED"
    if ctype not in CONNECTION_TYPES:
        raise _bad(f"Unknown connection type '{ctype}'")
    if (await db.execute(text("SELECT 1 FROM net_connections WHERE source_asset_id = :s AND dest_asset_id = :t "
                              "AND deleted_at IS NULL"), {"s": src.id, "t": dst.id})).first():
        raise _bad(f"{src.asset_code} already connects to {dst.asset_code}", status.HTTP_409_CONFLICT)
    if ctype == "FEED":
        await _feed_link(db, design, tr, src, dst, None, actor)
    else:
        kid = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO net_connections (id, tenant_id, design_id, source_asset_id, dest_asset_id, connection_type,
                                         lifecycle_status, created_by)
            VALUES (:id, :tid, :d, :s, :t, :ct, :life, :by)
        """), {"id": kid, "tid": design.tenant_id, "d": design.id, "s": src.id, "t": dst.id, "ct": ctype,
               "life": LIFECYCLE, "by": getattr(actor, "id", None)})
        tr.made("net_connections", kid)
    return {"label": f"Connect {src.asset_code} → {dst.asset_code}"}


async def _disconnect(db: AsyncSession, design: Design, tr: Tracker, p: dict[str, Any], actor: Any) -> dict[str, Any]:
    if p.get("id"):
        kid = _uuid(p["id"], "The connection")
        row = (await db.execute(text("SELECT id FROM net_connections WHERE id = :id AND design_id = :d"),
                                {"id": kid, "d": design.id})).first()
    else:
        s, t = _uuid(p.get("source_id"), "The source"), _uuid(p.get("dest_id"), "The destination")
        row = (await db.execute(text("SELECT id FROM net_connections WHERE source_asset_id = :s AND dest_asset_id = :t "
                                     "AND design_id = :d"), {"s": s, "t": t, "d": design.id})).first()
    if row is None:
        raise _bad("No such connection in this design", status.HTTP_404_NOT_FOUND)
    await tr.touch("net_connections", [row.id])
    await db.execute(text("DELETE FROM net_connections WHERE id = :id"), {"id": row.id})
    return {"label": "Disconnect"}


OPS: dict[str, Callable[..., Any]] = {
    "ADD_ASSET": _add_asset, "MOVE_ASSET": _move_asset, "DELETE_ASSET": _delete_asset, "UPDATE_ATTRS": _update_attrs,
    "DRAW_CABLE": _draw_cable, "DELETE_CABLE": _delete_cable, "EDIT_CABLE_GEOM": _edit_cable_geom,
    "SPLIT_CABLE": _split_cable, "EXTEND_CABLE": _extend_cable, "CONNECT": _connect, "DISCONNECT": _disconnect,
}


# ── The log ──────────────────────────────────────────────────

async def _state(db: AsyncSession, design_id: uuid.UUID) -> dict[str, Any]:
    r = (await db.execute(text("""
        SELECT (SELECT payload->>'_label' FROM design_operations WHERE design_id = :d AND undone_at IS NULL
                ORDER BY seq DESC LIMIT 1) AS undo,
               (SELECT payload->>'_label' FROM design_operations WHERE design_id = :d AND undone_at IS NOT NULL
                ORDER BY seq ASC LIMIT 1) AS redo,
               (SELECT count(*) FROM design_operations WHERE design_id = :d AND undone_at IS NULL) AS done
    """), {"d": design_id})).one()
    return {"can_undo": r.undo is not None, "can_redo": r.redo is not None, "undo_label": r.undo, "redo_label": r.redo,
            "applied": int(r.done)}


async def _after(db: AsyncSession, tid: uuid.UUID, design: Design, before: dict[str, Any],
                 patch: dict[str, Any]) -> dict[str, Any]:
    """What the client needs after any change: undo state, summary, validation, and the deltas."""
    from app.modules.design.service import summary
    if design.status == "GENERATED":
        design.status = "MODIFIED"
    design.updated_at = datetime.datetime.now(datetime.timezone.utc)
    await db.flush()
    validation = await validation_service.validate(db, tid, design)
    after = await recalc.snapshot(db, tid, design.id)
    return {"history": await _state(db, design.id), "summary": await summary(db, tid, design),
            "validation": validation["summary"],
            "delta": {"boq": recalc.boq_delta(before["boq"], after["boq"]),
                      "issues": recalc.validation_delta(before["issues"], after["issues"]),
                      **await recalc.changed_features(db, tid, design, patch)}}


async def apply_operation(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design,
                          body: dict[str, Any]) -> dict[str, Any]:
    from app.modules.design.service import ensure_editable
    ensure_editable(design)
    op = str(body.get("op") or "").upper()
    fn = OPS.get(op)
    if fn is None:
        raise _bad(f"Unknown operation '{op}'. Known: {', '.join(sorted(OPS))}")
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"design-ops:{design.id}"})
    payload = {k: v for k, v in body.items() if k != "op"}
    before = await recalc.snapshot(db, tid, design.id)
    tr = Tracker(db)
    result = await fn(db, design, tr, payload, caller)
    forward, inverse = await tr.patches()
    # A new operation ends the redo branch
    await db.execute(text("DELETE FROM design_operations WHERE design_id = :d AND undone_at IS NOT NULL"), {"d": design.id})
    seq = (await db.execute(text("SELECT coalesce(max(seq), 0) + 1 FROM design_operations WHERE design_id = :d"),
                            {"d": design.id})).scalar_one()
    await db.execute(text("""
        INSERT INTO design_operations (tenant_id, design_id, seq, op, payload, inverse, created_by)
        VALUES (:tid, :d, :seq, :op, CAST(:payload AS jsonb), CAST(:inverse AS jsonb), :by)
    """), {"tid": tid, "d": design.id, "seq": seq, "op": op, "by": getattr(caller, "id", None),
           "payload": json.dumps({**payload, "_label": result["label"], "_result": result, "_forward": forward}, default=str),
           "inverse": json.dumps(inverse, default=str)})
    return {"operation": {"seq": seq, "op": op, **result}, **await _after(db, tid, design, before, forward)}


async def undo(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design) -> dict[str, Any]:
    from app.modules.design.service import ensure_editable
    ensure_editable(design)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"design-ops:{design.id}"})
    r = (await db.execute(text("""
        SELECT id, seq, op, inverse, payload->>'_label' AS label FROM design_operations
        WHERE design_id = :d AND undone_at IS NULL ORDER BY seq DESC LIMIT 1
    """), {"d": design.id})).first()
    if r is None:
        raise _bad("Nothing to undo", status.HTTP_409_CONFLICT)
    before = await recalc.snapshot(db, tid, design.id)
    await apply_patch(db, r.inverse)
    await db.execute(text("UPDATE design_operations SET undone_at = now() WHERE id = :id"), {"id": r.id})
    return {"operation": {"seq": r.seq, "op": r.op, "label": f"Undid: {r.label}"},
            **await _after(db, tid, design, before, r.inverse)}


async def redo(db: AsyncSession, tid: uuid.UUID, caller: Any, design: Design) -> dict[str, Any]:
    from app.modules.design.service import ensure_editable
    ensure_editable(design)
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"design-ops:{design.id}"})
    r = (await db.execute(text("""
        SELECT id, seq, op, payload->'_forward' AS fwd, payload->>'_label' AS label FROM design_operations
        WHERE design_id = :d AND undone_at IS NOT NULL ORDER BY seq ASC LIMIT 1
    """), {"d": design.id})).first()
    if r is None:
        raise _bad("Nothing to redo", status.HTTP_409_CONFLICT)
    before = await recalc.snapshot(db, tid, design.id)
    await apply_patch(db, r.fwd)
    await db.execute(text("UPDATE design_operations SET undone_at = NULL WHERE id = :id"), {"id": r.id})
    return {"operation": {"seq": r.seq, "op": r.op, "label": f"Redid: {r.label}"},
            **await _after(db, tid, design, before, r.fwd)}


async def history(db: AsyncSession, tid: uuid.UUID, design: Design, limit: int = 50) -> dict[str, Any]:
    rows = (await db.execute(text("""
        SELECT seq, op, payload->>'_label' AS label, created_at, undone_at FROM design_operations
        WHERE design_id = :d AND tenant_id = :tid ORDER BY seq DESC LIMIT :n
    """), {"d": design.id, "tid": tid, "n": limit})).all()
    return {**await _state(db, design.id), "operations": [
        {"seq": r.seq, "op": r.op, "label": r.label, "created_at": r.created_at.isoformat(), "undone": r.undone_at is not None}
        for r in rows]}


async def clear_log(db: AsyncSession, design_id: uuid.UUID) -> None:
    """A new version replaced the working set: old operations no longer apply."""
    await db.execute(text("DELETE FROM design_operations WHERE design_id = :d"), {"d": design_id})
