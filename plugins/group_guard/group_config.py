"""
群配置存储 — 每个群独立配置，持久化到 JSON 文件

替代原有的全局单例 plugin_config，实现真正的多群管理。
每个群的开关互不影响，群管理员只能管理自己群的配置。

数据文件：data/group_config.json

使用方式：
    from .group_config import get_group_config
    gcfg = get_group_config()
    config = gcfg.get(str(group_id))
    if config.guard_enabled:
        ...
"""

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional

from nonebot import logger


# ============================================================
# 数据目录
# ============================================================
DATA_DIR = Path(__file__).parent / "data"
CONFIG_FILE = DATA_DIR / "group_config.json"


# ============================================================
# 配置数据类
# ============================================================

@dataclass
class GroupConfig:
    """单个群的配置"""

    # ---- AI 检测 ----
    guard_enabled: bool = True          # AI 违规检测
    mute_enabled: bool = False          # 自动禁言（默认关闭，仅警告）

    # ---- 功能开关 ----
    welcome_enabled: bool = True        # 入群欢迎
    morning_brief_enabled: bool = True  # 早安短报
    brainwash_enabled: bool = True      # 凑企鹅洗脑
    comfort_enabled: bool = True        # 情绪安慰
    penguin_chat_enabled: bool = True   # @企鹅聊天
    spam_enabled: bool = True           # 刷屏检测
    ad_enabled: bool = True             # 广告/链接拦截

    # ---- 元数据 ----
    joined_at: str = ""                 # 入群时间 ISO 格式
    updated_at: str = ""                # 最后修改时间


@dataclass
class GlobalDefaults:
    """全局默认值 — 新群从此继承初始配置，超级用户可修改"""

    default_guard_enabled: bool = True
    default_mute_enabled: bool = False
    default_welcome_enabled: bool = True
    default_morning_brief_enabled: bool = True
    default_brainwash_enabled: bool = True
    default_comfort_enabled: bool = True
    default_penguin_chat_enabled: bool = True
    default_spam_enabled: bool = True
    default_ad_enabled: bool = True
    enabled_groups: list[str] = field(default_factory=list)  # 群过滤白名单


# ============================================================
# 配置存储
# ============================================================

class GroupConfigStore:
    """群配置持久化存储 — 单例"""

    GLOBAL_KEY = "_global"

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._data: dict = self._load()
        self._ensure_global_defaults()

    # ---- 文件 I/O ----

    def _load(self) -> dict:
        """从 JSON 文件加载"""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"[群配置] 加载失败: {e}，使用空配置")
                return {}
        return {}

    def _save(self):
        """保存到 JSON 文件"""
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except IOError as e:
            logger.error(f"[群配置] 保存失败: {e}")

    def _ensure_global_defaults(self):
        """确保全局默认值存在"""
        if self.GLOBAL_KEY not in self._data:
            self._data[self.GLOBAL_KEY] = asdict(GlobalDefaults())
            self._save()

    # ---- 群配置 CRUD ----

    def get(self, group_id: str) -> GroupConfig:
        """获取某群配置，不存在则用默认值初始化"""
        if group_id == self.GLOBAL_KEY:
            raise ValueError(f"禁止使用保留键 '{self.GLOBAL_KEY}' 作为群号")

        if group_id not in self._data:
            return self.init_group(group_id)

        raw = self._data[group_id]
        return GroupConfig(**{k: v for k, v in raw.items()
                              if k in GroupConfig.__dataclass_fields__})

    def init_group(self, group_id: str) -> GroupConfig:
        """初始化新群配置（从全局默认值继承）"""
        defaults = self.get_defaults()
        now = time.strftime("%Y-%m-%dT%H:%M:%S")

        config = GroupConfig(
            guard_enabled=defaults.default_guard_enabled,
            mute_enabled=defaults.default_mute_enabled,
            welcome_enabled=defaults.default_welcome_enabled,
            morning_brief_enabled=defaults.default_morning_brief_enabled,
            brainwash_enabled=defaults.default_brainwash_enabled,
            comfort_enabled=defaults.default_comfort_enabled,
            penguin_chat_enabled=defaults.default_penguin_chat_enabled,
            spam_enabled=defaults.default_spam_enabled,
            ad_enabled=defaults.default_ad_enabled,
            joined_at=now,
            updated_at=now,
        )

        self._data[group_id] = asdict(config)
        self._save()
        logger.info(f"[群配置] + 新群 {group_id} 已初始化")
        return config

    def set(self, group_id: str, key: str, value) -> bool:
        """修改某群某个配置项，自动持久化

        Returns:
            True 如果值确实改变了，False 如果值未变
        """
        if group_id not in self._data:
            self.init_group(group_id)

        if key not in GroupConfig.__dataclass_fields__:
            logger.warning(f"[群配置] 未知的配置键: {key}")
            return False

        old_value = self._data[group_id].get(key)
        if old_value == value:
            return False

        self._data[group_id][key] = value
        self._data[group_id]["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._save()
        return True

    def remove_group(self, group_id: str):
        """移除某群配置（退群时调用）"""
        if group_id in self._data:
            del self._data[group_id]
            self._save()
            logger.info(f"[群配置] - 群 {group_id} 配置已移除")

    def list_groups(self) -> list[str]:
        """列出所有已配置的群号"""
        return [k for k in self._data.keys() if k != self.GLOBAL_KEY]

    # ---- 全局默认值 ----

    def get_defaults(self) -> GlobalDefaults:
        """获取全局默认值"""
        raw = self._data.get(self.GLOBAL_KEY, {})
        return GlobalDefaults(**{k: v for k, v in raw.items()
                                  if k in GlobalDefaults.__dataclass_fields__})

    def set_default(self, key: str, value) -> bool:
        """修改全局默认值

        Returns:
            True 如果值确实改变了
        """
        if key not in GlobalDefaults.__dataclass_fields__:
            logger.warning(f"[群配置] 未知的默认值键: {key}")
            return False

        if self.GLOBAL_KEY not in self._data:
            self._ensure_global_defaults()

        old_value = self._data[self.GLOBAL_KEY].get(key)
        if old_value == value:
            return False

        self._data[self.GLOBAL_KEY][key] = value
        self._save()
        return True

    def get_enabled_groups(self) -> list[str]:
        """获取群过滤白名单（为空 = 所有群都启用）"""
        defaults = self.get_defaults()
        return defaults.enabled_groups


# ============================================================
# 全局单例
# ============================================================
_group_config: Optional[GroupConfigStore] = None


def get_group_config() -> GroupConfigStore:
    """获取群配置存储单例"""
    global _group_config
    if _group_config is None:
        _group_config = GroupConfigStore()
    return _group_config


# ============================================================
# 兼容旧代码的工具函数
# ============================================================

def is_guard_enabled(group_id: str) -> bool:
    """快速查询某群是否开启了 AI 检测"""
    return get_group_config().get(group_id).guard_enabled


def is_mute_enabled(group_id: str) -> bool:
    """快速查询某群是否开启了自动禁言"""
    return get_group_config().get(group_id).mute_enabled
