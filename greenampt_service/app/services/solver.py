"""Green-Ampt 隐式累积入渗量求解器（职责二，独立于积水分段逻辑）。

积水情形下累积入渗量 F 满足隐式关系（长度单位）：

    q(F) = F − λ·ln(1 + F/λ) = 目标右端项，     λ = ψ·Δθ

两种时间平移情形共用同一个求解器：
  * 从时刻零就积水：目标右端项 = Ks·t；
  * 降雨积水：目标右端项 = Ks·(t − tp) + Fp（见 ponding 模块）。

注意对数项的符号：q(F) = F − λ·ln(1 + F/λ)。
对所有 F>0 都有 ln(1+F/λ) > 0，因此 q(F) < F，
解出的 F 必然**大于**目标右端项（吸力项的作用）。
若把符号写成 F + λ·ln(...)，会得到 F < Ks·t 的错误结果，
早期入渗行为整个失真——测试专门盯住这一点（tests/test_solver.py）。

数值方法：牛顿迭代 + 括号保护（牛顿步越界时退化为二分法）。
g(F) = q(F) − target 在 [0,∞) 上单调（g'(F) = F/(F+λ) > 0），
括号法保证只要迭代够多必能收敛；迭代到上限仍不达标则抛 SolverError，
绝不把没解出来的初值当结果吐出。
"""
from __future__ import annotations

import math

from app.config import F_FLOOR, MAX_ITERATIONS, RESIDUAL_TOL
from app.errors import SolverError


def ponded_rhs(F: float, lam: float) -> float:
    """q(F) = F − λ·ln(1 + F/λ)，隐式方程左端（长度量纲）。"""
    return F - lam * math.log1p(F / lam)


def residual(F: float, lam: float, target: float) -> float:
    """隐式方程残差 g(F) = q(F) − target；合格解必须 |g| ≤ 阈值。"""
    return ponded_rhs(F, lam) - target


def d_ponded_rhs(F: float, lam: float) -> float:
    """q'(F) = 1 − 1/(1+F/λ) = F/(F+λ)，牛顿步导数。"""
    return F / (F + lam)


def solve_f(
    target: float,
    lam: float,
    *,
    tol: float = RESIDUAL_TOL,
    max_iterations: int = MAX_ITERATIONS,
) -> float:
    """对 q(F) = target 求解 F（target ≥ 0，λ = ψΔθ > 0）。

    返回的 F 保证 |q(F) − target| ≤ tol；target=0 时 F=0。
    迭代不收敛时抛 :class:`SolverError`。
    """
    if lam <= 0.0:
        # 正常路径由参数校验挡住；这里是求解器自身的最后防线
        raise SolverError(f"吸力项 λ=ψ·Δθ 必须为正，收到 {lam:g}")
    if target < 0.0:
        raise SolverError(f"目标右端项不可为负，收到 {target:g}")
    if target == 0.0:
        # 时刻为零：累积入渗量为零（数值下限由入渗率一侧处理）
        return 0.0

    # ---- 找括号 [lo, hi]：g(lo)<0，g(hi)>=0 ----
    # q(F) < F 恒成立，所以 target 一定在解的左侧，可直接作为下界。
    lo = target
    glo = ponded_rhs(lo, lam) - target  # 必 < 0（target>0）

    # 小 target 时 q(F)≈F²/(2λ)，平方根给出好的上界初值；
    # 再保险地倍增直到夹住。
    hi = target + 2.0 * math.sqrt(2.0 * lam * target)
    hi = max(hi, F_FLOOR)
    g_hi = ponded_rhs(hi, lam) - target
    bracket_guards = 0
    while g_hi < 0.0:
        hi *= 2.0
        g_hi = ponded_rhs(hi, lam) - target
        bracket_guards += 1
        if bracket_guards > 200:  # 数值异常时的理论外防线
            raise SolverError(
                f"无法为隐式方程夹住根（target={target:g}, λ={lam:g}）"
            )

    # ---- 牛顿迭代，越界步退化为二分 ----
    x = 0.5 * (lo + hi)
    last_g = g_hi
    for iteration in range(1, max_iterations + 1):
        g = ponded_rhs(x, lam) - target
        last_g = g
        if abs(g) <= tol:
            return x

        gp = d_ponded_rhs(x, lam)
        if gp > 0.0:
            nx = x - g / gp
            # 括号保护：牛顿步必须落在 (lo, hi) 内，否则二分
            if lo < nx < hi:
                pass
            else:
                nx = 0.5 * (lo + hi)
        else:
            nx = 0.5 * (lo + hi)

        # 维护括号
        g_nx = ponded_rhs(nx, lam) - target
        if g_nx == 0.0 or abs(g_nx) <= tol:
            return nx
        if g_nx < 0.0:
            lo, glo = nx, g_nx
        else:
            hi, g_hi = nx, g_nx
        x = nx

    raise SolverError(
        "Green-Ampt 隐式方程牛顿迭代未在 "
        f"{max_iterations} 次内收敛到残差阈值 {tol:g}："
        f"末次残差 |g(F)|={abs(last_g):.3e}（target={target:g}, λ={lam:g}）"
    )


def ponded_time(F: float, lam: float, ks: float) -> float:
    """t(F) = (F − λ·ln(1+F/λ)) / Ks：积水式的显式时间反解。"""
    return ponded_rhs(F, lam) / ks
