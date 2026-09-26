"""Green-Ampt 入渗核算服务的异常类型。

所有对外错误都带一个可机读的 ``code`` 与一个人类可读的中文原因，
HTTP 层据此统一回带原因的错误结构。
"""
from __future__ import annotations


class ServiceError(Exception):
    """服务级错误基类。"""

    code = "service_error"
    http_status = 400

    def __init__(
        self, message: str, *, details: list[str] | None = None,
        http_status: int | None = None,
    ):
        super().__init__(message)
        self.message = message
        # 校验类错误通常一次收集所有字段问题，放在 details 里
        self.details: list[str] = details or []
        if http_status is not None:
            self.http_status = http_status

    def to_dict(self) -> dict:
        body = {"error": self.code, "message": self.message}
        if self.details:
            body["details"] = self.details
        return body


class ValidationError(ServiceError):
    """土壤参数 / 时间 / 降雨强度等输入不合法（在任何迭代之前挡下）。"""

    code = "validation_error"
    http_status = 400


class SolverError(ServiceError):
    """隐式方程迭代到上限仍未收敛——宁可报错，不吐未收敛的初值。"""

    code = "solver_error"
    http_status = 500


class NotFoundError(ServiceError):
    """按名字取工况档时查无此档。"""

    code = "not_found"
    http_status = 404


class JobError(ServiceError):
    """点列作业本身的状态问题（查不到、已取消、未完成等）。"""

    code = "job_error"
    http_status = 409
