"""积水时刻判定与降雨下的分段入渗（职责三的降雨侧）。

降雨强度 i 与入渗能力 f 的关系决定何时积水：

* i ≤ Ks 时，入渗能力 f = Ks(1 + λ/F) 恒大于 Ks ≥ i，
  降雨永远全部渗入——**不会积水**，明确回报该判定；
* i > Ks 时，能力随 F 增大而下降，二者相等时开始积水。
  令 i = Ks(1 + λ/Fp)，得积水点累积入渗量
      Fp = Ks·λ/(i − Ks)，   λ = ψ·Δθ
  积水前自由入渗 F = i·t，故积水时刻（Mein–Larson）
      tp = Fp/i = Ks·λ/[i·(i − Ks)]。
* t < tp：自由入渗，F = i·t，实际入渗率 = i（全部渗入，地表不积水）；
* t ≥ tp：转入积水式（时间平移）：
      F − λ·ln(1 + F/λ) = Ks·(t − tp) + [Fp − λ·ln(1 + Fp/λ)]。
"""
from __future__ import annotations

import math

from app.config import F_FLOOR, RESIDUAL_TOL
from app.services.infiltration import infiltration_rate, ponded_infiltration_at
from app.services.parameters import SoilParameters, check_nonnegative, check_positive
from app.services.solver import ponded_rhs, residual, solve_f


def ponding_time(params: SoilParameters, i: float) -> dict:
    """给定降雨强度 i，判定是否积水并解出积水时刻 tp。"""
    iv = check_positive("i（降雨强度）", i)
    lam = params.suction_storage

    if iv <= params.ks:
        return {
            "will_pond": False,
            "rainfall_rate": iv,
            "ks": params.ks,
            "tp": None,
            "Fp": None,
            "reason": (
                f"降雨强度 i={iv:g} 不超过饱和导水率 Ks={params.ks:g}，"
                "入渗能力恒高于降雨强度，永远不会积水"
            ),
        }

    Fp = params.ks * lam / (iv - params.ks)
    tp = Fp / iv  # 自由段 F=i·t
    return {
        "will_pond": True,
        "rainfall_rate": iv,
        "ks": params.ks,
        "tp": tp,
        "Fp": Fp,
        "reason": (
            f"降雨强度 i={iv:g} 大于 Ks={params.ks:g}，"
            f"自由入渗至 t={tp:g} 时入渗能力降到与降雨强度相等，开始积水"
        ),
    }


def rainfall_infiltration_at(
    params: SoilParameters,
    t: float,
    i: float,
    *,
    tol: float = RESIDUAL_TOL,
) -> dict:
    """给定降雨强度 i 时，时刻 t 的入渗核算（自动分自由/积水两段）。"""
    t_v = check_nonnegative("t（历时）", t)
    iv = check_positive("i（降雨强度）", i)
    lam = params.suction_storage

    base = {"t": t_v, "soil": params.to_dict(), "rainfall_rate": iv}

    # 不会积水：整段自由入渗
    if iv <= params.ks:
        F = iv * t_v
        return {
            **base,
            "F": F,
            "f": iv,
            "f_capacity": infiltration_rate(params, F),
            "residual": 0.0,
            "residual_abs": 0.0,
            "residual_tol": tol,
            "residual_within_tol": True,
            "rate_capped": t_v == 0.0,
            "ponded": False,
            "will_pond": False,
            "tp": None,
            "phase": "free",
            "equation": "free infiltration: F = i*t (i <= Ks, never ponded)",
        }

    Fp = params.ks * lam / (iv - params.ks)
    tp = Fp / iv  # 自由段 F=i·t

    # 积水前：水先全部渗入，地表不积水
    if t_v < tp:
        F = iv * t_v
        return {
            **base,
            "F": F,
            "f": iv,
            "f_capacity": infiltration_rate(params, F),
            "residual": 0.0,
            "residual_abs": 0.0,
            "residual_tol": tol,
            "residual_within_tol": True,
            "rate_capped": t_v == 0.0,
            "ponded": False,
            "will_pond": True,
            "tp": tp,
            "Fp": Fp,
            "phase": "free",
            "equation": "free infiltration: F = i*t (t < tp)",
        }

    # 积水后：时间平移的隐式积水式
    offset = ponded_rhs(Fp, lam)  # q(Fp) = Fp − λ·ln(1 + Fp/λ)
    target = params.ks * (t_v - tp) + offset
    F = solve_f(target, lam, tol=tol)
    r = residual(F, lam, target)
    return {
        **base,
        "F": F,
        "f": infiltration_rate(params, F),
        "residual": r,
        "residual_abs": abs(r),
        "residual_tol": tol,
        "residual_within_tol": abs(r) <= tol,
        "rate_capped": False,
        "ponded": True,
        "will_pond": True,
        "tp": tp,
        "Fp": Fp,
        "phase": "ponded",
        "equation": (
            "F - psi*dtheta*ln(1+F/(psi*dtheta)) "
            "= ks*(t-tp) + Fp - psi*dtheta*ln(1+Fp/(psi*dtheta))"
        ),
    }


def infiltration_at(
    params: SoilParameters,
    t: float,
    *,
    rainfall_rate: float | None = None,
    already_ponded: bool = False,
    tol: float = RESIDUAL_TOL,
) -> dict:
    """统一入口：已声明积水走积水式；否则按降雨强度分段判定。

    * ``already_ponded=True``：从时刻零就走积水式（忽略降雨强度）；
    * 给出 ``rainfall_rate``：先判积水时刻，再取对应段；
    * 两者都不给：默认按地表已积水处理（保守、与模型核心一致）。
    """
    if already_ponded or rainfall_rate is None:
        return ponded_infiltration_at(params, t, tol=tol)
    return rainfall_infiltration_at(params, t, rainfall_rate, tol=tol)
