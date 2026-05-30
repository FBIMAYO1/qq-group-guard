"""
今日运势模块

企鹅玄学每日一签，大吉到凶六档运势，每人每天一次。

- /抽签 — 抽取今日运势
- /运势 — 同上
"""

import random
import time

from nonebot import on_command, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent


# ============================================================
# 运势分档 — 加权随机（权重总和 100）
# ============================================================
FORTUNE_POOL = [
    ("大吉", 5, [
        "咕咕嘎嘎！南极仙企亲赐大吉！今天做什么都顺，鱼会自己跳进你嘴里。",
        "大吉大利！冰面之下暗流涌动，但你能在暗流中捉到最大的鱼。咕咕嘎嘎！",
        "咕咕嘎嘎！大——吉——！企鹅长老说今天是你全年最旺的一天。",
    ]),
    ("吉", 15, [
        "吉签到手！今天运气不错，企鹅保佑你一切顺利。咕咕嘎嘎！",
        "咕咕嘎嘎！吉星高照，走路都会踩到好运气。",
        "吉！企鹅在冰面上给你画了个好运圈。咕咕嘎嘎！",
    ]),
    ("中吉", 25, [
        "中吉，不好不坏。就像南极的天气——不出太阳但也不下暴风雪。咕咕嘎嘎！",
        "咕咕嘎嘎！比上不足比下有余，企鹅觉得这样挺好。",
        "中吉。平静的一天，冰面稳固，适合发呆。咕咕嘎嘎！",
    ]),
    ("小吉", 25, [
        "小吉。今天会有小确幸，比如抢到最后一个红包。咕咕嘎嘎！",
        "咕咕嘎嘎！微吉，聊胜于无，企鹅给你加块冰。",
        "小吉。企鹅觉得你嘴角会上扬至少一次。咕咕嘎嘎！",
    ]),
    ("末吉", 20, [
        "末吉……今天做事要小心，别像企鹅一样在冰面上滑倒。咕咕嘎嘎！",
        "咕咕嘎嘎！签运平平，建议多喝热水少作死。",
        "末吉。冰面有点滑，但还不至于掉下去。谨慎前行！咕咕嘎嘎！",
    ]),
    ("凶", 10, [
        "凶！今天出门小心，别踩到海豹尾巴。建议宅一天。咕咕嘎嘎！",
        "咕咕嘎嘎……凶签。企鹅建议你今天老实待着，少说话多吃鱼。",
        "大凶之兆！但企鹅在南极见过更糟的天气——暴风雪过后总会天晴的。咕咕嘎嘎！",
    ]),
]


def _draw_fortune() -> tuple[str, str]:
    """加权随机抽取运势"""
    total_weight = sum(w for _, w, _ in FORTUNE_POOL)
    r = random.randint(1, total_weight)

    cumulative = 0
    for level, weight, descriptions in FORTUNE_POOL:
        cumulative += weight
        if r <= cumulative:
            return (level, random.choice(descriptions))

    # 兜底
    return ("中吉", FORTUNE_POOL[2][2][0])


# ============================================================
# 每日追踪 — 每人每群每天一次（内存存储，重启重置）
# ============================================================
_daily_fortunes: dict[str, dict[str, str]] = {}  # group_id -> {user_id -> "YYYY-MM-DD"}


# ============================================================
# 命令：/抽签
# ============================================================
fortune_cmd = on_command("抽签", aliases={"运势", "今日运势"}, priority=5, block=True)


@fortune_cmd.handle()
async def handle_fortune(bot: Bot, event: GroupMessageEvent):
    user_id = str(event.user_id)
    group_id = str(event.group_id)
    today = time.strftime("%Y-%m-%d")

    # 确保群字典存在
    if group_id not in _daily_fortunes:
        _daily_fortunes[group_id] = {}

    # 清理过期记录
    if user_id in _daily_fortunes[group_id] and _daily_fortunes[group_id][user_id] != today:
        del _daily_fortunes[group_id][user_id]

    # 今天已经抽过
    if user_id in _daily_fortunes[group_id]:
        await fortune_cmd.finish(
            f"[CQ:at,qq={user_id}] 咕咕嘎嘎！你今天在本群已经抽过签了。\n"
            f"明天再来吧，企鹅一天只算一次命。"
        )

    # 抽取运势
    level, description = _draw_fortune()
    _daily_fortunes[group_id][user_id] = today

    await fortune_cmd.finish(
        f"[CQ:at,qq={user_id}] 🔮 {level}\n\n{description}"
    )

    logger.info(f"[运势] 群:{group_id} 用户:{user_id} → {level}")
