"""参数校验：非法输入必须在任何迭代之前挡下，回带原因。"""
from __future__ import annotations

import pytest

from app.errors import ValidationError
from app.services.parameters import make_params


def test_ks_must_be_positive():
    with pytest.raises(ValidationError) as ei:
        make_params(0, 8.0, 0.4)
    assert "ks" in ei.value.message or any("ks" in d for d in ei.value.details)
    with pytest.raises(ValidationError):
        make_params(-1.0, 8.0, 0.4)


def test_dtheta_range():
    with pytest.raises(ValidationError):
        make_params(1.0, 8.0, 0.0)
    with pytest.raises(ValidationError):
        make_params(1.0, 8.0, -0.2)
    with pytest.raises(ValidationError):
        make_params(1.0, 8.0, 1.2)
    # 边界：1.0 合法
    p = make_params(1.0, 8.0, 1.0)
    assert p.dtheta == 1.0


def test_psi_must_be_positive():
    with pytest.raises(ValidationError):
        make_params(1.0, 0.0, 0.4)
    with pytest.raises(ValidationError):
        make_params(1.0, -3.0, 0.4)


def test_negative_time_rejected_before_iteration(loam):
    from app.services.infiltration import ponded_infiltration_at

    with pytest.raises(ValidationError) as ei:
        ponded_infiltration_at(loam, -0.5)
    assert "t" in ei.value.message


def test_non_finite_and_bool_rejected():
    with pytest.raises(ValidationError):
        make_params(float("nan"), 8.0, 0.4)
    with pytest.raises(ValidationError):
        make_params(float("inf"), 8.0, 0.4)
    with pytest.raises(ValidationError):
        make_params(True, 8.0, 0.4)  # bool 不能冒充数值


def test_all_field_problems_collected():
    with pytest.raises(ValidationError) as ei:
        make_params(0, -1, 2.0)
    assert len(ei.value.details) == 3


def test_negative_rainfall_rejected(loam):
    from app.services.ponding import ponding_time, rainfall_infiltration_at

    with pytest.raises(ValidationError):
        ponding_time(loam, -1.0)
    with pytest.raises(ValidationError):
        rainfall_infiltration_at(loam, 1.0, 0.0)
