"""服务级常量与默认配置。

单位约定（全服务自洽即可，不强制具体单位制）：
    Ks、ψ、F、f 使用同一套长度/时间单位，例如 cm 与 h；
    Δθ 为体积含水量之差，无量纲，取 (0, 1]；
    t 与时间单位一致（例如 h）。
"""
from __future__ import annotations

import os

# 入渗量的数值下限：t=0 时形式上 F=0，对 F 做除法前先夹到这里
F_FLOOR = 1.0e-10

# 隐式方程残差阈值：对外给出的 F 必须让两侧残差压到此值以下
RESIDUAL_TOL = 1.0e-10

# 牛顿迭代上限
MAX_ITERATIONS = 100

# 入渗率在 t→0 时形式上趋于无穷；数值上用 F_FLOOR 夹底，
# 即 f0 = Ks*(1 + ψΔθ/F_FLOOR)，作为对外回报的约定初值（在 infiltration 模块计算）。

# 点列作业允许的最大点数（防呆）
MAX_HYDROGRAPH_POINTS = 1_000_000

# 工况档持久化目录（容器内挂到持久化位置；默认 /data）
DATA_DIR = os.environ.get("GA_DATA_DIR", "/data")
PROFILE_FILE = "profiles.json"
