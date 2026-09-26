# Green–Ampt 湿润锋入渗核算服务

把一场雨的水分账算清楚：给定饱和导水率 `Ks`、湿润锋基质吸力 `ψ`、
锋前后含水量差 `Δθ` 与历时，回报**累积入渗量 F**、**瞬时入渗率 f** 与
**隐式方程残差**；再给降雨强度 `i`，回报**积水时刻 tp** 与「是否会积水」。

后端：Python 3.12 + Flask，无网页界面，仅 HTTP JSON 应答。

## 模型

已积水时累积入渗量满足隐式关系（λ = ψ·Δθ）：

```
F − λ·ln(1 + F/λ) = Ks·t
```

- 时间是入渗量的显函数，反解 F 用**牛顿迭代 + 括号保护**（越界步退化二分），
  对外给出的 F 保证残差 `|F − λ·ln(1+F/λ) − Ks·t| ≤ 1e-10`，残差一并回报；
  迭代到上限不收敛直接报错，不吐未收敛的初值。
- 瞬时入渗率 `f = Ks·(1 + λ/F)`，随 F 单调下降、趋近 Ks。
  `t=0` 时形式上的无穷封顶为约定初值 `Ks·(1+λ/1e-10)`，并标 `rate_capped`。
- **对数项为减号**：q(F) < F，故解出的 F 恒大于 Ks·t（吸力项的作用）。
  符号写反会得到 F < Ks·t 的失真结果，测试专门钉住这一点。

降雨时：

- `i ≤ Ks`：入渗能力恒高于降雨强度，**永远不积水**；
- `i > Ks`：先自由入渗 `F=i·t`，到 `tp = Fp/i = Ks·λ/[i·(i−Ks)]`
  （`Fp = Ks·λ/(i−Ks)`）开始积水，之后走时间平移的隐式积水式：
  `F − λ·ln(1+F/λ) = Ks·(t−tp) + Fp − λ·ln(1+Fp/λ)`。
- 请求里声明 `already_ponded=true` 则从时刻零就走积水式（忽略降雨强度）；
  给了 `rainfall_rate` 而不声明该开关时按降雨自动分段（与显式
  `already_ponded=false` 完全一致）；两者都不给则缺省按地表已积水处理。

单位自洽即可（如 Ks、ψ、F、f 用 cm/h，t 用 h），Δθ 无量纲。

## 代码结构（按职责切开）

```
app/
  config.py                 # 常量：残差阈值、数值下限、数据目录
  errors.py                 # 统一错误结构（code + 原因）
  routes.py                 # HTTP 路由（只做报文解析/封装）
  services/
    parameters.py           # 土壤参数校验（迭代前挡非法输入）
    solver.py               # 隐式入渗量求解（独立文件）
    infiltration.py         # 入渗率 + 已积水入渗结果
    ponding.py              # 积水时刻判定与降雨分段
    hydrograph.py           # 历时点列分段推进（可取消作业）
    persistence.py          # 工况建档持久化（JSON，原子写）
tests/                      # 自动化测试
Dockerfile                  # 构建时跑 pytest，容器起即可应答
```

## 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET  | `/health` | 健康检查 |
| POST | `/api/infiltration` | 给定时刻：F、f、残差、段别 |
| POST | `/api/ponding` | 降雨强度：tp 与 will_pond 判定 |
| GET  | `/api/profiles` | 列出工况档（预置 loam、silt_loam） |
| POST | `/api/profiles` | 按名字建档 |
| GET  | `/api/profiles/<name>` | 取档 |
| DELETE | `/api/profiles/<name>` | 删档 |
| POST | `/api/hydrographs` | 提交长历时点列作业（202 + job_id，可取消） |
| GET  | `/api/hydrographs/<id>` | 查作业；completed 才带完整 points |
| POST | `/api/hydrographs/<id>/cancel` | 取消；未完成点列绝不交付 |

入参土壤来源二选一：建档名 `{"profile": "loam"}`，
或现场 `{"ks", "psi", "dtheta"}`。

示例：

```bash
# 已积水，1 小时
curl -s localhost:8000/api/infiltration -H 'Content-Type: application/json' \
  -d '{"ks":1.04,"psi":6.0,"dtheta":0.434,"t":1.0,"already_ponded":true}'

# 降雨强度 3 cm/h，5 小时（自动分自由/积水两段）
curl -s localhost:8000/api/infiltration -H 'Content-Type: application/json' \
  -d '{"profile":"loam","t":5.0,"rainfall_rate":3.0,"already_ponded":false}'

# 只问积水时刻
curl -s localhost:8000/api/ponding -H 'Content-Type: application/json' \
  -d '{"profile":"loam","rainfall_rate":3.0}'
```

非法输入统一回 400：`{"error":"validation_error","message":...,"details":[...]}`；
迭代不收敛回 500 `solver_error`。

## 预置壤土算例

`loam`：Ks=1.04 cm/h，ψ=6.0 cm，Δθ=0.434。
由于吸力项 λ≈2.60，1 小时累积入渗量 F≈3.07 cm，**明显大于 Ks·t=1.04 cm**（约 2.9 倍），
拉起服务即可用它核对（`GET /api/profiles/loam`）。

## 本地运行

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
GA_DATA_DIR=./data flask --app wsgi:app run --port 8000   # 或 gunicorn wsgi:app
pytest -q
```

## Docker

```bash
docker build -t greenampt .            # 构建同时跑全部自动化测试
docker run -p 8000:8000 greenampt      # 起服务
docker run greenampt test              # 只跑测试
```

工况档写在容器内 `/data`（`GA_DATA_DIR` 可改），可用卷持久化：
`-v "$PWD/data:/data"`。

## 并发与隔离

每份方案各自持有土壤参数快照，求解器是无状态纯函数；
点列作业在各自线程内推进，临时量全部在函数局部账下，互不串档。
生产用单 worker + 多线程（见 entrypoint），作业表进程内有效；
工况档落 `/data` 持久化。

## 测试钉住的因果关系

- t=0 ⇒ F=0，入渗率无穷封顶约定初值；
- F 随时间只增不减，f 一路走低并趋近 Ks；
- 单抬 ψ ⇒ 早期 F 更大；单加 Δθ ⇒ 达同样 F 更久；单提 Ks ⇒ 同时刻 F 更大；
- 隐式残差 ≤ 1e-10；i ≤ Ks 判为不会积水；
- 牛顿不收敛必报错；积水前后 F、f 连续；
- 点列作业取消后绝不交出半成品；多方案并发结果各自对得上自己的账。
