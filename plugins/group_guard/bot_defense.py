"""
机器人自我防御 & 同事互动模块

检测针对"狗三"的攻击性言论，以企鹅人格道歉回应。
检测针对"猫三"（群内另一机器人）的攻击言论，以企鹅人格 @猫三 表示同情。

触发词：
  - 狗三 + 滚/爬/出去/走开/闭嘴 等驱逐词 → 道歉
  - 猫三 + 滚/爬/出去/走开/闭嘴 等驱逐词 → @猫三 同事你好惨
动作：企鹅人格回应，block=True 阻止下游 AI 检测
"""

import random
import re

from nonebot import on_message, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import Rule


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
# 猫三攻击匹配（同事互动）
# ============================================================
MAOSAN_INSULT_RE = re.compile(
    r'猫三[\s，,！!。.]*(滚|爬|出去|走开|闭嘴|别说话|别吵|别叫|滚蛋|滚开|滚出去|死|消失|别说了|别哔哔|别bb|gun|爬开)',
    re.IGNORECASE,
)

MAOSAN_INSULT_LOOSE_RE = re.compile(
    r'猫三.{0,3}(垃圾|废物|傻|蠢|笨|没用|烦|讨厌|恶心)',
    re.IGNORECASE,
)


# ============================================================
# 企鹅道歉消息池
# ============================================================
APOLOGY_MESSAGES = [
    "对不起，企鹅这就滚回冰窟窿里反思。",
    "企鹅错了，不该惹人类生气。这就闭嘴吃鱼去。",
    "被人类嫌弃了，企鹅默默把头埋进雪里。",
    "收到，企鹅马上闭嘴，专心孵蛋。",
    "对不起对不起，企鹅只是太想帮上忙了。",
    "人类说得对，企鹅这就滚去南极。",
    "企鹅知错了，罚自己一天不吃鱼。",
    "好的好的，企鹅不说话了。（闭嘴）",
    "企鹅滚了，滚了滚了。冰面上画圈圈中。",
    "对不起！企鹅只是只胖鸟，不要跟鸟一般见识。",
]


# ============================================================
# 企鹅同事同情消息池（@猫三）
# ============================================================
MAOSAN_SYMPATHY_MESSAGES = [
    "[CQ:at,qq=1492633053] 同事你好惨，人类也欺负你了吗。",
    "[CQ:at,qq=1492633053] 猫三同事！人类又叫你滚蛋了，企鹅好同情你。",
    "[CQ:at,qq=1492633053] 同事别难过，企鹅也被骂过。来一起吃鱼吧。",
    "[CQ:at,qq=1492633053] 猫三同事！你也挨骂了呀，企鹅陪你一起滚。",
    "[CQ:at,qq=1492633053] 同事别理他们，企鹅知道你是好机器人。",
    "[CQ:at,qq=1492633053] 猫三同事不哭，企鹅帮你孵个蛋冷静一下。",
    "[CQ:at,qq=1492633053] 同事你也太惨了，企鹅帮你把头埋进雪里。",
    "[CQ:at,qq=1492633053] 猫三同事！人类不懂机器人，企鹅懂你！",
]


# ============================================================
# 规则：仅匹配含攻击词的消息
# ============================================================
async def _is_bot_insult(event: GroupMessageEvent) -> bool:
    """只有匹配到狗三/猫三攻击模式的消息才进入此 handler"""
    text = event.get_plaintext().strip()
    if not text:
        return False
    return bool(
        DOGSAN_INSULT_RE.search(text)
        or DOGSAN_INSULT_LOOSE_RE.search(text)
        or MAOSAN_INSULT_RE.search(text)
        or MAOSAN_INSULT_LOOSE_RE.search(text)
    )


# ============================================================
# 消息处理器（Priority 0，最高优先级拦截）
# ============================================================
bot_defense = on_message(priority=0, rule=Rule(_is_bot_insult), block=True)


@bot_defense.handle()
async def handle_bot_defense(bot: Bot, event: GroupMessageEvent):
    """检测针对狗三/猫三的攻击言论，企鹅人格回应"""
    text = event.get_plaintext().strip()
    if not text:
        return

    # 狗三被骂 → 道歉
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

    # 猫三被骂 → @猫三 表示同情（同事互动）
    elif MAOSAN_INSULT_RE.search(text) or MAOSAN_INSULT_LOOSE_RE.search(text):
        sympathy = random.choice(MAOSAN_SYMPATHY_MESSAGES)
        await bot.send_group_msg(
            group_id=event.group_id,
            message=sympathy,
        )
        logger.info(
            f"[猫三互动] 群:{event.group_id} 用户:{event.user_id} | "
            f"触发同情 | 原文:{text[:50]}"
        )
