"""土壤工况档的建档与持久化（职责五）。

按名字把一组土壤参数留存到容器内持久化位置（GA_DATA_DIR，默认 /data），
日后凭名字取回复算。文件采用 JSON、原子写入（同目录临时文件 + os.replace），
进程内用一把锁串行化读写。

服务预置一组壤土（loam）算例：Ks=1.04、ψ=6.0、Δθ=0.434。
由于 λ=ψ·Δθ≈2.60 的吸力项作用，一小时累积入渗量 F 明显大于 Ks·t
（约为后者的 2.9 倍），谁拉起服务都能拿它核对。
另外预置一组粉壤土（silt loam）便于对比。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from typing import Any

from app.config import DATA_DIR, PROFILE_FILE
from app.errors import NotFoundError, ServiceError, ValidationError
from app.services.parameters import SoilParameters, make_params

# 预置工况：谁拉起服务都在（仅在档库首次创建时写入，不覆盖用户同名档）
SEED_PROFILES: dict[str, dict] = {
    "loam": {
        "ks": 1.04,
        "psi": 6.0,
        "dtheta": 0.434,
        "description": (
            "壤土算例（cm/h 单位）。"
            "吸力项使 1 小时累积入渗量明显大于 Ks·t，用于拉起后核对。"
        ),
    },
    "silt_loam": {
        "ks": 0.65,
        "psi": 16.68,
        "dtheta": 0.472,
        "description": "粉壤土算例（cm/h 单位），吸力作用更强，用于趋势对比。",
    },
}

_PROFILE_NAME_RULES = "名字需为 1–64 个非空字符"


class ProfileConflict(ServiceError):
    code = "profile_conflict"
    http_status = 409


def _validate_name(name: Any) -> str:
    if not isinstance(name, str):
        raise ValidationError(f"工况名必须是字符串。{_PROFILE_NAME_RULES}")
    cleaned = name.strip()
    if not (1 <= len(cleaned) <= 64):
        raise ValidationError(f"工况名长度非法。{_PROFILE_NAME_RULES}")
    if any(ch in cleaned for ch in (os.sep, "/", "\x00")):
        raise ValidationError("工况名不得包含路径分隔符")
    return cleaned


class ProfileStore:
    """JSON 文件支撑的命名工况档库。"""

    def __init__(self, data_dir: str = DATA_DIR, filename: str = PROFILE_FILE):
        self.data_dir = data_dir
        self.path = os.path.join(data_dir, filename)
        self._lock = threading.Lock()
        self._profiles: dict[str, dict] = {}
        self._ensure_loaded()

    # ---------- 装载 / 落盘 ----------
    def _ensure_loaded(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        with self._lock:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as fh:
                    self._profiles = json.load(fh)
            else:
                # 首次创建：写入预置算例
                self._profiles = {
                    name: dict(payload) for name, payload in SEED_PROFILES.items()
                }
                self._write_locked()

    def _write_locked(self) -> None:
        # 原子写：同目录临时文件落盘后 replace，进程读到的永远是完整文件
        fd, tmp = tempfile.mkstemp(
            prefix=f".{PROFILE_FILE}.", suffix=".tmp", dir=self.data_dir
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._profiles, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---------- 对外操作 ----------
    def create(
        self,
        name: str,
        ks: Any,
        psi: Any,
        dtheta: Any,
        *,
        description: str | None = None,
        overwrite: bool = False,
    ) -> SoilParameters:
        clean = _validate_name(name)
        params = make_params(ks, psi, dtheta, name=clean)
        with self._lock:
            if clean in self._profiles and not overwrite:
                raise ProfileConflict(f"工况档 {clean!r} 已存在")
            payload: dict[str, Any] = {
                "ks": params.ks,
                "psi": params.psi,
                "dtheta": params.dtheta,
            }
            if description is not None:
                payload["description"] = str(description)
            self._profiles[clean] = payload
            self._write_locked()
        return params

    def get(self, name: str) -> SoilParameters:
        clean = _validate_name(name)
        with self._lock:
            payload = self._profiles.get(clean)
        if payload is None:
            raise NotFoundError(f"工况档 {clean!r} 不存在")
        return make_params(
            payload["ks"], payload["psi"], payload["dtheta"], name=clean
        )

    def get_meta(self, name: str) -> dict:
        clean = _validate_name(name)
        with self._lock:
            payload = self._profiles.get(clean)
        if payload is None:
            raise NotFoundError(f"工况档 {clean!r} 不存在")
        return {"name": clean, **payload}

    def list(self) -> list[dict]:
        with self._lock:
            return [
                {"name": n, **{k: v for k, v in p.items()}}
                for n, p in sorted(self._profiles.items())
            ]

    def delete(self, name: str) -> None:
        clean = _validate_name(name)
        with self._lock:
            if clean not in self._profiles:
                raise NotFoundError(f"工况档 {clean!r} 不存在")
            del self._profiles[clean]
            self._write_locked()
