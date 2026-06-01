"""
违规记录存储 - 使用 JSON 文件持久化

每日清零规则：每天0点自动清零所有用户的违规计数，历史记录保留。

存储结构：
{
    "群号": {
        "_whitelist": ["QQ号1", "QQ号2"],
        "_last_reset": "2026-05-30",
        "用户QQ号": {
            "count": 今日违规次数,
            "records": [...]
        }
    }
}
"""

import time

from .store import JsonStore


DATA_FILE = "violations.json"


class ViolationStorage(JsonStore):
    """违规记录存储管理"""

    WHITELIST_KEY = "_whitelist"
    RESET_KEY = "_last_reset"

    def __init__(self):
        super().__init__(DATA_FILE)
        self._check_daily_reset()

    # ============================================================
    # 每日清零
    # ============================================================

    @staticmethod
    def _today() -> str:
        """返回今天日期字符串 YYYY-MM-DD"""
        return time.strftime("%Y-%m-%d")

    def _check_daily_reset(self):
        """检查所有群是否到了新的一天，是则清零计数（保留历史记录）"""
        today = self._today()
        changed = False
        for gid in list(self._data.keys()):
            last_reset = self._data[gid].get(self.RESET_KEY, "")
            if last_reset != today:
                # 新的一天 → 清零所有用户的 count
                for uid in list(self._data[gid].keys()):
                    if uid in (self.WHITELIST_KEY, self.RESET_KEY):
                        continue
                    info = self._data[gid][uid]
                    if isinstance(info, dict) and info.get("count", 0) > 0:
                        info["count"] = 0
                self._data[gid][self.RESET_KEY] = today
                changed = True
        if changed:
            self.save()

    # ============================================================
    # 违规记录
    # ============================================================

    def add_violation(
        self,
        group_id: str,
        user_id: str,
        category: str,
        matched: str,
        action: str,
        text: str = "",
    ) -> int:
        """记录一次违规，返回当前今日累计次数"""
        self._check_daily_reset()
        self._ensure_group(group_id)
        self._ensure_user(group_id, user_id)

        user_data = self._data[group_id][user_id]
        user_data["count"] += 1
        user_data["records"].append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "category": category,
            "matched": matched,
            "action": action,
            "text": text,
        })
        self.save()
        return user_data["count"]

    def add_manual_violation(
        self,
        group_id: str,
        user_id: str,
        count: int = 1,
        reason: str = "管理员手动添加",
    ) -> int:
        """管理员手动添加违规记录"""
        self._check_daily_reset()
        self._ensure_group(group_id)
        self._ensure_user(group_id, user_id)

        user_data = self._data[group_id][user_id]
        for _ in range(count):
            user_data["count"] += 1
            user_data["records"].append({
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "category": "手动添加",
                "matched": reason,
                "action": "手动违规",
            })
        self.save()
        return user_data["count"]

    def set_violation_count(
        self, group_id: str, user_id: str, count: int
    ) -> int:
        """设置违规次数为指定值"""
        self._ensure_group(group_id)
        self._ensure_user(group_id, user_id)

        old_count = self._data[group_id][user_id]["count"]
        if count > old_count:
            diff = count - old_count
            for _ in range(diff):
                self._data[group_id][user_id]["records"].append({
                    "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "category": "管理员调整",
                    "matched": "手动设置为指定次数",
                    "action": "手动调整",
                })
        self._data[group_id][user_id]["count"] = count
        self.save()
        return count

    def remove_last_violation(self, group_id: str, user_id: str) -> bool:
        """撤销最近一条违规记录"""
        try:
            user_data = self._data[group_id][user_id]
            if user_data["count"] > 0:
                user_data["count"] -= 1
                if user_data["records"]:
                    user_data["records"].pop()
                self.save()
                return True
            return False
        except KeyError:
            return False

    def update_last_record_action(self, group_id: str, user_id: str, action: str):
        """更新最近一条违规记录的 action 字段（warn/mute）"""
        try:
            records = self._data[group_id][user_id]["records"]
            if records:
                records[-1]["action"] = action
                self.save()
        except KeyError:
            pass

    def get_violation_count(self, group_id: str, user_id: str) -> int:
        """获取用户在某群的违规次数（今日）"""
        self._check_daily_reset()
        try:
            return self._data[group_id][user_id]["count"]
        except KeyError:
            return 0

    def get_user_records(self, group_id: str, user_id: str) -> list[dict]:
        """获取用户的违规记录列表"""
        try:
            return self._data[group_id][user_id]["records"]
        except KeyError:
            return []

    def reset_user(self, group_id: str, user_id: str) -> bool:
        """重置用户违规记录"""
        try:
            del self._data[group_id][user_id]
            self.save()
            return True
        except KeyError:
            return False

    def get_group_stats(self, group_id: str) -> dict[str, int]:
        """获取群内所有用户的违规次数统计（今日，不含白名单标记）"""
        self._check_daily_reset()
        if group_id not in self._data:
            return {}
        return {
            uid: info["count"]
            for uid, info in self._data[group_id].items()
            if uid not in (self.WHITELIST_KEY, self.RESET_KEY) and isinstance(info, dict)
        }

    def get_violation_leaderboard(
        self, group_id: str, top_n: int = 10
    ) -> list[tuple[str, int]]:
        """获取违规排行榜"""
        stats = self.get_group_stats(group_id)
        sorted_stats = sorted(stats.items(), key=lambda x: x[1], reverse=True)
        return sorted_stats[:top_n]

    # ============================================================
    # 白名单管理
    # ============================================================

    def get_whitelist(self, group_id: str) -> list[str]:
        """获取群白名单"""
        try:
            return self._data[group_id].get(self.WHITELIST_KEY, [])
        except KeyError:
            return []

    def add_to_whitelist(self, group_id: str, user_id: str) -> bool:
        """添加用户到白名单"""
        self._ensure_group(group_id)
        if self.WHITELIST_KEY not in self._data[group_id]:
            self._data[group_id][self.WHITELIST_KEY] = []
        if user_id not in self._data[group_id][self.WHITELIST_KEY]:
            self._data[group_id][self.WHITELIST_KEY].append(user_id)
            self.save()
            return True
        return False

    def remove_from_whitelist(self, group_id: str, user_id: str) -> bool:
        """从白名单移除"""
        try:
            wl = self._data[group_id].get(self.WHITELIST_KEY, [])
            if user_id in wl:
                wl.remove(user_id)
                self.save()
                return True
            return False
        except KeyError:
            return False

    def is_whitelisted(self, group_id: str, user_id: str) -> bool:
        """检查用户是否在白名单中"""
        return user_id in self.get_whitelist(group_id)

    # ============================================================
    # 内部工具
    # ============================================================

    def _ensure_group(self, group_id: str):
        if group_id not in self._data:
            self._data[group_id] = {}

    def _ensure_user(self, group_id: str, user_id: str):
        if user_id not in self._data[group_id]:
            self._data[group_id][user_id] = {"count": 0, "records": []}


# 全局单例
_storage: ViolationStorage | None = None


def get_storage() -> ViolationStorage:
    """获取存储单例"""
    global _storage
    if _storage is None:
        _storage = ViolationStorage()
    return _storage
