"""HTTP 路由的端到端测试。"""
from __future__ import annotations

import time

import pytest


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_infiltration_direct_params(client):
    r = client.post("/api/infiltration", json={
        "ks": 1.04, "psi": 6.0, "dtheta": 0.434, "t": 1.0,
        "already_ponded": True,
    })
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["F"] > 1.04  # 吸力项作用
    assert body["f"] > 1.04
    assert abs(body["residual"]) <= 1e-10
    assert body["residual_within_tol"] is True
    assert body["phase"] == "ponded"


def test_infiltration_zero_time_capped(client):
    r = client.post("/api/infiltration", json={
        "ks": 1.0, "psi": 5.0, "dtheta": 0.4, "t": 0.0,
    })
    body = r.get_json()
    assert body["F"] == 0.0
    assert body["rate_capped"] is True
    assert body["f"] != float("inf")


def test_infiltration_validation_error_structure(client):
    r = client.post("/api/infiltration", json={
        "ks": -1, "psi": 0, "dtheta": 2, "t": -3,
    })
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "validation_error"
    assert body["message"]
    assert len(body["details"]) >= 3


def test_infiltration_rainfall_piecewise(client):
    r = client.post("/api/infiltration", json={
        "ks": 1.04, "psi": 6.0, "dtheta": 0.434, "t": 5.0,
        "rainfall_rate": 3.0, "already_ponded": False,
    })
    body = r.get_json()
    assert body["will_pond"] is True
    assert body["tp"] > 0
    assert body["phase"] in ("free", "ponded")


# ---- 回归：带降雨强度、不声明 already_ponded 时必须按降雨分段 ----
# 曾经的缺陷：路由层把 already_ponded 缺省成 True，降雨强度被静默丢弃，
# 一律按「从零积水」解。以下用例钉住「不声明开关」与「显式不积水」
# 两条路结果完全一致。

SOIL = {"ks": 1.04, "psi": 6.0, "dtheta": 0.434}


def _infiltration(client, **payload):
    r = client.post("/api/infiltration", json=payload)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


def test_light_rain_without_flag_never_ponds(client):
    # 小雨 i < Ks：物理上永不积水，F = i·t，入渗率即降雨强度
    i, t = 0.5, 5.0
    body = _infiltration(client, **SOIL, t=t, rainfall_rate=i)
    assert body["ponded"] is False
    assert body["will_pond"] is False
    assert body["phase"] == "free"
    assert body["tp"] is None
    assert body["F"] == pytest.approx(i * t)
    assert body["f"] == pytest.approx(i)

    # 与显式 already_ponded=false 的应答逐项一致
    explicit = _infiltration(
        client, **SOIL, t=t, rainfall_rate=i, already_ponded=False
    )
    assert body == explicit


def test_heavy_rain_without_flag_free_then_ponded(client):
    # 大雨 i > Ks：tp 前自由段 F = i·t，tp 后积水段，且与显式不积水一致
    i = 3.0
    tp = client.post(
        "/api/ponding", json={**SOIL, "rainfall_rate": i}
    ).get_json()["tp"]
    assert tp > 0

    early = _infiltration(client, **SOIL, t=0.5 * tp, rainfall_rate=i)
    assert early["phase"] == "free"
    assert early["ponded"] is False
    assert early["F"] == pytest.approx(i * 0.5 * tp)
    assert early["f"] == pytest.approx(i)
    assert early["tp"] == pytest.approx(tp)

    late = _infiltration(client, **SOIL, t=tp + 5.0, rainfall_rate=i)
    assert late["phase"] == "ponded"
    assert late["ponded"] is True
    assert late["residual_within_tol"] is True
    # 积水段累积入渗必大于同段自由外推 i·t 的 Ks 部分（吸力项作用），
    # 且与显式不积水的应答逐项一致
    for t in (0.5 * tp, tp, tp + 5.0):
        auto = _infiltration(client, **SOIL, t=t, rainfall_rate=i)
        explicit = _infiltration(
            client, **SOIL, t=t, rainfall_rate=i, already_ponded=False
        )
        assert auto == explicit


def test_explicit_ponded_true_still_ignores_rainfall(client):
    # 显式声明已积水：即使带了降雨强度，也从零走积水隐式式
    body = _infiltration(
        client, **SOIL, t=1.0, rainfall_rate=3.0, already_ponded=True
    )
    assert body["phase"] == "ponded"
    assert body["ponded"] is True
    assert "tp" not in body
    assert body["F"] > SOIL["ks"] * 1.0  # 吸力项作用


def test_no_rainfall_no_flag_defaults_to_ponded(client):
    # 既不给降雨强度也不声明开关：维持原缺省，按已积水处理
    body = _infiltration(client, **SOIL, t=1.0)
    assert body["phase"] == "ponded"
    assert body["ponded"] is True
    assert body["F"] > SOIL["ks"] * 1.0


def test_hydrograph_rainfall_without_flag_segments(client):
    # 点列作业同样：带降雨、不声明开关时必须分自由/积水两段
    r = client.post("/api/hydrographs", json={
        **SOIL, "t_end": 5.0, "n_points": 200, "rainfall_rate": 3.0,
    })
    assert r.status_code == 202
    job_id = r.get_json()["job_id"]

    deadline = time.time() + 10
    while time.time() < deadline:
        body = client.get(f"/api/hydrographs/{job_id}").get_json()
        if body["status"] == "completed":
            break
        time.sleep(0.02)
    assert body["status"] == "completed"

    phases = [p["phase"] for p in body["points"]]
    assert phases[0] == "free"
    assert phases[-1] == "ponded"
    transitions = sum(1 for a, b in zip(phases, phases[1:]) if a != b)
    assert transitions == 1


def test_ponding_endpoint_no_pond(client):
    r = client.post("/api/ponding", json={
        "ks": 1.04, "psi": 6.0, "dtheta": 0.434, "rainfall_rate": 0.5,
    })
    body = r.get_json()
    assert r.status_code == 200
    assert body["will_pond"] is False
    assert body["tp"] is None
    assert "不会积水" in body["reason"]


def test_ponding_endpoint_will_pond(client):
    r = client.post("/api/ponding", json={
        "ks": 1.04, "psi": 6.0, "dtheta": 0.434, "i": 3.0,
    })
    body = r.get_json()
    assert body["will_pond"] is True
    assert body["tp"] > 0


def test_ponding_missing_rate(client):
    r = client.post("/api/ponding", json={
        "ks": 1.0, "psi": 5.0, "dtheta": 0.4,
    })
    assert r.status_code == 400
    assert r.get_json()["error"] == "validation_error"


def test_seed_profile_infiltration(client):
    r = client.get("/api/profiles")
    names = [p["name"] for p in r.get_json()["profiles"]]
    assert "loam" in names

    r = client.post("/api/infiltration", json={"profile": "loam", "t": 1.0})
    body = r.get_json()
    assert r.status_code == 200
    assert body["F"] > 1.5 * 1.04


def test_profile_crud(client):
    r = client.post("/api/profiles", json={
        "name": "field_a", "ks": 2.0, "psi": 9.0, "dtheta": 0.4,
    })
    assert r.status_code == 201

    r = client.get("/api/profiles/field_a")
    assert r.get_json()["profile"]["ks"] == 2.0

    r = client.post("/api/infiltration", json={"profile": "field_a", "t": 2.0})
    assert r.status_code == 200

    r = client.delete("/api/profiles/field_a")
    assert r.status_code == 200

    r = client.post("/api/infiltration", json={"profile": "field_a", "t": 2.0})
    assert r.status_code == 404


def test_unknown_profile_404(client):
    r = client.post("/api/infiltration", json={"profile": "ghost", "t": 1})
    assert r.status_code == 404
    assert r.get_json()["error"] == "not_found"


def test_non_json_body_rejected(client):
    r = client.post("/api/infiltration", data="ks=1")
    assert r.status_code == 400


def test_hydrograph_lifecycle_and_cancel(client):
    # 正常小作业
    r = client.post("/api/hydrographs", json={
        "ks": 1.04, "psi": 6.0, "dtheta": 0.434,
        "t_end": 5.0, "n_points": 50,
    })
    assert r.status_code == 202
    job_id = r.get_json()["job_id"]

    deadline = time.time() + 10
    while time.time() < deadline:
        body = client.get(f"/api/hydrographs/{job_id}").get_json()
        if body["status"] == "completed":
            break
        time.sleep(0.02)
    assert body["status"] == "completed"
    assert len(body["points"]) == 50

    # 大作业提交后立刻取消
    r = client.post("/api/hydrographs", json={
        "profile": "loam", "t_end": 100.0, "n_points": 300000,
    })
    big_id = r.get_json()["job_id"]
    r = client.post(f"/api/hydrographs/{big_id}/cancel")
    assert r.status_code == 200
    body = client.get(f"/api/hydrographs/{big_id}").get_json()
    assert body["status"] in ("cancelled", "queued", "running")
    assert "points" not in body


def test_hydrograph_validation(client):
    r = client.post("/api/hydrographs", json={
        "ks": 1.0, "psi": 5.0, "dtheta": 0.4,
        "t_end": -1, "n_points": 10,
    })
    assert r.status_code == 400
