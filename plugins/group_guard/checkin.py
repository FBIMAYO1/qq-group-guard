"""
签到打卡模块

每日签到领企鹅奖励，连续签到解锁里程碑彩蛋。
支持签到排行榜，查看谁是最坚持的人类。

- /签到 — 每日签到
- /签到排行 — 连续签到排行榜
"""

import random
import re
import time
from datetime import datetime, timedelta

from nonebot import on_command, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from .store import JsonStore


# ============================================================
# 持久化存储
# ============================================================
DATA_FILE = "checkin.json"


class CheckinStorage(JsonStore):
    """签到记录存储"""

    def __init__(self):
        super().__init__(DATA_FILE)

    def _ensure_group(self, group_id: str):
        """确保群数据结构存在"""
        if group_id not in self._data:
            self._data[group_id] = {}

    def checkin(self, group_id: str, user_id: str) -> tuple[int, int, bool]:
        """
        执行签到（按群隔离）

        Returns:
            (streak, total, is_first_today)
        """
        today = time.strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        self._ensure_group(group_id)

        if user_id not in self._data[group_id]:
            self._data[group_id][user_id] = {"last_date": "", "streak": 0, "total": 0}

        record = self._data[group_id][user_id]

        # 今天已经签过
        if record["last_date"] == today:
            return (record["streak"], record["total"], False)

        # 连续判断
        if record["last_date"] == yesterday:
            record["streak"] += 1
        else:
            record["streak"] = 1

        record["last_date"] = today
        record["total"] += 1
        self.save()

        return (record["streak"], record["total"], True)

    def get_top_streaks(self, group_id: str, n: int = 10) -> list[tuple[str, int, int]]:
        """获取某群连续签到 TOP N: [(user_id, streak, total), ...]"""
        self._ensure_group(group_id)
        items = [
            (uid, r["streak"], r["total"])
            for uid, r in self._data.get(group_id, {}).items()
        ]
        items.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return items[:n]


# 全局单例
_checkin_storage: CheckinStorage | None = None


def get_checkin_storage() -> CheckinStorage:
    global _checkin_storage
    if _checkin_storage is None:
        _checkin_storage = CheckinStorage()
    return _checkin_storage


# ============================================================
# 奖励消息池
# ============================================================
STREAK_REWARDS = {
    7: [
        "连续7天签到，你比其他人类勤快一点点。",
        "一周签到达成！企鹅给你记在小本本上了。",
        "7天领到的冰砖数量：1块。不够再说。",
    ],
    30: [
        "整整一个月签到，南极冰面都被你踩薄了。",
        "30天全勤！凑企鹅表示勉强认可你。",
        "一个月没断签，你比企鹅还能坚持。",
    ],
    100: [
        "100天！你是企鹅见过最固执的人类。",
        "百天签到达成！企鹅决定赏你一条冷冻鱼。",
        "100天连签，南极长老会注意到你了。",
    ],
    365: [
        "365天全年签到！！！企鹅族谱上从此有你的名字。",
        "一年连签！你已经是半个企鹅了。身份证稍后发放。",
    ],
}

DAILY_REWARDS = [
    "签到成功，今天又活了一天。",
    "滴——打卡成功。企鹅冷漠地看了你一眼。",
    "签到！企鹅从冰水里探出头表示看到了。",
    "签到打卡，南极冰面留下你的脚印。",
    "打卡完成！企鹅叼来一条鱼作为奖励（然后又叼走了）。",
    "签到成功。凑企鹅在此盖章确认。",
]


def _pick_reward(streak: int, total: int) -> str:
    """根据连续签到天数选择奖励消息"""
    # 检查是否命中里程碑
    for milestone in sorted(STREAK_REWARDS.keys(), reverse=True):
        if streak >= milestone and streak % milestone == 0:
            return random.choice(STREAK_REWARDS[milestone])

    # 日常奖励
    return random.choice(DAILY_REWARDS)


# ============================================================
# 命令：/签到
# ============================================================
checkin_cmd = on_command("签到", aliases={"打卡", "报到"}, priority=5, block=True)


@checkin_cmd.handle()
async def handle_checkin(bot: Bot, event: GroupMessageEvent):
    user_id = str(event.user_id)
    group_id = str(event.group_id)
    storage = get_checkin_storage()
    streak, total, is_first = storage.checkin(group_id, user_id)

    if not is_first:
        await checkin_cmd.finish(
            f"[CQ:at,qq={user_id}] 你今天已经签过了。\n"
            f"连续{streak}天 | 累计{total}次"
        )

    reward = _pick_reward(streak, total)
    await checkin_cmd.finish(
        f"[CQ:at,qq={user_id}] 第{total}次签到 | 连续{streak}天\n{reward}"
    )

    logger.info(
        f"[签到] 群:{event.group_id} 用户:{user_id} | "
        f"连续:{streak}天 累计:{total}次"
    )


# ============================================================
# 命令：/签到排行
# ============================================================
rank_cmd = on_command("签到排行", aliases={"签到排名", "签到榜"}, priority=5, block=True)


@rank_cmd.handle()
async def handle_checkin_rank(bot: Bot, event: GroupMessageEvent):
    """显示连续签到排行榜"""
    storage = get_checkin_storage()

    # 解析参数（取前 N 名，默认 10）
    text = event.get_plaintext().strip()
    n = 10
    m = re.search(r'\d+', text.replace("签到排行", "").replace("签到排名", "").replace("签到榜", ""))
    if m:
        n = min(int(m.group()), 30)

    group_id = str(event.group_id)
    top = storage.get_top_streaks(group_id, n)
    if not top:
        await rank_cmd.finish("本群还没有人签到过。快来做第一个吧！")

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"🐧 本群签到排行榜 TOP{len(top)}", ""]
    for i, (uid, streak, total) in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"  {medal} [CQ:at,qq={uid}] — 连续{streak}天 | 累计{total}次")

    await rank_cmd.finish("\n".join(lines))
