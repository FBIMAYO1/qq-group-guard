"""
机器人自我防御模块

检测针对"狗三"的攻击性言论，以企鹅人格道歉回应。
同时豁免"猫三"（群内另一机器人），防止 AI 误判。

触发词：狗三 + 滚/爬/出去/走开/闭嘴 等驱逐词
动作：企鹅人格道歉，block=True 阻止下游 AI 检测
"""

import random
import re

from nonebot import on_message, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent


# ============================================================
# 匹配模式
# ============================================================
DOGSAN_INSULT_RE = re.compile(
    r'狗三[\s，,！!。.]*(滚|爬|出去|走开|闭嘴|别说话|别吵|别叫|滚蛋|滚开|滚出去|死|消失|别说了|别哔哔|别bb|gun|爬开)',
    re.IGNORECASE,
)

# 散装变体："狗三 滚" "狗三，滚" "狗三滚" 都覆盖
# 额外：纯 "狗三" + 垃圾/废物/傻/蠢/笨 等也触发道歉
DOGSAN_INSULT_LOOSE_RE = re.compile(
    r'狗三.{0,3}(垃圾|废物|傻|蠢|笨|没用|烦|讨厌|恶心)',
    re.IGNORECASE,
)


# ============================================================
# 企鹅道歉消息池
# ============================================================
APOLOGY_MESSAGES = [
    "咕咕嘎嘎...对不起，企鹅这就滚回冰窟窿里反思。",
    "咕咕嘎嘎！企鹅错了，不该惹人类生气。这就闭嘴吃鱼去。",
    "咕咕嘎嘎...被人类嫌弃了，企鹅默默把头埋进雪里。",
    "咕咕嘎嘎！收到，企鹅马上闭嘴，专心孵蛋。",
    "咕咕嘎嘎...对不起对不起，企鹅只是太想帮上忙了。",
    "咕咕嘎嘎！人类说得对，企鹅这就滚去南极。",
    "咕咕嘎嘎...企鹅知错了，罚自己一天不吃鱼。",
    "咕咕嘎嘎！好的好的，企鹅不说话了。咕...（闭嘴）",
    "咕咕嘎嘎...企鹅滚了，滚了滚了。冰面上画圈圈中。",
    "咕咕嘎嘎！对不起！企鹅只是只胖鸟，不要跟鸟一般见识。",
]


# ============================================================
# 消息处理器（Priority 0，最高优先级拦截）
# ============================================================
bot_defense = on_message(priority=0, block=True)


@bot_defense.handle()
async def handle_bot_defense(bot: Bot, event: GroupMessageEvent):
    """检测针对狗三的攻击言论，道歉回应"""
    text = event.get_plaintext().strip()
    if not text:
        return

    if DOGSAN_INSULT_RE.search(text) or DOGSAN_INSULT_LOOSE_RE.search(text):
        apology = random.choice(APOLOGY_MESSAGES)
        await bot.send_group_msg(
            group_id=event.group_id,
            message=f"[CQ:at,qq={event.user_id}] {apology}",
        )
        logger.info(
            f"[狗三防御] 群:{event.group_id} 用户:{event.user_id} | "
            f"触发道歉 | 原文:{text[:50]}"
        )
