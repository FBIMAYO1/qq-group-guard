"""
广告检测模块

纯正则检测，不消耗 AI token。检测广告关键词（扫码/加V/日入/代理等 20+ 词）。

动作：尝试撤回 + @警告
"""

import re

from nonebot import on_message, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from .config import plugin_config
from .group_config import get_group_config
from .storage import get_storage


# ============================================================
# 正则模式
# ============================================================

# 广告关键词
AD_KEYWORD_PATTERN = re.compile(
    r'(扫码|加V|加微|加Q|日入|日赚|代理|白菜价|免费送|'
    r'点击领取|限时优惠|内部价|招代理|兼职招聘|'
    r'加群|加我|私聊|代发|接单|秒杀|拼团|返利|'
    r'刷单|好评返现|亏本甩卖|清仓|绝版|'
    r'注册送|推广|引流|变现|躺赚|网赚)',
    re.IGNORECASE,
)


# ============================================================
# 消息处理器
# ============================================================
ad_detector = on_message(priority=3, block=False)


@ad_detector.handle()
async def handle_ad(bot: Bot, event: GroupMessageEvent):
    """检测广告关键词"""
    gid = str(event.group_id)
    uid = str(event.user_id)

    # 检查功能开关
    gcfg = get_group_config()
    if not gcfg.get(gid).ad_enabled:
        return

    # 跳过管理员和群主
    if event.sender.role in ("admin", "owner"):
        return

    # 跳过白名单用户
    if uid in plugin_config.whitelist_users:
        return
    storage = get_storage()
    if storage.is_whitelisted(gid, uid):
        return

    text = event.get_plaintext().strip()
    if not text:
        return

    # 检测广告关键词
    if not AD_KEYWORD_PATTERN.search(text):
        return

    match_reason = "疑似广告"

    # 尝试撤回消息
    try:
        await bot.delete_msg(message_id=event.message_id)
    except Exception:
        pass

    # 发送警告
    await bot.send_group_msg(
        group_id=event.group_id,
        message=(
            f"[CQ:at,qq={uid}] 检测到{match_reason}，"
            f"请勿在群内发送广告内容。"
        ),
    )

    logger.info(
        f"[广告检测] 群:{gid} 用户:{uid} | "
        f"类型:{match_reason} | 原文:{text[:50]}"
    )
