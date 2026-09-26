"""积水时刻判定与降雨分段（自由入渗 → 积水式）测试。"""
from __future__ import annotations

import pytest

from app.config import RESIDUAL_TOL
from app.services.parameters import make_params
from app.services.ponding import (
    infiltration_at,
    ponding_time,
    rainfall_infiltration_at,
)


def test_i_below_ks_never_ponds(loam):
    for i in [0.1, 0.5 * loam.ks, loam.ks]:
        r = ponding_time(loam, i)
        assert r["will_pond"] is False
        assert r["tp"] is None


def test_i_above_ks_ponds_with_positive_tp(loam):
    i = 2.0 * loam.ks
    r = ponding_time(loam, i)
    assert r["will_pond"] is True
    assert r["tp"] > 0
    # 积水时刻能力恰好等于降雨强度
    Fp = r["Fp"]
    f_at_pond = loam.ks * (1 + loam.suction_storage / Fp)
    assert f_at_pond == pytest.approx(i)


def test_free_phase_then_ponded_phase(loam):
    i = 3.0
    tp = ponding_time(loam, i)["tp"]
    pre = rainfall_infiltration_at(loam, 0.5 * tp, i)
    at = rainfall_infiltration_at(loam, tp, i)
    post = rainfall_infiltration_at(loam, tp + 1.0, i)

    assert pre["phase"] == "free"
    assert pre["ponded"] is False
    assert pre["F"] == pytest.approx(i * 0.5 * tp)
    assert pre["f"] == i

    assert at["phase"] == "ponded"
    assert post["phase"] == "ponded"
    # 积水点连续：tp 左侧（自由段）与 tp 处（积水段）F 一致
    left = rainfall_infiltration_at(loam, tp - 1e-9, i)
    assert at["F"] == pytest.approx(left["F"], rel=1e-6)


def test_continuity_at_ponding(loam):
    # 积水前后两侧 F 连续、f 连续（自由段末率 i，积水段初率≈i）
    i = 2.5
    tp = ponding_time(loam, i)["tp"]
    just_before = rainfall_infiltration_at(loam, tp * (1 - 1e-9), i)
    just_after = rainfall_infiltration_at(loam, tp * (1 + 1e-9), i)
    assert just_before["F"] == pytest.approx(just_after["F"], rel=1e-6)
    assert just_before["f"] == pytest.approx(just_after["f"], rel=1e-5)


def test_ponded_phase_residual_within_tol(loam):
    i = 3.0
    for t in [0.5, 2.0, 50.0]:
        out = rainfall_infiltration_at(loam, t, i)
        if out["phase"] == "ponded":
            assert abs(out["residual"]) <= RESIDUAL_TOL
            assert out["residual_within_tol"] is True


def test_no_ponding_whole_history_free(loam):
    i = 0.8 * loam.ks
    for t in [0.1, 1.0, 100.0]:
        out = rainfall_infiltration_at(loam, t, i)
        assert out["phase"] == "free"
        assert out["F"] == pytest.approx(i * t)
        assert out["f"] == i


def test_already_ponded_uses_ponded_equation_from_zero(loam):
    out = infiltration_at(loam, 1.0, already_ponded=True)
    assert out["phase"] == "ponded"
    assert out["F"] > loam.ks * 1.0


def test_F_monotone_through_ponding(loam):
    i = 3.0
    tp = ponding_time(loam, i)["tp"]
    ts = [0.0, 0.25 * tp, 0.75 * tp, tp, 1.5 * tp, 3 * tp, 10 * tp]
    Fs = [rainfall_infiltration_at(loam, t, i)["F"] for t in ts]
    for a, b in zip(Fs, Fs[1:]):
        assert b >= a


def test_higher_intensity_ponds_earlier(loam):
    t1 = ponding_time(loam, 1.5 * loam.ks)["tp"]
    t2 = ponding_time(loam, 5.0 * loam.ks)["tp"]
    assert t2 < t1
