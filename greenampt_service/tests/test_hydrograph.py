"""长历时分段点列与可取消作业测试。"""
from __future__ import annotations

import time

import pytest

from app.errors import JobError, ValidationError
from app.services.hydrograph import (
    HydrographSpec,
    JobCancelled,
    JobManager,
    generate_points,
)


def _spec(params, t_end=10.0, n=101, **kw):
    return HydrographSpec(
        params=params, t_end=t_end, n_points=n, **kw
    )


def test_points_cover_grid_and_monotone(loam):
    pts = generate_points(_spec(loam))
    assert len(pts) == 101
    assert pts[0]["t"] == 0.0
    assert pts[-1]["t"] == pytest.approx(10.0)
    Fs = [p["F"] for p in pts]
    fs = [p["f"] for p in pts]
    assert all(b >= a for a, b in zip(Fs, Fs[1:]))
    assert all(b <= a for a, b in zip(fs, fs[1:]))
    assert all(p["residual_within_tol"] for p in pts)


def test_phases_marked_under_rainfall(loam):
    spec = _spec(loam, t_end=5.0, n=200, rainfall_rate=3.0, already_ponded=False)
    pts = generate_points(spec)
    phases = [p["phase"] for p in pts]
    assert phases[0] == "free"
    assert phases[-1] == "ponded"
    # 只允许一次自由→积水的切换
    transitions = sum(
        1 for a, b in zip(phases, phases[1:]) if a != b
    )
    assert transitions == 1


def test_cancelled_generation_returns_nothing(loam):
    # 推进前就置取消：必须抛 JobCancelled，点列一个都不交
    with pytest.raises(JobCancelled):
        generate_points(
            _spec(loam, n=10), is_cancelled=lambda: True
        )


def test_job_completes_and_delivers_points(loam):
    mgr = JobManager(max_workers=2)
    try:
        job = mgr.submit(_spec(loam, n=50))
        assert job.wait(timeout=10)
        view = job.public_view()
        assert view["status"] == "completed"
        assert len(view["points"]) == 50
    finally:
        mgr.shutdown()


def test_cancelled_job_never_exposes_partial_points(loam):
    # 大点数作业，提交后立即取消；终态只能是 cancelled（或来不及跑时仍可拦在完成前）
    mgr = JobManager(max_workers=1)
    try:
        job = mgr.submit(_spec(loam, t_end=100.0, n=300_000))
        job.cancel()
        job.wait(timeout=10)
        view = job.public_view()
        assert view["status"] in ("cancelled", "queued", "running")
        assert "points" not in view
        assert view["status"] != "completed"
    finally:
        mgr.shutdown()


def test_cancel_completed_job_rejected(loam):
    mgr = JobManager(max_workers=2)
    try:
        job = mgr.submit(_spec(loam, n=5))
        job.wait(timeout=10)
        with pytest.raises(JobError):
            mgr.cancel(job.id)
    finally:
        mgr.shutdown()


def test_unknown_job(loam):
    mgr = JobManager()
    try:
        with pytest.raises(JobError):
            mgr.get("nope")
    finally:
        mgr.shutdown()


def test_spec_validation(loam):
    with pytest.raises(ValidationError):
        HydrographSpec(loam, t_end=-1, n_points=10)
    with pytest.raises(ValidationError):
        HydrographSpec(loam, t_end=1, n_points=1)
    with pytest.raises(ValidationError):
        HydrographSpec(loam, t_end=1, n_points=True)
