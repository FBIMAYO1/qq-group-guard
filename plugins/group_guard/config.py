"""
插件配置（兼容层）

⚠️ DEPRECATED: 此类已迁移到 group_config.py 的 GroupConfigStore。
   所有群级开关现在按群独立存储于 data/group_config.json。

   旧代码仍可导入 plugin_config，但以下字段已不生效：
   - guard_enabled → 使用 group_config.get(gid).guard_enabled
   - mute_enabled  → 使用 group_config.get(gid).mute_enabled
   - whitelist_users → 使用 storage 的 per-group whitelist

   保留此文件仅用于：
   1. 向后兼容（旧代码 import 不会报错）
   2. enabled_groups 群过滤（全局白名单模式）
   3. recall_message / notify_private 仍为全局设置
"""

from pydantic import BaseModel, ConfigDict


class GroupGuardConfig(BaseModel):
    """群管插件配置 — 兼容层，新代码请使用 group_config.GroupConfigStore"""

    model_config = ConfigDict(frozen=False)

    # ⚠️ DEPRECATED: 由 group_config 按群管理
    guard_enabled: bool = True

    # ⚠️ DEPRECATED: 由 group_config 按群管理
    whitelist_users: list[str] = []

    # 启用的群（为空则所有群都启用）— 仍生效，存于 group_config._global
    enabled_groups: list[str] = []

    # ⚠️ DEPRECATED: 由 group_config 按群管理
    mute_enabled: bool = False

    # 是否尝试撤回违规消息（全局设置）
    recall_message: bool = True

    # 是否在私聊通知被处罚用户（全局设置）
    notify_private: bool = False


# 全局单例 — 兼容层，逐步废弃
plugin_config = GroupGuardConfig()
