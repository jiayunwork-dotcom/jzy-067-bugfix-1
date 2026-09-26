"""入渗率与积水入渗结果（职责三的积水侧）。

对外只负责「地表已经积水」的账：给定土壤与时刻，走
    F − λ·ln(1 + F/λ) = Ks·t
解出 F，再由 f = Ks·(1 + λ/F) 给瞬时入渗率。
随 F 增大 f 单调下降、趋近 Ks。

t=0 时 F=0，f 在形式上趋于无穷——数值上把 F 夹到 F_FLOOR，
对外回报约定初值 f0 = Ks·(1 + λ/F_FLOOR) 并打上 capped 标记。
"""
from __future__ import annotations

from app.config import F_FLOOR, RESIDUAL_TOL
from app.errors import ValidationError
from app.services.parameters import SoilParameters, check_nonnegative
from app.services.solver import residual, solve_f


def infiltration_rate(
    params: SoilParameters, F: float, *, floor: float = F_FLOOR
) -> float:
    """f = Ks·(1 + ψΔθ/F)；F 夹到数值下限，形式无穷封顶为约定初值。"""
    f_safe = F if F > floor else floor
    return params.ks * (1.0 + params.suction_storage / f_safe)


def ponded_infiltration_at(
    params: SoilParameters,
    t: float,
    *,
    tol: float = RESIDUAL_TOL,
) -> dict:
    """从时刻零就积水时，时刻 t 的入渗核算结果。

    返回 {t, F, f, residual, ponded, phase, residual_within_tol}。
    时间为负在迭代之前挡下；土壤参数假定已由 make_params 校验。
    """
    t_v = check_nonnegative("t（历时）", t)
    lam = params.suction_storage
    F = solve_f(params.ks * t_v, lam, tol=tol)
    r = residual(F, lam, params.ks * t_v)
    capped = F <= F_FLOOR
    f = infiltration_rate(params, F)
    return {
        "t": t_v,
        "F": F,
        "f": f,
        "residual": r,
        "residual_abs": abs(r),
        "residual_tol": tol,
        "residual_within_tol": abs(r) <= tol,
        "rate_capped": capped,
        "ponded": True,
        "phase": "ponded",
        "equation": "F - psi*dtheta*ln(1 + F/(psi*dtheta)) = ks*t",
        "soil": params.to_dict(),
    }
