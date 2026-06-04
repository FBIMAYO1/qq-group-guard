"""
每日摸鱼日历播报模块

每天早上 8:00 向各群发送「摸鱼人日历」图片 + 智能文字附言。
图片与内容由 moyuren.py 调用 moyuren_server 公开 API 获取。

本模块只负责「播报骨架」：
  1. 群收集器 — 记录所有活跃群（priority=99）
  2. 8:00 定时循环 — 到点构建消息并群发
  3. 群开关检查 — 仅向开启了 morning_brief_enabled 的群发送
  4. 群间随机延迟 — 抗风控；防止重启后重复发

注：开关沿用 morning_brief_enabled（/功能开关 早安短报），语义不变。
"""

import asyncio
from datetime import datetime

from nonebot import on_message, get_driver, get_bots, logger
from nonebot.adapters.onebot.v11 import GroupMessageEvent

from . import moyuren
from .group_config import get_group_config


# ============================================================
# 记录活跃群 — 防止重启后重复发
# ============================================================
_active_groups: set[str] = set()


# 注意：与 brainwash.py 的 member_collector (priority=99) 同时运行，
# 两者独立收集，可考虑未来合并为一个统一的元数据收集器
group_collector = on_message(priority=99, block=False)


@group_collector.handle()
async def _collect_group(event: GroupMessageEvent):
    """记录所有出现过消息的群"""
    _active_groups.add(str(event.group_id))


# ============================================================
# 定时播报任务
# ============================================================
async def _morning_brief_loop():
    """每天早上 8:00 发送摸鱼日历"""
    await asyncio.sleep(8)  # 等待 NoneBot 完全启动

    last_send_date = ""

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # 检查是否到了 8:00（±4分钟窗口，避免因高负载错过）
            hour, minute = now.hour, now.minute
            is_eight = (hour == 8 and 0 <= minute <= 4)

            if is_eight and today_str != last_send_date:
                last_send_date = today_str

                bots = get_bots()
                if not bots:
                    logger.warning("[早报] 没有可用的Bot实例")
                    await asyncio.sleep(60)
                    continue

                bot = list(bots.values())[0]

                # 构建摸鱼日历图文消息（含 API 请求）
                msg = await moyuren.get_moyuren_message()
                if msg is None:
                    logger.warning("[早报] 摸鱼日历获取失败，本次播报跳过")
                    await asyncio.sleep(60)
                    continue

                # 发送到所有已知的群
                groups = list(_active_groups)
                if not groups:
                    logger.warning("[早报] 没有已知的活跃群")
                else:
                    sent_count = 0
                    gcfg = get_group_config()
                    for gid in groups:
                        # 检查功能开关 — 该群是否开启了每日播报
                        if not gcfg.get(gid).morning_brief_enabled:
                            logger.info(f"[早报] 群{gid} 已关闭摸鱼日历播报，跳过")
                            continue
                        try:
                            await bot.send_group_msg(
                                group_id=int(gid),
                                message=msg,
                            )
                            sent_count += 1
                            await asyncio.sleep(1.5)  # 群间间隔，避免风控
                        except Exception as e:
                            logger.error(f"[早报] 群{gid}发送失败: {e}")

                    logger.info(f"[早报] ✅ 摸鱼日历已发送到 {sent_count}/{len(groups)} 个群")

        except Exception as e:
            logger.error(f"[早报] 后台异常: {e}")

        await asyncio.sleep(60)  # 每分钟检查一次


# ============================================================
# 注册启动钩子
# ============================================================
_driver = get_driver()


@_driver.on_startup
async def _start_morning_brief():
    """NoneBot启动后拉起摸鱼日历播报任务"""
    asyncio.create_task(_morning_brief_loop())
    logger.info("[早报] 📅 摸鱼日历播报模块已启动，每天早上8:00发送")
