"""HTTP 路由层（职责六）：只做报文解析、参数来源解析与结果封装。

求解器、积水分段、持久化等逻辑都不在这里。
"""
from __future__ import annotations

from typing import Any

from flask import Blueprint, current_app, jsonify, request

from app.errors import ServiceError, ValidationError
from app.services.hydrograph import HydrographSpec
from app.services.parameters import SoilParameters, make_params
from app.services.ponding import infiltration_at, ponding_time

api = Blueprint("api", __name__)


# ---------- 请求解析辅助 ----------
def _json_body() -> dict[str, Any]:
    if not request.is_json:
        raise ValidationError("请求体必须是 application/json")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    return body


def _resolve_soil(body: dict[str, Any]) -> SoilParameters:
    """土壤参数来源：先看建档名 profile，再看现场给的 ks/psi/dtheta。"""
    store = current_app.extensions["profile_store"]
    if "profile" in body and body["profile"] is not None:
        return store.get(body["profile"])
    try:
        return make_params(body.get("ks"), body.get("psi"), body.get("dtheta"))
    except KeyError:
        raise ValidationError(
            "需提供建档名 profile，或同时提供 ks、psi、dtheta 三个土壤参数"
        )


def _as_bool(value: Any, name: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValidationError(f"参数 {name} 必须是布尔值 true/false")
    return value


def _float_or_none(body: dict, name: str):
    value = body.get(name)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"参数 {name} 必须是数值")
    fv = float(value)
    if fv != fv or fv in (float("inf"), float("-inf")):
        raise ValidationError(f"参数 {name} 必须是有限实数")
    return fv


# ---------- 健康检查 ----------
@api.get("/health")
def health():
    return jsonify({"status": "ok", "service": "green-ampt-infiltration"})


# ---------- 核心一：给定时刻的入渗核算 ----------
@api.post("/api/infiltration")
def infiltration():
    body = _json_body()
    params = _resolve_soil(body)
    t = body.get("t")
    if t is None:
        raise ValidationError("必须提供历时 t（t ≥ 0）")
    if isinstance(t, bool) or not isinstance(t, (int, float)):
        raise ValidationError("历时 t 必须是非负数值")
    rainfall_rate = _float_or_none(body, "rainfall_rate")
    already_ponded = _as_bool(body.get("already_ponded"), "already_ponded", True)
    result = infiltration_at(
        params,
        float(t),
        rainfall_rate=rainfall_rate,
        already_ponded=already_ponded,
    )
    return jsonify(result)


# ---------- 核心二：积水时刻判定 ----------
@api.post("/api/ponding")
def ponding():
    body = _json_body()
    params = _resolve_soil(body)
    if body.get("rainfall_rate") is None and body.get("i") is None:
        raise ValidationError("必须提供降雨强度 rainfall_rate（或 i）")
    i = body.get("rainfall_rate", body.get("i"))
    if isinstance(i, bool) or not isinstance(i, (int, float)):
        raise ValidationError("降雨强度必须是数值")
    result = ponding_time(params, float(i))
    result["soil"] = params.to_dict()
    return jsonify(result)


# ---------- 工况建档 ----------
@api.get("/api/profiles")
def list_profiles():
    return jsonify({"profiles": current_app.extensions["profile_store"].list()})


@api.post("/api/profiles")
def create_profile():
    body = _json_body()
    name = body.get("name")
    if not name:
        raise ValidationError("必须提供工况名 name")
    overwrite = _as_bool(body.get("overwrite"), "overwrite", False)
    params = current_app.extensions["profile_store"].create(
        name,
        body.get("ks"),
        body.get("psi"),
        body.get("dtheta"),
        description=body.get("description"),
        overwrite=overwrite,
    )
    profile = {
        "name": params.name,
        "ks": params.ks,
        "psi": params.psi,
        "dtheta": params.dtheta,
        "suction_storage": params.suction_storage,
    }
    return jsonify({"saved": True, "profile": profile}), 201


@api.get("/api/profiles/<string:name>")
def get_profile(name: str):
    meta = current_app.extensions["profile_store"].get_meta(name)
    params = current_app.extensions["profile_store"].get(name)
    return jsonify({"profile": {**meta, "suction_storage": params.suction_storage}})


@api.delete("/api/profiles/<string:name>")
def delete_profile(name: str):
    current_app.extensions["profile_store"].delete(name)
    return jsonify({"deleted": True, "name": name})


# ---------- 长历时点列（可取消作业） ----------
@api.post("/api/hydrographs")
def submit_hydrograph():
    body = _json_body()
    params = _resolve_soil(body)
    t_end = body.get("t_end")
    if t_end is None:
        raise ValidationError("必须提供历时上限 t_end")
    n_points = body.get("n_points", 101)
    spec = HydrographSpec(
        params=params,
        t_end=float(t_end) if isinstance(t_end, (int, float)) and not isinstance(t_end, bool) else t_end,
        n_points=n_points,
        rainfall_rate=_float_or_none(body, "rainfall_rate"),
        already_ponded=_as_bool(body.get("already_ponded"), "already_ponded", True),
    )
    job = current_app.extensions["job_manager"].submit(spec)
    return jsonify(job.public_view()), 202


@api.get("/api/hydrographs/<string:job_id>")
def get_hydrograph(job_id: str):
    job = current_app.extensions["job_manager"].get(job_id)
    return jsonify(job.public_view())


@api.post("/api/hydrographs/<string:job_id>/cancel")
def cancel_hydrograph(job_id: str):
    job = current_app.extensions["job_manager"].cancel(job_id)
    return jsonify(job.public_view())
