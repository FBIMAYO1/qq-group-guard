"""
插件配置
"""

from pydantic import BaseModel


class GroupGuardConfig(BaseModel):
    """群管插件配置"""

    # 是否启用（可以通过配置临时关闭）
    guard_enabled: bool = True

    # 白名单用户（不受规则约束的QQ号）
    whitelist_users: list[str] = []

    # 启用的群（为空则所有群都启用）
    enabled_groups: list[str] = []

    # 是否尝试撤回违规消息
    recall_message: bool = True

    # 是否在私聊通知被处罚用户
    notify_private: bool = False
