"""隐式求解器的因果关系测试。

专门盯住最隐蔽的实现错误：对数项符号。正确式 q(F)=F−λln(1+F/λ) 下 q(F)<F，
解 F 必然大于目标右端项（积水时即大于 Ks·t）；符号写反会得到 F<Ks·t。
"""
from __future__ import annotations

import math

import pytest

from app.config import F_FLOOR, RESIDUAL_TOL
from app.errors import SolverError
from app.services.parameters import make_params
from app.services.solver import (
    d_ponded_rhs,
    ponded_rhs,
    residual,
    solve_f,
    ponded_time,
)


def test_log_sign_makes_F_greater_than_target():
    # λ>0 时 ln(1+F/λ)>0，故 q(F)<F；解必须大于目标右端项
    lam = 6.0 * 0.434
    target = 1.04  # 对应 Ks*t，t=1
    F = solve_f(target, lam)
    assert F > target
    # 与“符号写反”的错误式对照：错误式 F+λln(1+F/λ)=target 的解必 < target
    # 这里直接断言解落在正确一侧
    assert ponded_rhs(F, lam) == pytest.approx(target, abs=RESIDUAL_TOL)
    assert F - target > 0.1 * target  # 吸力项作用显著（壤土约为 2.9 倍）


def test_wrong_sign_reference_equation_is_distinguishable():
    # 把错误符号解代回正确方程，残差必然巨大——钉死符号这件事
    lam = 3.858
    target = 1.04
    F_wrong = 0.5  # 任何 F<target 的候选都不可能是正确式的解
    assert residual(F_wrong, lam, target) < -RESIDUAL_TOL


def test_residual_within_tolerance_across_times(loam):
    lam = loam.suction_storage
    for t in [0.0, 1e-6, 1e-3, 0.1, 1.0, 10.0, 100.0, 1000.0]:
        target = loam.ks * t
        F = solve_f(target, lam)
        assert abs(residual(F, lam, target)) <= RESIDUAL_TOL


def test_residual_reported_below_threshold_via_infiltration(loam):
    from app.services.infiltration import ponded_infiltration_at

    for t in [0.01, 0.5, 1.0, 24.0]:
        out = ponded_infiltration_at(loam, t)
        assert out["residual_within_tol"] is True
        assert abs(out["residual"]) <= RESIDUAL_TOL


def test_zero_time_gives_zero_F():
    F = solve_f(0.0, 3.0)
    assert F == 0.0


def test_F_monotonic_in_time(loam):
    lam = loam.suction_storage
    ts = [1e-4 * 2 ** k for k in range(20)]
    Fs = [solve_f(loam.ks * t, lam) for t in ts]
    for a, b in zip(Fs, Fs[1:]):
        assert b > a


def test_long_time_identity(loam):
    # 长历时恒等式：F − Ks·t = λ·ln(1 + F/λ)，且 F 始终大于 Ks·t
    lam = loam.suction_storage
    t = 1e6
    F = solve_f(loam.ks * t, lam)
    assert F > loam.ks * t
    assert F - loam.ks * t == pytest.approx(
        lam * math.log1p(F / lam), rel=1e-8
    )


def test_derivative_positive_and_below_one():
    lam = 3.0
    for F in [1e-8, 0.1, 1.0, 100.0]:
        d = d_ponded_rhs(F, lam)
        assert 0.0 < d < 1.0


def test_newton_failure_raises_instead_of_returning_guess():
    # max_iterations=0：一次迭代都不许做，必须抛 SolverError，不能吐初值
    with pytest.raises(SolverError) as ei:
        solve_f(1.0, 3.0, max_iterations=0)
    assert "收敛" in ei.value.message or "converg" in ei.value.message.lower()


def test_nonpositive_lambda_rejected():
    with pytest.raises(SolverError):
        solve_f(1.0, 0.0)
    with pytest.raises(SolverError):
        solve_f(1.0, -1.0)


def test_negative_target_rejected():
    with pytest.raises(SolverError):
        solve_f(-0.1, 3.0)


def test_time_inversion_consistency(loam):
    # 显式时间 t(F) 与隐式反解 F(t) 互为反函数
    lam = loam.suction_storage
    for F in [0.1, 1.0, 5.0, 50.0]:
        t = ponded_time(F, lam, loam.ks)
        F_back = solve_f(loam.ks * t, lam)
        assert F_back == pytest.approx(F, rel=1e-9)


def test_loam_one_hour_noticeably_above_kst(loam):
    # 预置壤土算例的核对口径：1 小时 F 明显大于 Ks·t
    out_target = loam.ks * 1.0
    F = solve_f(out_target, loam.suction_storage)
    assert F > 1.5 * out_target
