"""工况建档持久化与预置壤土算例测试。"""
from __future__ import annotations

import json

import pytest

from app.errors import NotFoundError, ValidationError
from app.services.persistence import SEED_PROFILES, ProfileStore


def test_seed_loam_present_and_one_hour_exceeds_kst(tmp_path):
    store = ProfileStore(data_dir=str(tmp_path))
    loam = store.get("loam")
    from app.services.solver import solve_f

    F = solve_f(loam.ks * 1.0, loam.suction_storage)
    assert F > 1.5 * loam.ks  # 吸力项使 1 小时 F 明显大于 Ks·t
    assert "loam" in SEED_PROFILES


def test_seed_only_on_first_creation(tmp_path):
    s1 = ProfileStore(data_dir=str(tmp_path))
    s1.create("clay_test", 0.2, 30.0, 0.4)
    # 重新打开：预置算例不应覆盖已有档库，新档仍在
    s2 = ProfileStore(data_dir=str(tmp_path))
    p = s2.get("clay_test")
    assert p.ks == 0.2
    assert s2.get("loam").ks == 1.04


def test_create_get_list_delete(tmp_path):
    store = ProfileStore(data_dir=str(tmp_path))
    store.create("my_soil", 2.0, 10.0, 0.35, description="试验土")
    names = [m["name"] for m in store.list()]
    assert "my_soil" in names
    meta = store.get_meta("my_soil")
    assert meta["description"] == "试验土"
    store.delete("my_soil")
    with pytest.raises(NotFoundError):
        store.get("my_soil")


def test_duplicate_conflict_and_overwrite(tmp_path):
    store = ProfileStore(data_dir=str(tmp_path))
    store.create("dup", 1.0, 1.0, 0.2)
    with pytest.raises(Exception):
        store.create("dup", 2.0, 1.0, 0.2)
    store.create("dup", 2.0, 1.0, 0.2, overwrite=True)
    assert store.get("dup").ks == 2.0


def test_persistence_survives_reopen(tmp_path):
    d = str(tmp_path)
    ProfileStore(data_dir=d).create("persist_me", 0.9, 7.0, 0.3)
    reopened = ProfileStore(data_dir=d)
    assert reopened.get("persist_me").psi == 7.0


def test_bad_name(tmp_path):
    store = ProfileStore(data_dir=str(tmp_path))
    with pytest.raises(ValidationError):
        store.create("../escape", 1, 1, 0.2)
    with pytest.raises(NotFoundError):
        store.get("no_such_profile")


def test_invalid_profile_payload_rejected_before_write(tmp_path):
    store = ProfileStore(data_dir=str(tmp_path))
    before = set(m["name"] for m in store.list())
    with pytest.raises(ValidationError):
        store.create("bad", -1, 1, 0.2)
    after = set(m["name"] for m in store.list())
    assert before == after  # 校验失败不留残档
