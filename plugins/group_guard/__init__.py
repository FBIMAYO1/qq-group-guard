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

import re
import random
import asyncio
from .checker import CheckResult
from .punisher import get_punisher
from .ai_checker import get_ai_checker
from .storage import get_storage
from .config import plugin_config
from .group_config import get_group_config

# ============================================================
# 关键词预检层 — 无需 AI 的直接命中的违规模式
# 在 AI 调用之前做快速匹配，节省 token 并确保不漏判
# ============================================================
_KEYWORD_VIOLATIONS: list[tuple[re.Pattern, str, str]] = [
    # (正则, 类别, 原因说明)
    # === R18 色情 ===
    (re.compile(r'自慰|zw\b'), "R18", "直接提及自慰"),
    (re.compile(r'扫福瑞|sofree|骚福瑞|sao.*福瑞'), "R18", "涉黄内容"),
    (re.compile(r'口交|口\s*交|kj\b'), "R18", "直接提及口交"),
    (re.compile(r'抠你的|扣你的'), "R18", "涉黄暗示"),
    (re.compile(r'颜射|颜\s*射'), "R18", "直接提及颜射"),
    (re.compile(r'高潮|高\s*潮|gc\b'), "R18", "直接提及高潮"),
    (re.compile(r'坐上来自己动|坐上来.*动'), "R18", "涉黄内容"),
    # === 辱骂 ===
    (re.compile(r'操你|草你|艹你|曹你|肏你'), "辱骂", "直接辱骂"),
    (re.compile(r'傻逼|sb\b|5b\b|傻福|煞笔|沙比|纱碧|傻杯'), "辱骂", "直接辱骂"),
    (re.compile(r'cnm|cnmb|操你妈|草你妈|艹你妈'), "辱骂", "直接辱骂"),
    (re.compile(r'nmsl|你妈死了|你冯死了|你🐴死了'), "辱骂", "直接辱骂"),
]

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

# 导入掉线通知模块（注册 bot_offline 事件监听）
from . import offline_notify  # noqa: F401, E402

# 导入图片违禁检测模块（注册视觉模型审核）
from . import image_checker  # noqa: F401, E402

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
# 辅助函数：图片违规检测
# ============================================================

def _has_image_segments(event: GroupMessageEvent) -> bool:
    """检查消息是否包含图片段"""
    for seg in event.message:
        if seg.type == "image":
            return True
    return False


async def _check_group_images(event: GroupMessageEvent) -> CheckResult | None:
    """检查群消息中的图片是否违规（含开关检查）"""
    gid = str(event.group_id)
    gcfg = get_group_config()
    if not gcfg.get(gid).image_check_enabled:
        return None
    if not _has_image_segments(event):
        return None
    return await image_checker.check_images(event)


# ============================================================
# 消息监听器
# ============================================================

group_guard = on_message(
    rule=Rule(is_group_msg_and_not_whitelisted),
    priority=1,
    block=False,
)


async def _human_delay():
    """随机短暂延迟，避免回复过快被QQ识别为机器人"""
    await asyncio.sleep(random.uniform(0.3, 1.5))


@group_guard.handle()
async def handle_group_message(bot: Bot, event: GroupMessageEvent):
    """处理群消息 — 关键词预检 + AI 语义判断"""

    text = event.get_plaintext()

    # 图片违禁检测（有图片时始终检查，get_plaintext() 对图片返回 "[图片]" 不是空串）
    image_result = await _check_group_images(event)
    if image_result:
        punisher = get_punisher()
        punish_result = await punisher.execute(bot, event, image_result)
        await _human_delay()
        await bot.send_group_msg(
            group_id=event.group_id,
            message=punish_result.message,
        )
        logger.info(
            f"[群管] 图片处罚完成 | "
            f"动作:{punish_result.action} | "
            f"第{punish_result.violation_count}次违规"
        )
        return

    if not text:
        return

    text_stripped = text.strip()

    # ---- 关键词预检层：无需 AI 的直接命中 ----
    keyword_match = False
    for pattern, category, reason in _KEYWORD_VIOLATIONS:
        if pattern.search(text_stripped):
            keyword_match = True
            result = CheckResult(
                is_violation=True,
                category=category,
                category_name=category,
                matched_word=f"[关键词] {reason}",
                original_text=text,
            )
            logger.info(
                f"[群管] 关键词命中 | "
                f"群:{event.group_id} | "
                f"用户:{event.user_id} | "
                f"类别:{category} | "
                f"原因:{reason} | "
                f"文本:{text[:40]}"
            )

            punisher = get_punisher()
            punish_result = await punisher.execute(bot, event, result)
            await _human_delay()
            await bot.send_group_msg(
                group_id=event.group_id,
                message=punish_result.message,
            )
            logger.info(
                f"[群管] 处罚完成 | "
                f"动作:{punish_result.action} | "
                f"第{punish_result.violation_count}次违规"
            )
            break  # 命中一个就停止，避免重复处罚

    if keyword_match:
        return  # 已由关键词处理，不走 AI

    # 已知无害的拼音缩写/网络用语（跳过AI，避免误判）
    # "zdjd"=真的假的 "yysy"=有一说一 "nsdd"=你说得对 "xswl"=笑死我了 等
    _SAFE_ABBREVS = {
        "zdjd", "yysy", "nsdd", "xswl", "awsl", "yyds", "dbq",
        "srds", "u1s1", "tql", "pyq", "bhys", "nbsl", "zqsg",
        "pljj", "plmm", "xjj", "xgg", "gkd", "bdjw", "lgld",
        "y1s1", "jjww", "ybb", "wl", "ky", "bp", "blx",
    }
    if text_stripped.lower() in _SAFE_ABBREVS:
        return

    # 太短的消息跳过（"嗯""好的"之类不用 AI）
    if len(text_stripped) < 3:
        return

    # AI 语义判断
    ai_checker = get_ai_checker()
    if not ai_checker.is_available():
        return

    ai_result = await ai_checker.check(text)

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

    await _human_delay()
    await bot.send_group_msg(
        group_id=event.group_id,
        message=punish_result.message,
    )

    logger.info(
        f"[群管] 处罚完成 | "
        f"动作:{punish_result.action} | "
        f"第{punish_result.violation_count}次违规"
    )
