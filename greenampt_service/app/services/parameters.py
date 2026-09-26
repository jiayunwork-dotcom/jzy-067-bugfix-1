"""土壤参数的定义与校验（职责一）。

Green-Ampt 模型由三个参数刻画：
    ks        饱和导水率 Ks，必须为正；
    psi       湿润锋基质吸力 ψ（正值），必须为正；
    dtheta    锋前后含水量差 Δθ，必须落在 (0, 1]。

所有数值还必须是有限实数（拒绝 NaN / Inf）。校验在任何迭代之前进行，
非法输入一次性收集全部问题，抛 ``ValidationError``（回带原因）。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from numbers import Real
from typing import Any

from app.errors import ValidationError

_BOOL = bool  # bool 是 int 的子类，需单独挡掉，True/False 不当作数值


def check_positive(name: str, value: Any) -> float:
    """校验“必须为正”的数值字段（Ks、ψ、降雨强度、时刻上限等）。

    返回浮点化后的值；不合法时把原因追加进 errors（由调用方统一抛错），
    返回 NaN 占位以免后续解引用出错。
    """
    if not isinstance(value, Real) or isinstance(value, _BOOL):
        raise ValidationError(
            f"参数 {name} 必须是数值，收到的是 {value!r}"
        )
    fv = float(value)
    if not math.isfinite(fv):
        raise ValidationError(f"参数 {name} 必须是有限实数，收到的是 {value!r}")
    if fv <= 0.0:
        raise ValidationError(f"参数 {name} 必须为正，收到的是 {fv:g}")
    return fv


def check_nonnegative(name: str, value: Any) -> float:
    """校验“允许为零、不可为负”的数值字段（时间 t）。"""
    if not isinstance(value, Real) or isinstance(value, _BOOL):
        raise ValidationError(
            f"参数 {name} 必须是数值，收到的是 {value!r}"
        )
    fv = float(value)
    if not math.isfinite(fv):
        raise ValidationError(f"参数 {name} 必须是有限实数，收到的是 {value!r}")
    if fv < 0.0:
        raise ValidationError(f"参数 {name} 不可为负，收到的是 {fv:g}")
    return fv


def check_dtheta(value: Any) -> float:
    """校验含水量差 Δθ ∈ (0, 1]。"""
    if not isinstance(value, Real) or isinstance(value, _BOOL):
        raise ValidationError(
            f"参数 dtheta（Δθ）必须是数值，收到的是 {value!r}"
        )
    fv = float(value)
    if not math.isfinite(fv):
        raise ValidationError(
            f"参数 dtheta（Δθ）必须是有限实数，收到的是 {value!r}"
        )
    if not (0.0 < fv <= 1.0):
        raise ValidationError(
            f"参数 dtheta（Δθ）必须落在 (0, 1] 区间，收到的是 {fv:g}"
        )
    return fv


@dataclass(frozen=True)
class SoilParameters:
    """一组 Green-Ampt 土壤参数，构造即保证合法。

    直接构造（绕过校验）仅供测试求解器时使用；外部一律走 :func:`make_params`。
    """

    ks: float
    psi: float
    dtheta: float
    name: str | None = field(default=None, compare=False)

    @property
    def suction_storage(self) -> float:
        """吸力项 λ = ψ·Δθ：模型里反复出现的组合量。"""
        return self.psi * self.dtheta

    def to_dict(self) -> dict:
        d = {
            "ks": self.ks,
            "psi": self.psi,
            "dtheta": self.dtheta,
            "suction_storage": self.suction_storage,
        }
        if self.name is not None:
            d["name"] = self.name
        return d


def make_params(
    ks: Any, psi: Any, dtheta: Any, *, name: str | None = None
) -> SoilParameters:
    """校验三项土壤参数并建档；Ks、Δθ、ψ 任一不合法都在迭代前挡下。

    这里一次性收集所有字段的问题，让调用方一次看到全部原因
    （错误结构 details）。
    """
    errors: list[str] = []

    try:
        ks_f = check_positive("ks（饱和导水率 Ks）", ks)
    except ValidationError as exc:
        ks_f = float("nan")
        errors.append(exc.message)

    try:
        psi_f = check_positive("psi（湿润锋基质吸力 ψ）", psi)
    except ValidationError as exc:
        psi_f = float("nan")
        errors.append(exc.message)

    try:
        dtheta_f = check_dtheta(dtheta)
    except ValidationError as exc:
        dtheta_f = float("nan")
        errors.append(exc.message)

    if errors:
        raise ValidationError("土壤参数校验未通过", details=errors)
    return SoilParameters(ks=ks_f, psi=psi_f, dtheta=dtheta_f, name=name)
