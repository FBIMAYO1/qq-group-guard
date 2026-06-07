"""
刷屏检测模块

滑动窗口检测刷屏行为，同一用户在窗口内发送超过阈值条消息则自动禁言。

配置：
- SPAM_THRESHOLD: 窗口内消息数阈值（默认 5）
- SPAM_WINDOW: 滑动窗口大小（秒，默认 10）
- MUTE_DURATION: 禁言时长（秒，默认 300 = 5分钟）
"""

import asyncio
import time

from nonebot import on_message, get_driver, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from .config import plugin_config
from .group_config import get_group_config


# ============================================================
# 配置
# ============================================================
SPAM_THRESHOLD = 5      # 窗口内消息数阈值
SPAM_WINDOW = 10        # 滑动窗口大小（秒）
MUTE_DURATION = 300     # 禁言时长（秒）


# ============================================================
# 滑动窗口数据 — 纯内存存储
# ============================================================
# {group_id: {user_id: [timestamp, ...]}}
_spam_tracker: dict[str, dict[str, list[float]]] = {}


# ============================================================
# 消息处理器
# ============================================================
spam_detector = on_message(priority=4, block=False)


@spam_detector.handle()
async def handle_spam(bot: Bot, event: GroupMessageEvent):
    """检测刷屏"""
    gid = str(event.group_id)
    uid = str(event.user_id)

    # 检查功能开关
    gcfg = get_group_config()
    if not gcfg.get(gid).spam_enabled:
        return

    # 跳过管理员和群主
    if event.sender.role in ("admin", "owner"):
        return

    now = time.time()

    # 初始化嵌套字典
    if gid not in _spam_tracker:
        _spam_tracker[gid] = {}
    if uid not in _spam_tracker[gid]:
        _spam_tracker[gid][uid] = []

    timestamps = _spam_tracker[gid][uid]

    # 清理过期时间戳
    cutoff = now - SPAM_WINDOW
    _spam_tracker[gid][uid] = [t for t in timestamps if t > cutoff]

    # 记录当前消息
    _spam_tracker[gid][uid].append(now)

    # 检查阈值
    count = len(_spam_tracker[gid][uid])
    if count >= SPAM_THRESHOLD:
        # 清空时间戳防止连锁触发
        _spam_tracker[gid][uid] = []

        # 尝试禁言（受禁言开关控制 — 按群独立）
        mute_min = MUTE_DURATION // 60
        mute_enabled = get_group_config().get(gid).mute_enabled
        if mute_enabled:
            try:
                await bot.set_group_ban(
                    group_id=event.group_id,
                    user_id=event.user_id,
                    duration=MUTE_DURATION,
                )
            except Exception:
                logger.warning(
                    f"[刷屏] 禁言失败 群:{gid} 用户:{uid} — bot可能无管理员权限"
                )
        else:
            logger.info(
                f"[刷屏] 禁言已关闭 群:{gid} 用户:{uid} | "
                f"{count}条/{SPAM_WINDOW}s → 仅警告"
            )

        # 发送警告
        mute_note = f"，企鹅送你{mute_min}分钟冷静期" if mute_enabled else "，禁言已关闭仅作警告"
        await bot.send_group_msg(
            group_id=event.group_id,
            message=(
                f"[CQ:at,qq={uid}] 刷屏了！\n"
                f"{count}条消息/{SPAM_WINDOW}秒内{mute_note}。"
            ),
        )

        logger.info(
            f"[刷屏] 群:{gid} 用户:{uid} | "
            f"{count}条/{SPAM_WINDOW}s → 禁言{'已关闭' if not mute_enabled else f'{mute_min}分钟'}"
        )


# ============================================================
# 后台清理任务
# ============================================================
async def _spam_cleanup_loop():
    """定期清理全局过期数据，防止内存泄漏"""
    await asyncio.sleep(10)

    while True:
        try:
            now = time.time()
            cutoff = now - SPAM_WINDOW

            for gid in list(_spam_tracker.keys()):
                for uid in list(_spam_tracker[gid].keys()):
                    _spam_tracker[gid][uid] = [
                        t for t in _spam_tracker[gid][uid] if t > cutoff
                    ]
                    if not _spam_tracker[gid][uid]:
                        del _spam_tracker[gid][uid]
                if not _spam_tracker[gid]:
                    del _spam_tracker[gid]
        except Exception as e:
            logger.error(f"[刷屏] 清理异常: {e}")

        await asyncio.sleep(30)


# ============================================================
# 启动钩子
# ============================================================
_driver = get_driver()


@_driver.on_startup
async def _start_spam_cleanup():
    """NoneBot 启动后拉起刷屏清理任务"""
    asyncio.create_task(_spam_cleanup_loop())
    logger.info("[刷屏] 🚨 刷屏检测模块已启动")
