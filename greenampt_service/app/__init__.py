"""Flask 应用工厂：装配工况档库、作业管理器、路由与统一错误结构。"""
from __future__ import annotations

import os

from flask import Flask, jsonify

from app.errors import ServiceError
from app.routes import api
from app.services.hydrograph import JobManager
from app.services.persistence import ProfileStore


def create_app(
    *,
    data_dir: str | None = None,
    profile_filename: str = "profiles.json",
    job_workers: int = 4,
) -> Flask:
    app = Flask(__name__)

    store = ProfileStore(
        data_dir=data_dir or os.environ.get("GA_DATA_DIR", "/data"),
        filename=profile_filename,
    )
    manager = JobManager(max_workers=job_workers)
    app.extensions["profile_store"] = store
    app.extensions["job_manager"] = manager

    app.register_blueprint(api)

    @app.errorhandler(ServiceError)
    def _handle_service_error(exc: ServiceError):
        return jsonify(exc.to_dict()), exc.http_status

    @app.errorhandler(404)
    def _handle_404(_exc):
        return (
            jsonify({"error": "not_found", "message": "请求的资源或路径不存在"}),
            404,
        )

    @app.errorhandler(405)
    def _handle_405(_exc):
        return jsonify({"error": "method_not_allowed", "message": "方法不允许"}), 405

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        # 未预期错误也统一成错误结构，不泄露堆栈
        app.logger.exception("未预期错误: %s", exc)
        return (
            jsonify({"error": "internal_error", "message": f"服务内部错误：{exc}"}),
            500,
        )

    return app
