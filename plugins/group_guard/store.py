"""
统一 JSON 持久化基类 — 所有按 JSON 文件存储的模块共用。

替代各模块各自手写的 _load / _save 样板，集中解决三件事：
  1. 原子写入：先写临时文件再 os.replace，进程中途崩溃也不会损坏数据文件
  2. 损坏自愈：JSON 解析失败时备份损坏文件（.corrupt）而不是静默清空
  3. 写入加锁：threading.RLock 保护文件写，兼容线程池里触发的保存

子类只需实现领域方法，调用 self.save() 落盘即可。
数据统一存放在 data/ 目录（与历史路径一致，零迁移）。
"""

import json
import os
import threading
import time
from pathlib import Path

from nonebot import logger


# 所有数据文件的统一根目录（保持与历史一致：plugins/group_guard/data/）
DATA_DIR = Path(__file__).parent / "data"


class JsonStore:
    """JSON 文件持久化基类。

    子类用法：
        class FooStore(JsonStore):
            def __init__(self):
                super().__init__("foo.json")
            def do_something(self):
                self._data[...] = ...
                self.save()
    """

    def __init__(self, filename: str):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._path: Path = DATA_DIR / filename
        self._lock = threading.RLock()
        self._data: dict = self._load()

    # ---- 文件 I/O ----

    def _load(self) -> dict:
        """读取数据文件。损坏时备份为 .corrupt 并返回空字典，避免丢数据。"""
        if not self._path.exists():
            return {}
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            # 不静默清空：把损坏文件备份下来，方便事后人工恢复
            backup = self._path.with_suffix(
                self._path.suffix + f".corrupt.{int(time.time())}"
            )
            try:
                os.replace(self._path, backup)
                logger.error(
                    f"[存储] ❌ {self._path.name} 解析失败({e})，"
                    f"已备份为 {backup.name}，本次以空数据启动"
                )
            except OSError:
                logger.error(f"[存储] ❌ {self._path.name} 解析失败且备份失败: {e}")
            return {}

    def save(self):
        """原子保存：写临时文件 → os.replace 覆盖，崩溃也不损坏原文件。"""
        with self._lock:
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self._path)  # 同盘原子替换
            except OSError as e:
                logger.error(f"[存储] ❌ 保存 {self._path.name} 失败: {e}")
                # 清理可能残留的临时文件
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
