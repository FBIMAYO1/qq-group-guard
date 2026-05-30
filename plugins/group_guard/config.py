"""
插件配置
"""

from pydantic import BaseModel, ConfigDict


class GroupGuardConfig(BaseModel):
    """群管插件配置 — 全局单例，通过 plugin_config 引用"""

    model_config = ConfigDict(frozen=False)

    # 是否启用（可以通过 /群管开关 临时关闭）
    guard_enabled: bool = True

    # 白名单用户（不受规则约束的QQ号）
    whitelist_users: list[str] = []

    # 启用的群（为空则所有群都启用）
    enabled_groups: list[str] = []

    # 是否开启违规禁言（默认关闭，仅警告不禁言）
    mute_enabled: bool = False

    # 是否尝试撤回违规消息
    recall_message: bool = True

    # 是否在私聊通知被处罚用户
    notify_private: bool = False


# 全局单例 — __init__.py 和 admin_cmd.py 共享此实例
plugin_config = GroupGuardConfig()
