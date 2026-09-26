"""多份土壤方案同时算时的隔离测试。

要求：每份方案的入渗推进和积水判定都关在自己的账下，
一份方案迭代过程中的临时量不能跑到别的方案头上去。
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.hydrograph import HydrographSpec, JobManager
from app.services.parameters import make_params
from app.services.ponding import infiltration_at
from app.services.solver import solve_f


SOILS = [
    make_params(0.3, 25.0, 0.45),   # 黏土感
    make_params(1.04, 6.0, 0.434), # 壤土
    make_params(5.0, 2.0, 0.30),    # 砂土感
    make_params(2.0, 12.0, 0.38),
]


def _expected(params, t):
    return solve_f(params.ks * t, params.suction_storage)


def test_concurrent_infiltration_queries_are_independent():
    errors: list[BaseException] = []
    results = {}
    lock = threading.Lock()

    def worker(soil_idx, t):
        try:
            p = SOILS[soil_idx]
            out = infiltration_at(p, t, already_ponded=True)
            exp = _expected(p, t)
            assert abs(out["F"] - exp) <= 1e-8
            assert out["soil"]["ks"] == p.ks  # 没串档
            with lock:
                results[(soil_idx, t)] = out["F"]
        except BaseException as exc:  # noqa: BLE001
            with lock:
                errors.append(exc)

    tasks = [(i, 0.1 * (j + 1)) for i in range(len(SOILS)) for j in range(20)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda args: worker(*args), tasks))

    assert not errors
    assert len(results) == len(tasks)
    # 不同土壤同刻结果各不相同（参数确有差异）：高 Ks 砂土在 t=1 的 F 远大于黏土
    assert results[(2, 1.0)] > results[(0, 1.0)]


def test_concurrent_hydrograph_jobs_are_isolated(loam, sandy):
    mgr = JobManager(max_workers=4)
    try:
        specs = [
            HydrographSpec(loam, t_end=5.0, n_points=300),
            HydrographSpec(sandy, t_end=5.0, n_points=300),
            HydrographSpec(loam, t_end=2.0, n_points=100, rainfall_rate=3.0,
                           already_ponded=False),
        ]
        jobs = [mgr.submit(s) for s in specs]
        for job in jobs:
            assert job.wait(timeout=15)
        views = [j.public_view() for j in jobs]
        assert all(v["status"] == "completed" for v in views)
        assert [len(v["points"]) for v in views] == [300, 300, 100]
        # 土壤快照没有串
        assert views[0]["soil"]["ks"] == loam.ks
        assert views[1]["soil"]["ks"] == sandy.ks
        # 各自终值只跟自己的参数账对得上
        assert abs(views[0]["points"][-1]["F"]
                   - solve_f(loam.ks * 5.0, loam.suction_storage)) < 1e-7
        assert abs(views[1]["points"][-1]["F"]
                   - solve_f(sandy.ks * 5.0, sandy.suction_storage)) < 1e-7
        # 第三个作业有自由段
        assert views[2]["points"][0]["phase"] == "free"
    finally:
        mgr.shutdown()
