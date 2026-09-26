"""长历时入渗过程的分段推进与可取消作业（职责四）。

长历时不是一把求一个点，而是沿时间网格逐点推进、给出 F(t)、f(t) 点列。
作业在后台线程里跑，可随时取消；中途被取消时只把状态停在 "cancelled"，
绝不能把没算完的点列当完整结果交出（取结果时只在 completed 时放行）。

隔离性：每份作业各自持有 SoilParameters 快照和独立的请求/结果容器，
推进过程中的临时量都在 worker 的局部变量里，不会跑到别的方案头上去。
"""
from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from app.config import MAX_HYDROGRAPH_POINTS, RESIDUAL_TOL
from app.errors import JobError, ValidationError
from app.services.parameters import SoilParameters, check_nonnegative, check_positive
from app.services.ponding import infiltration_at

# 每个点之间检查取消的最小间隔（秒），取消要及时但别把开销做大
_CANCEL_POLL_EVERY = 64


@dataclass
class HydrographSpec:
    """一份点列作业的输入（参数快照在此冻结）。"""

    params: SoilParameters
    t_end: float
    n_points: int
    rainfall_rate: float | None = None
    already_ponded: bool = False

    def __post_init__(self) -> None:
        # 输入校验在提交作业时就做，不进后台
        self.t_end = check_nonnegative("t_end（历时上限）", self.t_end)
        if not isinstance(self.n_points, int) or isinstance(self.n_points, bool):
            raise ValidationError("n_points 必须是整数")
        if not (2 <= self.n_points <= MAX_HYDROGRAPH_POINTS):
            raise ValidationError(
                f"n_points 必须在 [2, {MAX_HYDROGRAPH_POINTS}] 之间，"
                f"收到 {self.n_points}"
            )
        if self.rainfall_rate is not None:
            self.rainfall_rate = check_positive(
                "rainfall_rate（降雨强度）", self.rainfall_rate
            )
        if not isinstance(self.already_ponded, bool):
            raise ValidationError("already_ponded 必须是布尔值")


def _time_grid(spec: HydrographSpec) -> list[float]:
    """均匀时间网格，含 0 与 t_end 两端。"""
    if spec.n_points == 1:  # 理论上被校验挡掉，保留防御
        return [0.0]
    step = spec.t_end / (spec.n_points - 1)
    return [step * k for k in range(spec.n_points)]


def generate_points(
    spec: HydrographSpec,
    *,
    is_cancelled: Callable[[], bool] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[dict]:
    """逐点推进算完整条过程线。

    每个点独立求解，点间检查 ``is_cancelled``：一旦置位立即抛
    :class:`JobCancelled`，已算的点不会被返回。
    """
    is_cancelled = is_cancelled or (lambda: False)
    points: list[dict] = []
    total = spec.n_points

    for idx, tv in enumerate(_time_grid(spec)):
        if idx % _CANCEL_POLL_EVERY == 0 and is_cancelled():
            raise JobCancelled("点列作业已被取消，未完成的点列不予返回")
        point = infiltration_at(
            spec.params,
            tv,
            rainfall_rate=spec.rainfall_rate,
            already_ponded=spec.already_ponded,
        )
        points.append(
            {
                "t": tv,
                "F": point["F"],
                "f": point["f"],
                "phase": point["phase"],
                "ponded": point["ponded"],
                "residual": point["residual"],
                "residual_within_tol": point["residual_within_tol"],
            }
        )
        if on_progress is not None:
            on_progress(idx + 1, total)

    if is_cancelled():  # 收尾前再确认一次
        raise JobCancelled("点列作业已被取消，未完成的点列不予返回")
    return points


class JobCancelled(JobError):
    """作业在推进途中被取消。"""

    code = "job_cancelled"


@dataclass
class HydrographJob:
    """一份可取消的点列作业及其私有状态。"""

    id: str
    spec: HydrographSpec
    status: str = "queued"  # queued | running | completed | cancelled
    result: list[dict] | None = None
    error: str | None = None
    progress: tuple[int, int] = (0, 0)
    created_at: float = field(default_factory=time.time)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    def cancel(self) -> None:
        self._cancel.set()

    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)

    def public_view(self) -> dict:
        """作业的对外视图：只有 completed 才带完整点列。"""
        done, total = self.progress
        view = {
            "job_id": self.id,
            "status": self.status,
            "progress": {"done": done, "total": total},
            "t_end": self.spec.t_end,
            "n_points": self.spec.n_points,
            "rainfall_rate": self.spec.rainfall_rate,
            "already_ponded": self.spec.already_ponded,
            "soil": self.spec.params.to_dict(),
        }
        if self.status == "completed" and self.result is not None:
            view["points"] = self.result
        if self.error:
            view["error"] = self.error
        return view


class JobManager:
    """内存中的作业表：后台线程池 + 按 id 隔离的作业状态。"""

    def __init__(self, max_workers: int = 4) -> None:
        self._jobs: dict[str, HydrographJob] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="hydrograph"
        )

    def submit(self, spec: HydrographSpec) -> HydrographJob:
        job = HydrographJob(id=uuid.uuid4().hex, spec=spec)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job)
        return job

    def _run(self, job: HydrographJob) -> None:
        job.status = "running"

        def _progress(done: int, total: int) -> None:
            job.progress = (done, total)

        try:
            points = generate_points(
                job.spec, is_cancelled=job.cancelled, on_progress=_progress
            )
        except JobCancelled as exc:
            job.status = "cancelled"
            job.error = exc.message
            job.result = None  # 焊死：没算完的点列绝不交付
        except Exception as exc:  # 求解器失败等：报错不吐半成品
            job.status = "failed"
            job.error = str(exc)
            job.result = None
        else:
            # 成功落地前再次确认取消，避免“算完但已取消”仍交付
            if job.cancelled():
                job.status = "cancelled"
                job.result = None
            else:
                job.status = "completed"
                job.result = points
        finally:
            job._done.set()

    def get(self, job_id: str) -> HydrographJob:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobError(f"作业 {job_id} 不存在", http_status=404)
        return job

    def cancel(self, job_id: str) -> HydrographJob:
        job = self.get(job_id)
        if job.status == "completed":
            raise JobError(f"作业 {job_id} 已完成，无法取消")
        job.cancel()
        job.wait(timeout=2.0)
        return job

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
