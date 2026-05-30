"""
处罚系统 - 警告与阶梯禁言（每日清零）

处罚规则（当日累计）：
- 第1次违规：@警告
- 第2次违规：@警告（最后警告）
- 第3次违规：禁言1小时
- 第4次违规：禁言2小时
- 第N次违规（N>=3）：禁言 (N-2) 小时（等差递增）
- 每天0点自动清零 → 违规计数从1重新开始
"""

from dataclasses import dataclass

from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from .storage import get_storage
from .checker import CheckResult
from .config import plugin_config


@dataclass
class PunishResult:
    """处罚结果"""
    action: str             # "warn" | "mute"
    violation_count: int    # 当前是第几次违规
    mute_duration: int      # 禁言时长（秒），0表示仅警告
    message: str            # 发送给群里的消息


class Punisher:
    """处罚执行器"""

    def __init__(self):
        self.storage = get_storage()

    def calculate_punishment(self, count: int) -> tuple[str, int]:
        """
        根据违规次数计算处罚

        Args:
            count: 当前累计违规次数（含本次）

        Returns:
            (action, mute_seconds)
        """
        if count < 3:
            return "warn", 0
        else:
            # 第3次=1小时, 第4次=2小时, 第N次=(N-2)小时
            hours = count - 2
            return "mute", hours * 3600

    def build_warn_message(
        self,
        user_id: int,
        count: int,
        check_result: CheckResult,
    ) -> str:
        """构建警告消息"""
        at_user = f"[CQ:at,qq={user_id}]"

        if count == 1:
            return (
                f"⚠️ {at_user} 【第1次警告】\n"
                f"你的发言涉及违规内容（{check_result.category_name}）\n"
                f"请注意群规，下不为例！"
            )
        elif count == 2:
            return (
                f"⚠️⚠️ {at_user} 【第2次警告 - 最后警告】\n"
                f"你的发言再次涉及违规内容（{check_result.category_name}）\n"
                f"再犯将被禁言处理！"
            )
        else:
            hours = count - 2
            return (
                f"🔇 {at_user} 【违规禁言】\n"
                f"第{count}次违规（{check_result.category_name}）\n"
                f"禁言 {hours} 小时\n"
                f"请认真遵守群规！"
            )

    async def execute(
        self,
        bot: Bot,
        event: GroupMessageEvent,
        check_result: CheckResult,
    ) -> PunishResult:
        """
        执行处罚流程

        1. 记录违规
        2. 计算处罚
        3. 执行处罚（发消息 + 禁言）
        """
        group_id = str(event.group_id)
        user_id = str(event.user_id)

        # 记录违规并获取累计次数
        count = self.storage.add_violation(
            group_id=group_id,
            user_id=user_id,
            category=check_result.category_name or "未知",
            matched=check_result.matched_word or "",
            action="",  # 先占位，后面更新
            text=check_result.original_text or "",
        )

        # 计算处罚
        action, mute_seconds = self.calculate_punishment(count)

        # 更新记录中的 action 字段
        self.storage.update_last_record_action(group_id, user_id, action)

        # 构建消息
        message = self.build_warn_message(event.user_id, count, check_result)

        # 执行禁言（受禁言开关控制）
        if action == "mute" and mute_seconds > 0:
            if plugin_config.mute_enabled:
                try:
                    await bot.set_group_ban(
                        group_id=event.group_id,
                        user_id=event.user_id,
                        duration=mute_seconds,
                    )
                except Exception as e:
                    message += f"\n（禁言执行失败：{e}）"
            else:
                message += "\n💡 禁言功能已关闭，本次仅作警告"

        # 尝试撤回违规消息
        try:
            await bot.delete_msg(message_id=event.message_id)
        except Exception:
            pass  # 撤回失败不影响主流程（可能没有管理员权限）

        result = PunishResult(
            action=action,
            violation_count=count,
            mute_duration=mute_seconds,
            message=message,
        )

        return result


# 全局单例
_punisher: Punisher | None = None


def get_punisher() -> Punisher:
    """获取处罚器单例"""
    global _punisher
    if _punisher is None:
        _punisher = Punisher()
    return _punisher
