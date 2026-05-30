"""
群活跃排行榜模块

统计每人每天每群的发言数，支持 /活跃榜 查看水群冠军。

- 组件 A：Priority 99 消息收集器（统计发言数）
- 组件 B：命令 /活跃榜（展示 TOP N）
"""

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from nonebot import on_command, on_message, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent


# ============================================================
# 持久化存储
# ============================================================
DATA_DIR = Path(__file__).parent / "data"
DATA_FILE = DATA_DIR / "activity.json"


class ActivityStorage:
    """群活跃度存储"""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._data: dict = self._load()
        self._cleanup_old()

    def _load(self) -> dict:
        if DATA_FILE.exists():
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}

    def _save(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _today_str() -> str:
        return time.strftime("%Y-%m-%d")

    def increment(self, group_id: str, user_id: str):
        """记录一次发言"""
        today = self._today_str()
        if today not in self._data:
            self._data[today] = {}
        if group_id not in self._data[today]:
            self._data[today][group_id] = {}
        self._data[today][group_id][user_id] = \
            self._data[today][group_id].get(user_id, 0) + 1

    def get_top(
        self, group_id: str, n: int = 10
    ) -> list[tuple[str, int, int]]:
        """
        获取某群今日活跃 TOP N

        Returns:
            [(user_id, today_count, yesterday_count), ...]
        """
        today = self._today_str()

        # 今日数据
        today_data = self._data.get(today, {}).get(group_id, {})

        # 昨日数据
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        yesterday_data = self._data.get(yesterday, {}).get(group_id, {})

        items = [
            (uid, count, yesterday_data.get(uid, 0))
            for uid, count in today_data.items()
        ]
        items.sort(key=lambda x: x[1], reverse=True)
        return items[:n]

    def _cleanup_old(self):
        """清理超过 2 天的旧数据"""
        today = self._today_str()
        cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

        changed = False
        for date_key in list(self._data.keys()):
            if date_key < cutoff and date_key != today:
                del self._data[date_key]
                changed = True

        if changed:
            self._save()


# 全局单例
_activity_storage: ActivityStorage | None = None


def get_activity_storage() -> ActivityStorage:
    global _activity_storage
    if _activity_storage is None:
        _activity_storage = ActivityStorage()
    return _activity_storage


# ============================================================
# 组件 A：消息收集器（Priority 99）
# ============================================================
# 与 brainwash.py 的 member_collector 和 morning_brief.py 的 group_collector
# 同为 priority=99 的消息收集器，三者 block=False，共存无冲突。
_collect_count = 0

activity_collector = on_message(priority=99, block=False)


@activity_collector.handle()
async def _collect_activity(event: GroupMessageEvent):
    """记录每条消息的发言统计"""
    global _collect_count
    storage = get_activity_storage()
    storage.increment(str(event.group_id), str(event.user_id))

    _collect_count += 1
    if _collect_count % 50 == 0:
        storage._cleanup_old()
        _collect_count = 0  # 防止整数溢出


# ============================================================
# 组件 B：命令 /活跃榜
# ============================================================
rank_cmd = on_command(
    "活跃榜", aliases={"活跃排行", "活跃排名", "水群榜"}, priority=5, block=True
)


@rank_cmd.handle()
async def handle_activity_rank(bot: Bot, event: GroupMessageEvent):
    """展示群活跃排行榜"""
    group_id = str(event.group_id)

    # 解析参数（取前 N 名，默认 10）
    text = event.get_plaintext().strip()
    n = 10
    m = re.search(r'\d+', text.replace("活跃榜", "").replace("活跃排行", "")
                  .replace("活跃排名", "").replace("水群榜", ""))
    if m:
        n = min(int(m.group()), 30)

    storage = get_activity_storage()
    top = storage.get_top(group_id, n)

    if not top:
        await rank_cmd.finish("咕咕嘎嘎！今天还没有人说话。快去水群吧！")

    medals = ["🥇", "🥈", "🥉"]
    lines = [f"💬 今日水群排行榜 TOP{len(top)}", ""]
    for i, (uid, today_count, yesterday_count) in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        diff = today_count - yesterday_count
        if diff > 0:
            trend = f" ↑{diff}"
        elif diff < 0:
            trend = f" ↓{abs(diff)}"
        else:
            trend = ""
        lines.append(
            f"  {medal} [CQ:at,qq={uid}] — {today_count}条{trend}"
        )

    await rank_cmd.finish("\n".join(lines))
