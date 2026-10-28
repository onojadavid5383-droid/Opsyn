# ============================================================
# OPSYN DESIGN ↔ ENGINE BRIDGE — app/modules/design/engine_bridge.py
#
# Everything the shared design services need from the FTTx engine
# (fttx_designer/engine, used unchanged):
#   - the design's inputs as the engine's projected layers
#     (geojson_io.build_input_layers → one UTM zone chosen from the roads)
#   - coordinate transforms WGS84 ↔ that UTM zone
#   - the engine's CableRouter over the design's roads (true Dijkstra on
#     the noded road graph, with device stubs)
#   - nearest-road lookup, for hydrating devices and homepasses
#   - the design's FTTXConfig (engine_config overrides on the defaults)
#
# A context is built once per (design, inputs revision) and cached, so a
# series of routing calls pays for the road graph once. It is rebuilt as
# soon as any input changes.
#
# The engine keeps a few per-run tunables in module globals
# (runtime_config); ENGINE_LOCK serialises every call that sets them.
# ============================================================

from __future__ import annotations

import json
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import pyproj
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.fttx_designer.config_io import config_from_dict
from app.modules.fttx_designer.engine.config import FTTXConfig
from app.modules.fttx_designer.engine.geometry_compat import (
    QgsCoordinateReferenceSystem, QgsPointXY, QgsSpatialIndex, QgsVectorLayer,
)
from app.modules.fttx_designer.geojson_io import build_input_layers

ENGINE_LOCK = threading.Lock()
_CACHE_SIZE = 8
_cache: "OrderedDict[tuple[str, str], EngineContext]" = OrderedDict()
_cache_lock = threading.Lock()

# The customer count every homepass input carries (design/inputs.py)
HOMEPASS_COUNT_FIELD = "customers"


class MissingInputs(Exception):
    """The design lacks an input layer a service needs (e.g. roads to route on)."""


@dataclass
class EngineContext:
    layers: dict[str, QgsVectorLayer]
    crs: QgsCoordinateReferenceSystem
    config: FTTXConfig
    _fwd: pyproj.Transformer
    _back: pyproj.Transformer
    _road_index: QgsSpatialIndex
    _router: Any = None

    def to_utm(self, lng: float, lat: float) -> QgsPointXY:
        x, y = self._fwd.transform(lng, lat)
        return QgsPointXY(x, y)

    def to_wgs(self, x: float, y: float) -> tuple[float, float]:
        lng, lat = self._back.transform(x, y)
        return round(lng, 7), round(lat, 7)

    def nearest_road_id(self, pt: QgsPointXY) -> int | None:
        hits = self._road_index.nearestNeighbor(pt, 1)
        return hits[0] if hits else None

    @property
    def router(self):
        """The engine's CableRouter over this design's roads (built on first use)."""
        if self._router is None:
            from app.modules.fttx_designer.engine.cable_routing import CableRouter
            from app.modules.fttx_designer.engine.spatial_utils import DistanceCalculator
            self._router = CableRouter(self.layers["road"], DistanceCalculator(self.crs))
        return self._router


async def inputs_revision(db: AsyncSession, design_id: uuid.UUID) -> str:
    """Changes whenever any input of the design is added, replaced or removed."""
    row = (await db.execute(text("""
        SELECT count(*)::text || ':' || coalesce(max(created_at)::text, '')
               || ':' || coalesce((SELECT max(uploaded_at)::text FROM design_input_uploads WHERE design_id = :d), '')
        FROM design_inputs WHERE design_id = :d
    """), {"d": design_id})).scalar_one()
    return row


async def load_inputs(db: AsyncSession, tid: uuid.UUID, design_id: uuid.UUID,
                      layer_keys: tuple[str, ...] | None = None) -> dict[str, dict[str, Any]]:
    """The design's inputs as WGS84 FeatureCollections, one per layer that has features."""
    params: dict[str, Any] = {"d": design_id, "tid": tid}
    where = ""
    if layer_keys:
        where = "AND layer_key = ANY(:keys)"
        params["keys"] = list(layer_keys)
    rows = (await db.execute(text(f"""
        SELECT layer_key, ST_AsGeoJSON(geom, 7) AS g, properties
        FROM design_inputs WHERE design_id = :d AND tenant_id = :tid {where}
        ORDER BY layer_key, created_at, id
    """), params)).all()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        fc = out.setdefault(r.layer_key, {"type": "FeatureCollection", "features": []})
        fc["features"].append({"type": "Feature", "geometry": json.loads(r.g), "properties": r.properties or {}})
    return out


def _explode_multilines(fc: dict[str, Any]) -> dict[str, Any]:
    """The engine's road layer expects single LineStrings."""
    feats = []
    for f in fc["features"]:
        g = f["geometry"]
        if g["type"] == "MultiLineString":
            feats.extend({"type": "Feature", "properties": f["properties"],
                          "geometry": {"type": "LineString", "coordinates": part}} for part in g["coordinates"])
        else:
            feats.append(f)
    return {"type": "FeatureCollection", "features": feats}


def build_context(inputs: dict[str, dict[str, Any]], engine_config: dict[str, Any]) -> EngineContext:
    if "road" not in inputs or not inputs["road"]["features"]:
        raise MissingInputs("Upload the design's roads first: routing, BOQ streets and road assignment need them.")
    usable = {k: v for k, v in inputs.items() if k in ("road", "homepass", "pole", "pickup", "building")}
    usable["road"] = _explode_multilines(usable["road"])
    layers, crs = build_input_layers(usable)
    road_index = QgsSpatialIndex()
    for feat in layers["road"].getFeatures():
        road_index.addFeature(feat)
    config = config_from_dict({"homepass_field_name": HOMEPASS_COUNT_FIELD, **(engine_config or {})})
    return EngineContext(
        layers=layers, crs=crs, config=config,
        _fwd=pyproj.Transformer.from_crs(4326, crs.authid(), always_xy=True),
        _back=pyproj.Transformer.from_crs(crs.authid(), 4326, always_xy=True),
        _road_index=road_index,
    )


async def context_for(db: AsyncSession, tid: uuid.UUID, design: Any) -> EngineContext:
    """Cached per (design, inputs revision)."""
    rev = await inputs_revision(db, design.id)
    key = (str(design.id), rev + json.dumps(design.engine_config or {}, sort_keys=True))
    with _cache_lock:
        ctx = _cache.get(key)
        if ctx is not None:
            _cache.move_to_end(key)
            return ctx
    inputs = await load_inputs(db, tid, design.id)
    from fastapi.concurrency import run_in_threadpool
    ctx = await run_in_threadpool(build_context, inputs, design.engine_config or {})
    with _cache_lock:
        _cache[key] = ctx
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return ctx
