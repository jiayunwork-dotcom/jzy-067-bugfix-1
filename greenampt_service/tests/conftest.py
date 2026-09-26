"""测试夹具：用临时数据目录拉起应用，互不污染容器内 /data。"""
from __future__ import annotations

import pytest

from app import create_app
from app.config import F_FLOOR
from app.services.parameters import make_params


@pytest.fixture()
def app(tmp_path):
    application = create_app(data_dir=str(tmp_path / "data"), job_workers=2)
    application.config.update(TESTING=True)
    yield application
    application.extensions["job_manager"].shutdown()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def loam():
    # 与预置壤土算例一致
    return make_params(1.04, 6.0, 0.434, name="loam")


@pytest.fixture()
def sandy():
    # 高 Ks、低吸力的对照土
    return make_params(5.0, 2.0, 0.30)
