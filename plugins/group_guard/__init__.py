"""
群管机器人 - 主插件入口

纯 AI 语义判断（DeepSeek），不做关键词匹配。
每条群消息直接交给 AI 判断是否违规。
"""

from nonebot import on_message, logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
)
from nonebot.rule import Rule

from .checker import CheckResult
from .punisher import get_punisher
from .ai_checker import get_ai_checker
from .storage import get_storage
from .config import GroupGuardConfig

# 加载配置
plugin_config = GroupGuardConfig()

# 导入管理命令（注册 /帮助 /查询 等命令）
from . import admin_cmd  # noqa: F401, E402


# ============================================================
# 规则：只处理群消息，且发送者不在白名单中
# ============================================================

async def is_group_msg_and_not_whitelisted(event: GroupMessageEvent) -> bool:
    """判断是否需要检测该消息"""
    if not plugin_config.guard_enabled:
        return False

    if str(event.user_id) in plugin_config.whitelist_users:
        return False

    # 持久化白名单检查
    storage = get_storage()
    if storage.is_whitelisted(str(event.group_id), str(event.user_id)):
        return False

    if plugin_config.enabled_groups:
        if str(event.group_id) not in plugin_config.enabled_groups:
            return False

    # 跳过管理员和群主
    if event.sender.role in ("admin", "owner"):
        return False

    return True


# ============================================================
# 消息监听器
# ============================================================

group_guard = on_message(
    rule=Rule(is_group_msg_and_not_whitelisted),
    priority=1,
    block=False,
)


@group_guard.handle()
async def handle_group_message(bot: Bot, event: GroupMessageEvent):
    """处理群消息 — 纯 AI 检测"""

    text = event.get_plaintext()
    if not text:
        return

    # 太短的消息跳过（"嗯""好的"之类不用 AI）
    if len(text.strip()) < 3:
        return

    # AI 语义判断
    ai_checker = get_ai_checker()
    if not ai_checker.is_available():
        return

    ai_result = ai_checker.check(text)

    if not ai_result.is_violation:
        return

    # 构造 CheckResult
    result = CheckResult(
        is_violation=True,
        category=ai_result.category or "违规",
        category_name=ai_result.category or "违规",
        matched_word=f"[AI] {ai_result.reason}",
        original_text=text,
    )

    logger.info(
        f"[群管] AI违规 | "
        f"群:{event.group_id} | "
        f"用户:{event.user_id} | "
        f"类别:{ai_result.category} | "
        f"原因:{ai_result.reason} | "
        f"耗时:{ai_result.latency_seconds:.1f}s"
    )

    punisher = get_punisher()
    punish_result = await punisher.execute(bot, event, result)

    await bot.send_group_msg(
        group_id=event.group_id,
        message=punish_result.message,
    )

    logger.info(
        f"[群管] 处罚完成 | "
        f"动作:{punish_result.action} | "
        f"第{punish_result.violation_count}次违规"
    )
