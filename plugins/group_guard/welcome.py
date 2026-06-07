"""
入群欢迎模块

新成员入群时自动 @欢迎，随机企鹅式问候。

使用 NoneBot on_notice 事件监听 GroupIncreaseNoticeEvent。
"""

import random

from nonebot import on_notice, logger
from nonebot.adapters.onebot.v11 import Bot, GroupIncreaseNoticeEvent

from .group_config import get_group_config


# ============================================================
# 欢迎语池
# ============================================================
WELCOME_MESSAGES = [
    "新人入群！[CQ:at,qq={user_id}] 欢迎来到冰面，注意别滑倒。",
    "又来一个人类。[CQ:at,qq={user_id}] 企鹅表示看到了。",
    "新企鹅（划掉）新人你好！[CQ:at,qq={user_id}] 请阅读群规，企鹅不想啄你。",
    "[CQ:at,qq={user_id}] 入群了。希望你不是海豹派来的间谍。",
    "[CQ:at,qq={user_id}] 欢迎加入！凑企鹅在此看守冰面。",
    "[CQ:at,qq={user_id}] 踏上了南极冰面。请遵守企鹅公约。",
    "新成员出现！[CQ:at,qq={user_id}] 凑企鹅代表南极欢迎你。",
    "[CQ:at,qq={user_id}] 进群记得改名片，企鹅不喜欢认错人。",
    "冰面上多了一个身影。[CQ:at,qq={user_id}] 欢迎入群，鱼在左边。",
    "[CQ:at,qq={user_id}] 欢迎来到企鹅看守的群！看群规，别违规，不然啄。",
]


# ============================================================
# 入群通知处理器
# ============================================================
welcome_notice = on_notice(priority=5, block=False)


@welcome_notice.handle()
async def handle_group_increase(bot: Bot, event: GroupIncreaseNoticeEvent):
    """新成员入群时发送欢迎消息"""
    # 检查功能开关
    gcfg = get_group_config()
    if not gcfg.get(str(event.group_id)).welcome_enabled:
        return

    # 跳过机器人自身入群
    if event.user_id == event.self_id:
        return

    msg_template = random.choice(WELCOME_MESSAGES)
    msg = msg_template.format(user_id=event.user_id)

    await bot.send_group_msg(group_id=event.group_id, message=msg)

    logger.info(f"[欢迎] 群:{event.group_id} 新人:{event.user_id}")
