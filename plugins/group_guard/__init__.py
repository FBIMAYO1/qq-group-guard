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
from .config import plugin_config
from .group_config import get_group_config

# 加载配置（config.py 中的全局单例，兼容层）

# 导入群配置存储（多群管理核心）
# group_config 在 group_lifecycle 之前导入，确保单例已创建

# 导入群生命周期管理（注册入群/退群/启动同步）
from . import group_lifecycle  # noqa: F401, E402

# 导入管理命令（注册 /帮助 /查询 等命令）
from . import admin_cmd  # noqa: F401, E402

# 导入企鹅角色扮演（注册 @机器人 趣味聊天）
from . import penguin_chat  # noqa: F401, E402

# 导入机器人自我防御（注册狗三道歉 + 猫三豁免）
from . import bot_defense  # noqa: F401, E402

# 导入洗脑模块（注册定时洗脑任务）
from . import brainwash  # noqa: F401, E402

# 导入情绪安慰模块（注册负面情绪检测）
from . import comfort  # noqa: F401, E402

# 导入早安短报模块（注册每天早上8:00定时任务）
from . import morning_brief  # noqa: F401, E402

# 导入签到打卡模块（注册 /签到 /签到排行 命令）
from . import checkin  # noqa: F401, E402

# 导入今日运势模块（注册 /抽签 /运势 命令）
from . import fortune  # noqa: F401, E402

# 导入入群欢迎模块（注册新成员入群欢迎通知）
from . import welcome  # noqa: F401, E402

# 导入活跃排行榜模块（注册消息收集器 + /活跃榜 命令）
from . import activity_rank  # noqa: F401, E402

# 导入刷屏检测模块（注册刷屏消息监听器）
from . import spam_detector  # noqa: F401, E402

# 导入广告/链接检测模块（注册广告消息监听器）
from . import ad_detector  # noqa: F401, E402


# ============================================================
# 规则：只处理群消息，且发送者不在白名单中
# ============================================================

async def is_group_msg_and_not_whitelisted(event: GroupMessageEvent) -> bool:
    """判断是否需要检测该消息（按群独立配置）"""
    gid = str(event.group_id)

    # 按群独立的 AI 检测开关（替代旧的全局 plugin_config.guard_enabled）
    gcfg = get_group_config().get(gid)
    if not gcfg.guard_enabled:
        return False

    # 全局白名单（兼容层）
    if str(event.user_id) in plugin_config.whitelist_users:
        return False

    # 按群持久化白名单检查
    storage = get_storage()
    if storage.is_whitelisted(gid, str(event.user_id)):
        return False

    # 群过滤白名单（来自 group_config._global.enabled_groups）
    enabled_groups = get_group_config().get_enabled_groups()
    if enabled_groups:
        if gid not in enabled_groups:
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
        f"置信度:{ai_result.confidence:.2f} | "
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
