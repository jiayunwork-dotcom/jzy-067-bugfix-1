"""HTTP 路由的端到端测试。"""
from __future__ import annotations

import time


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
