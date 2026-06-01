"""
掉线通知 + 自动恢复模块

1. 监听 bot_offline 通知事件，通知超级管理员
2. 掉线后自动尝试重连（延迟重试 + 指数退避）
3. 周期性心跳检测，确保 WebSocket 连接健康
4. Bot 恢复后通知超级管理员
"""

import asyncio
from nonebot import on_notice, get_driver, get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, NoticeEvent
from nonebot.rule import Rule


# ============================================================
# 重连配置
# ============================================================
RECONNECT_MAX_ATTEMPTS = 10       # 最大重连次数
RECONNECT_BASE_DELAY = 5          # 首次重连延迟（秒）
RECONNECT_MAX_DELAY = 300         # 最大重连延迟（秒，5分钟）
HEARTBEAT_INTERVAL = 30           # 心跳检测间隔（秒）
HEARTBEAT_TIMEOUT = 10            # 心跳 API 调用超时（秒）

# 重连状态
_reconnect_lock = asyncio.Lock()
_reconnect_task: asyncio.Task | None = None
_bot_was_offline = False          # 用于恢复通知


# ============================================================
# 判断是否为 bot_offline 事件
# ============================================================
async def _is_bot_offline(event: NoticeEvent) -> bool:
    """只响应 bot_offline 类型的通知"""
    return event.notice_type == "bot_offline"


# ============================================================
# 掉线监听器
# ============================================================
bot_offline = on_notice(
    rule=Rule(_is_bot_offline),
    priority=0,
    block=False,
)


@bot_offline.handle()
async def _handle_bot_offline(bot: Bot, event: NoticeEvent):
    """机器人掉线时通知超级管理员 + 启动自动重连"""

    global _bot_was_offline
    _bot_was_offline = True

    # 获取掉线原因
    tag = getattr(event, "tag", "未知原因")
    message = getattr(event, "message", "")
    reason = message or tag

    logger.error(
        f"[掉线通知] ⚠️ Bot 已离线！原因: {reason}"
    )

    # 给所有超级管理员发私聊通知
    superusers = get_driver().config.superusers
    if superusers:
        notify_msg = (
            f"⚠️ 狗三掉线通知\n\n"
            f"时间: 刚刚\n"
            f"原因: {reason}\n\n"
            f"正在自动尝试重连（最多{RECONNECT_MAX_ATTEMPTS}次）...\n"
            f"如需手动处理，请打开 NapCat WebUI：\n"
            f"http://127.0.0.1:6099"
        )
        for user_id in superusers:
            try:
                await bot.send_private_msg(
                    user_id=int(user_id),
                    message=notify_msg,
                )
                logger.info(f"[掉线通知] ✅ 已通知超级管理员 {user_id}")
            except Exception as e:
                logger.error(f"[掉线通知] 通知超级管理员 {user_id} 失败: {e}")

    # 启动自动重连任务（非阻塞）
    asyncio.create_task(_auto_reconnect_with_backoff())


# ============================================================
# 自动重连 — 指数退避
# ============================================================
async def _auto_reconnect_with_backoff():
    """掉线后自动重连，指数退避延迟"""
    global _reconnect_task

    async with _reconnect_lock:
        logger.info("[掉线通知] 🔄 开始自动重连...")

        for attempt in range(1, RECONNECT_MAX_ATTEMPTS + 1):
            # 指数退避：5s → 10s → 20s → 40s → 80s → 160s → 300s (cap)
            delay = min(RECONNECT_BASE_DELAY * (2 ** (attempt - 1)), RECONNECT_MAX_DELAY)
            logger.info(
                f"[掉线通知] ⏳ 第 {attempt}/{RECONNECT_MAX_ATTEMPTS} 次重连，"
                f"等待 {delay}s..."
            )
            await asyncio.sleep(delay)

            # 尝试获取 bot 实例并检测是否已恢复
            try:
                bots = get_bots()
                if not bots:
                    logger.warning("[掉线通知] ❌ 无可用 bot 实例")
                    continue

                bot = list(bots.values())[0]

                # 调用 get_login_info 测试连通性
                try:
                    login_info = await asyncio.wait_for(
                        bot.call_api("get_login_info"),
                        timeout=HEARTBEAT_TIMEOUT,
                    )
                    global _bot_was_offline
                    if _bot_was_offline:
                        _bot_was_offline = False
                        logger.info(
                            f"[掉线通知] ✅ Bot 已恢复在线！"
                            f"（第 {attempt} 次重连成功）"
                        )
                        await _notify_recovery(bot, login_info, attempt)
                    else:
                        logger.info(
                            f"[掉线通知] ✅ 心跳成功，Bot 在线"
                        )
                    return  # 重连成功
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[掉线通知] ⚠️ 第 {attempt} 次 — API 调用超时"
                    )
                except Exception as e:
                    logger.warning(
                        f"[掉线通知] ⚠️ 第 {attempt} 次 — API 调用失败: {e}"
                    )
            except Exception as e:
                logger.error(f"[掉线通知] 重连检测异常: {e}")

        # 全部重连失败
        logger.error(
            f"[掉线通知] ❌ {RECONNECT_MAX_ATTEMPTS} 次重连全部失败！"
            f"请手动扫码登录：http://127.0.0.1:6099"
        )
        # 再次通知超级管理员
        await _notify_reconnect_failed()


async def _notify_recovery(bot: Bot, login_info, attempt: int):
    """通知超级管理员 bot 已恢复"""
    superusers = get_driver().config.superusers
    if not superusers:
        return

    nickname = login_info.get("nickname", "狗三")
    user_id = login_info.get("user_id", "未知")
    msg = (
        f"✅ 狗三已恢复在线！\n\n"
        f"账号: {nickname} ({user_id})\n"
        f"重连次数: 第 {attempt} 次\n\n"
        f"自动恢复成功 ✨"
    )
    for uid in superusers:
        try:
            await bot.send_private_msg(user_id=int(uid), message=msg)
        except Exception as e:
            logger.error(f"[掉线通知] 恢复通知 {uid} 失败: {e}")


async def _notify_reconnect_failed():
    """通知超级管理员重连全部失败"""
    superusers = get_driver().config.superusers
    if not superusers:
        return

    msg = (
        f"❌ 狗三自动重连失败\n\n"
        f"已尝试 {RECONNECT_MAX_ATTEMPTS} 次重连，全部失败。\n"
        f"请手动处理：\n"
        f"1. 打开 NapCat WebUI: http://127.0.0.1:6099\n"
        f"2. 重新扫码登录\n"
        f"3. 重启 docker-compose: docker compose restart"
    )
    try:
        bots = get_bots()
        if bots:
            bot = list(bots.values())[0]
            for uid in superusers:
                try:
                    await bot.send_private_msg(user_id=int(uid), message=msg)
                except Exception:
                    pass  # 可能发不出去，至少日志里有
    except Exception:
        pass
    # 无论如何打印到日志，方便排查
    logger.error(msg.replace("\n", " | "))


# ============================================================
# 心跳看门狗 — 周期性检测 bot 连通性
# ============================================================
async def _heartbeat_watchdog():
    """周期性检测 bot 是否在线，发现掉线则触发重连"""
    await asyncio.sleep(15)  # 等 NoneBot 完全启动

    global _bot_was_offline

    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)

        try:
            bots = get_bots()
            if not bots:
                logger.warning("[心跳] ⚠️ 无可用 bot 实例，跳过检测")
                continue

            bot = list(bots.values())[0]

            try:
                await asyncio.wait_for(
                    bot.call_api("get_login_info"),
                    timeout=HEARTBEAT_TIMEOUT,
                )
                # 心跳成功，bot 在线
                if _bot_was_offline:
                    _bot_was_offline = False
                    logger.info("[心跳] ✅ Bot 已恢复在线！")
                logger.debug("[心跳] ✅ Bot 在线")
            except asyncio.TimeoutError:
                logger.warning("[心跳] ⚠️ API 调用超时，可能已掉线")
                _bot_was_offline = True
                asyncio.create_task(_auto_reconnect_with_backoff())
            except Exception as e:
                logger.warning(f"[心跳] ⚠️ 心跳失败: {e}")
                _bot_was_offline = True
                asyncio.create_task(_auto_reconnect_with_backoff())

        except Exception as e:
            logger.error(f"[心跳] 检测异常: {e}")


# ============================================================
# 启动钩子
# ============================================================
_driver = get_driver()


@_driver.on_startup
async def _start_offline_watchdog():
    """NoneBot 启动后拉起掉线监控"""
    asyncio.create_task(_heartbeat_watchdog())
    logger.info(
        f"[掉线通知] 🔔 掉线监控已就绪 "
        f"(心跳间隔:{HEARTBEAT_INTERVAL}s, "
        f"最大重连:{RECONNECT_MAX_ATTEMPTS}次, "
        f"超时:{HEARTBEAT_TIMEOUT}s)"
    )
