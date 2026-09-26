"""入渗率、积水入渗与参数趋势的因果关系测试。"""
from __future__ import annotations

import pytest

from app.config import F_FLOOR, RESIDUAL_TOL
from app.errors import ValidationError
from app.services.infiltration import (
    infiltration_rate,
    ponded_infiltration_at,
)
from app.services.parameters import make_params


def test_zero_time_zero_F_and_capped_rate(loam):
    out = ponded_infiltration_at(loam, 0.0)
    assert out["F"] == 0.0
    assert out["rate_capped"] is True
    # 形式上的无穷封顶到约定初值 Ks*(1+λ/F_FLOOR)，不允许是 inf
    assert out["f"] == pytest.approx(
        loam.ks * (1.0 + loam.suction_storage / F_FLOOR)
    )
    assert out["f"] != float("inf")


def test_rate_decreases_toward_ks(loam):
    ts = [1e-3, 0.01, 0.1, 1.0, 10.0, 100.0, 1.0e4, 1.0e6]
    outs = [ponded_infiltration_at(loam, t) for t in ts]
    fs = [o["f"] for o in outs]
    Fs = [o["F"] for o in outs]
    # 入渗率一路走低、累积入渗只增不减
    for a, b in zip(Fs, Fs[1:]):
        assert b > a
    for a, b in zip(fs, fs[1:]):
        assert b < a
    # 每一点都高于 Ks 且长历时趋近 Ks
    for f in fs:
        assert f > loam.ks
    assert fs[-1] == pytest.approx(loam.ks, rel=1e-4)


def test_F_always_above_kst_due_to_suction(loam):
    for t in [0.1, 1.0, 10.0, 100.0]:
        out = ponded_infiltration_at(loam, t)
        assert out["F"] > loam.ks * t


def test_higher_psi_more_early_infiltration():
    # 单独抬高吸力 ψ：早期阶段渗进去的水更多
    base = make_params(1.0, 5.0, 0.4)
    high = make_params(1.0, 20.0, 0.4)
    for t in [0.05, 0.2, 1.0]:
        assert ponded_infiltration_at(high, t)["F"] > \
               ponded_infiltration_at(base, t)["F"]


def test_higher_dtheta_same_front_depth_takes_longer():
    # “单独加大 Δθ，要渗到同样的量就得花更久”的物理含义：
    # 锋前锋后含水量差越大，推进到同一湿润锋深度 L 需要的水越多、越慢。
    # Green-Ampt 锋深 L=F/Δθ，时间 t(L)=[ΔθL−λln(1+ΔθL/λ)]/Ks，
    # 固定 L 时 t 随 Δθ 线性增大。
    low = make_params(1.0, 10.0, 0.2)
    high = make_params(1.0, 10.0, 0.5)
    from app.services.solver import ponded_time

    L_target = 5.0
    F_low, F_high = L_target * low.dtheta, L_target * high.dtheta
    t_low = ponded_time(F_low, low.suction_storage, low.ks)
    t_high = ponded_time(F_high, high.suction_storage, high.ks)
    assert t_high > t_low


def test_higher_dtheta_more_early_infiltration_at_fixed_time():
    # 数学上 ψ 与 Δθ 只以 λ=ψΔθ 进入方程，二者对称：
    # 单独加大 Δθ 与抬高 ψ 同向——同一早期时刻渗入的水更多。
    base = make_params(1.0, 10.0, 0.2)
    high = make_params(1.0, 10.0, 0.5)
    for t in [0.05, 0.2, 1.0]:
        assert ponded_infiltration_at(high, t)["F"] > \
               ponded_infiltration_at(base, t)["F"]


def test_higher_ks_more_infiltration_same_time():
    # 单独提高 Ks：同一时刻渗进去更多
    low = make_params(0.5, 10.0, 0.4)
    high = make_params(2.0, 10.0, 0.4)
    for t in [0.1, 1.0, 10.0]:
        assert ponded_infiltration_at(high, t)["F"] > \
               ponded_infiltration_at(low, t)["F"]


def test_rate_formula_directly(loam):
    assert infiltration_rate(loam, loam.suction_storage) == \
        pytest.approx(loam.ks * 2.0)
    assert infiltration_rate(loam, 1e6) == pytest.approx(loam.ks, rel=1e-5)


def test_output_carries_residual_and_phase(loam):
    out = ponded_infiltration_at(loam, 1.0)
    assert abs(out["residual"]) <= RESIDUAL_TOL
    assert out["residual_within_tol"] is True
    assert out["phase"] == "ponded"
    assert out["ponded"] is True
