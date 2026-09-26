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


def test_light_rain_implicit_matches_explicit_not_ponded(client):
    # 回归：小雨（i < Ks）只给降雨强度、不声明积水时，必须与显式
    # already_ponded=false 完全一致——永不积水，F = i*t。
    # 修复前缺省开关恒为 True，降雨被无视、直接走积水隐式式。
    payload = {"ks": 1.04, "psi": 6.0, "dtheta": 0.434,
               "t": 5.0, "rainfall_rate": 0.5}
    implicit = client.post("/api/infiltration", json=payload).get_json()
    explicit = client.post(
        "/api/infiltration", json={**payload, "already_ponded": False}
    ).get_json()

    for body in (implicit, explicit):
        assert body["ponded"] is False
        assert body["will_pond"] is False
        assert body["tp"] is None
        assert body["phase"] == "free"
        assert body["F"] == pytest.approx(0.5 * 5.0)
        assert body["f"] == pytest.approx(0.5)

    assert implicit == explicit


def test_heavy_rain_free_phase_implicit_matches_explicit(client):
    # 回归：大雨早时刻（t < tp）只给降雨强度时，仍应在自由段，
    # F = i*t，且与显式 already_ponded=false 的结果逐项一致。
    ks, psi, dtheta = 1.04, 6.0, 0.434
    i = 3.0
    lam = psi * dtheta
    tp = ks * lam / (i * (i - ks))  # Mein–Larson 积水时刻
    t = 0.25 * tp
    payload = {"ks": ks, "psi": psi, "dtheta": dtheta,
               "t": t, "rainfall_rate": i}
    implicit = client.post("/api/infiltration", json=payload).get_json()
    explicit = client.post(
        "/api/infiltration", json={**payload, "already_ponded": False}
    ).get_json()

    for body in (implicit, explicit):
        assert body["will_pond"] is True
        assert body["ponded"] is False
        assert body["phase"] == "free"
        assert body["tp"] == pytest.approx(tp)
        assert body["F"] == pytest.approx(i * t)
        assert body["f"] == pytest.approx(i)

    assert implicit == explicit


def test_heavy_rain_transition_implicit_matches_explicit(client):
    # 回归：同一场大雨跨积水时刻取多个点，隐式缺省与显式 false
    # 在自由段、积水段以及 tp 邻域都必须给出逐点一致的分段结果。
    ks, psi, dtheta = 1.04, 6.0, 0.434
    i = 3.0
    lam = psi * dtheta
    tp = ks * lam / (i * (i - ks))
    for t in (0.0, 0.5 * tp, tp, tp + 1e-9, tp + 1.0, 5.0):
        payload = {"ks": ks, "psi": psi, "dtheta": dtheta,
                   "t": t, "rainfall_rate": i}
        implicit = client.post("/api/infiltration", json=payload).get_json()
        explicit = client.post(
            "/api/infiltration", json={**payload, "already_ponded": False}
        ).get_json()
        assert implicit == explicit
        if t < tp:
            assert implicit["phase"] == "free"
            assert implicit["F"] == pytest.approx(i * t)
        else:
            assert implicit["phase"] == "ponded"
            assert abs(implicit["residual"]) <= implicit["residual_tol"]


def test_implicit_rainfall_phase_switches_once_around_tp(client):
    # tp 前一刻还是自由段、tp 这一刻起转入积水段，且转段前后 F 连得上。
    ks, psi, dtheta = 1.04, 6.0, 0.434
    i = 3.0
    lam = psi * dtheta
    tp = ks * lam / (i * (i - ks))
    base = {"ks": ks, "psi": psi, "dtheta": dtheta, "rainfall_rate": i}

    before = client.post(
        "/api/infiltration", json={**base, "t": tp * (1 - 1e-9)}
    ).get_json()
    at = client.post(
        "/api/infiltration", json={**base, "t": tp}
    ).get_json()
    assert before["phase"] == "free"
    assert at["phase"] == "ponded"
    assert at["F"] == pytest.approx(before["F"], rel=1e-6)


def test_explicit_already_ponded_still_ponded_with_rainfall(client):
    # 显式声明已积水时，即便带着降雨强度，仍从零走积水隐式式。
    r = client.post("/api/infiltration", json={
        "ks": 1.04, "psi": 6.0, "dtheta": 0.434, "t": 1.0,
        "rainfall_rate": 0.5, "already_ponded": True,
    })
    body = r.get_json()
    assert body["phase"] == "ponded"
    assert body["ponded"] is True
    assert body["F"] > 1.04


def test_no_rainfall_no_flag_keeps_ponded_default(client):
    # 既不给降雨强度、也不声明积水：维持原来按已积水处理的缺省行为。
    r = client.post("/api/infiltration", json={
        "ks": 1.04, "psi": 6.0, "dtheta": 0.434, "t": 1.0,
    })
    body = r.get_json()
    assert body["phase"] == "ponded"
    assert body["ponded"] is True


def test_rainfall_implicit_still_rejects_invalid_inputs(client):
    # 走降雨分段这条路时，违约输入仍在开算前被挡下并回带原因。
    r = client.post("/api/infiltration", json={
        "ks": -1, "psi": 0, "dtheta": 2, "t": -3, "rainfall_rate": 0.5,
    })
    assert r.status_code == 400
    body = r.get_json()
    assert body["error"] == "validation_error"
    assert len(body["details"]) >= 3


def test_hydrograph_rainfall_implicit_is_piecewise(client):
    # 回归：点列作业只给降雨强度时同样必须分自由/积水两段，
    # 不能整条按已积水处理（修复前路由缺省 True）。
    r = client.post("/api/hydrographs", json={
        "ks": 1.04, "psi": 6.0, "dtheta": 0.434,
        "t_end": 5.0, "n_points": 200, "rainfall_rate": 3.0,
    })
    assert r.status_code == 202
    job_id = r.get_json()["job_id"]
    assert r.get_json()["already_ponded"] is False

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
    assert sum(1 for a, b in zip(phases, phases[1:]) if a != b) == 1


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
