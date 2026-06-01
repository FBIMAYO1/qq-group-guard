"""
掉线通知 + 自动恢复模块

区分两类掉线：
  - 致命掉线（登录失效/token 过期）→ 通知超管扫码，不自动重连
  - 临时掉线（网络波动/服务重启）→ 指数退避自动重连

恢复确认：用 get_status（查 QQ 内核运行时状态）而非 get_login_info（缓存值）
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

# 致命掉线关键字 — 匹配到则跳过自动重连（必须扫码）
FATAL_OFFLINE_KEYWORDS = [
    "登录已失效", "登录失效", "token过期", "token 过期",
    "账号冻结", "账号被封", "密码已修改", "设备锁",
    "安全提醒", "身份验证",
]

# 重连状态
_reconnect_lock = asyncio.Lock()
_bot_was_offline = False
_fatal_offline = False            # 是否致命掉线（需扫码）


# ============================================================
# 工具函数
# ============================================================
def _is_fatal_offline(reason: str) -> bool:
    """判断掉线原因是否致命（需扫码，自动重连无意义）"""
    reason_lower = reason.lower()
    for kw in FATAL_OFFLINE_KEYWORDS:
        if kw.lower() in reason_lower:
            return True
    return False


async def _check_bot_really_online(bot: Bot) -> bool:
    """真实连通性检查 — 调 get_status 查 QQ 内核运行时状态

    get_status 返回示例: {"online": true, "good": true, ...}
    只有 QQ 内核真正在线时才返回 online=true。
    对比 get_login_info 只是读 NapCat 本地缓存，QQ 死了也能返回。
    """
    try:
        status = await asyncio.wait_for(
            bot.call_api("get_status"),
            timeout=HEARTBEAT_TIMEOUT,
        )
        return bool(status.get("online", False))
    except Exception:
        return False


async def _get_login_info_safe(bot: Bot) -> dict:
    """安全获取登录信息，失败返回空字典"""
    try:
        return await asyncio.wait_for(
            bot.call_api("get_login_info"),
            timeout=HEARTBEAT_TIMEOUT,
        )
    except Exception:
        return {}


async def _notify_superusers(bot: Bot, msg: str):
    """给所有超管发私聊通知，单个失败不影响其他"""
    superusers = get_driver().config.superusers
    if not superusers:
        return
    for user_id in superusers:
        try:
            await bot.send_private_msg(user_id=int(user_id), message=msg)
            logger.info(f"[掉线通知] ✅ 已通知超级管理员 {user_id}")
        except Exception as e:
            logger.error(f"[掉线通知] 通知超级管理员 {user_id} 失败: {e}")


# ============================================================
# 判断事件类型
# ============================================================
async def _is_bot_offline(event: NoticeEvent) -> bool:
    return event.notice_type == "bot_offline"


async def _is_bot_online(event: NoticeEvent) -> bool:
    """bot 重新上线事件（扫码成功后会触发）"""
    return event.notice_type == "bot_online"


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
    """机器人掉线时通知 + 按原因决定是否自动重连"""

    global _bot_was_offline, _fatal_offline
    _bot_was_offline = True

    # 获取掉线原因
    tag = getattr(event, "tag", "未知原因")
    message = getattr(event, "message", "")
    reason = message or tag

    fatal = _is_fatal_offline(reason)
    _fatal_offline = fatal

    logger.error(f"[掉线通知] ⚠️ Bot 已离线！原因: {reason} | 致命={fatal}")

    if fatal:
        # ---- 致命掉线：不自动重连，直接通知超管扫码 ----
        notify_msg = (
            f"⚠️ 狗三掉线 — 需要重新扫码\n\n"
            f"原因: {reason}\n\n"
            f"此类掉线无法自动恢复，请立即扫码：\n"
            f"1. 打开 NapCat WebUI: http://127.0.0.1:6099\n"
            f"2. 点击「重新登录」扫码\n"
            f"3. 扫码成功后 Bot 会自动恢复并通知你"
        )
        await _notify_superusers(bot, notify_msg)
        logger.info("[掉线通知] 🛑 致命掉线，跳过自动重连，等待扫码...")
    else:
        # ---- 临时掉线：通知 + 自动重连 ----
        notify_msg = (
            f"⚠️ 狗三掉线通知\n\n"
            f"原因: {reason}\n\n"
            f"正在自动尝试重连（最多{RECONNECT_MAX_ATTEMPTS}次）..."
        )
        await _notify_superusers(bot, notify_msg)
        asyncio.create_task(_auto_reconnect_with_backoff())


# ============================================================
# 重新上线监听器 — 扫码成功 / 自动重连成功后触发
# ============================================================
bot_online = on_notice(
    rule=Rule(_is_bot_online),
    priority=0,
    block=False,
)


@bot_online.handle()
async def _handle_bot_online(bot: Bot, event: NoticeEvent):
    """Bot 重新上线 → 通知超管"""

    global _bot_was_offline, _fatal_offline

    # 验证真实在线（不是假恢复）
    really_online = await _check_bot_really_online(bot)
    if not really_online:
        logger.warning("[掉线通知] ⚠️ 收到 bot_online 但 get_status 返回不在线，忽略")
        return

    login_info = await _get_login_info_safe(bot)
    nickname = login_info.get("nickname", "狗三")
    qq = login_info.get("user_id", "?")

    if _fatal_offline:
        _fatal_offline = False
        logger.info(f"[掉线通知] ✅ 扫码成功！{nickname}({qq}) 已重新上线")
        msg = (
            f"✅ 狗三扫码成功，已重新上线！\n\n"
            f"账号: {nickname} ({qq})\n"
            f"恢复正常，可以继续使用了 ✨"
        )
    else:
        logger.info(f"[掉线通知] ✅ Bot 已重新上线: {nickname}({qq})")
        msg = (
            f"✅ 狗三已恢复在线！\n\n"
            f"账号: {nickname} ({qq})\n"
            f"自动恢复成功 ✨"
        )

    _bot_was_offline = False
    await _notify_superusers(bot, msg)


# ============================================================
# 自动重连 — 指数退避（仅临时掉线使用）
# ============================================================
async def _auto_reconnect_with_backoff():
    """临时掉线后自动重连，指数退避，用 get_status 做真实检测"""
    global _bot_was_offline, _fatal_offline

    async with _reconnect_lock:
        logger.info("[掉线通知] 🔄 开始自动重连...")

        for attempt in range(1, RECONNECT_MAX_ATTEMPTS + 1):
            # 指数退避：5s → 10s → 20s → ... → 300s cap
            delay = min(RECONNECT_BASE_DELAY * (2 ** (attempt - 1)), RECONNECT_MAX_DELAY)
            logger.info(
                f"[掉线通知] ⏳ 第 {attempt}/{RECONNECT_MAX_ATTEMPTS} 次重连，"
                f"等待 {delay}s..."
            )
            await asyncio.sleep(delay)

            # 如果中途变成致命掉线 → 放弃
            if _fatal_offline:
                logger.info("[掉线通知] 🛑 检测到致命掉线，放弃自动重连")
                return

            try:
                bots = get_bots()
                if not bots:
                    logger.warning("[掉线通知] ❌ 无可用 bot 实例")
                    continue

                bot = list(bots.values())[0]

                # ===== 用 get_status 做真实检测（非缓存）=====
                if await _check_bot_really_online(bot):
                    _bot_was_offline = False
                    login_info = await _get_login_info_safe(bot)
                    nickname = login_info.get("nickname", "狗三")
                    logger.info(
                        f"[掉线通知] ✅ {nickname} 已恢复在线！"
                        f"（第 {attempt} 次重连成功）"
                    )
                    # 恢复通知由 bot_online handler 统一发送
                    return
                else:
                    logger.warning(
                        f"[掉线通知] ⚠️ 第 {attempt} 次 — get_status 返回不在线"
                    )

            except Exception as e:
                logger.error(f"[掉线通知] 重连检测异常: {e}")

        # 全部重连失败 → 升级为致命，通知超管扫码
        _fatal_offline = True
        logger.error(
            f"[掉线通知] ❌ {RECONNECT_MAX_ATTEMPTS} 次重连全部失败！"
            f"请手动扫码登录：http://127.0.0.1:6099"
        )
        await _notify_reconnect_failed()


async def _notify_reconnect_failed():
    """通知超管重连全部失败，需手动扫码"""
    superusers = get_driver().config.superusers
    if not superusers:
        return

    msg = (
        f"❌ 狗三自动重连失败\n\n"
        f"已尝试 {RECONNECT_MAX_ATTEMPTS} 次重连，全部失败。\n"
        f"请手动处理：\n"
        f"1. 打开 NapCat WebUI: http://127.0.0.1:6099\n"
        f"2. 点击「重新登录」扫码\n"
        f"3. 扫码成功后 Bot 会自动恢复并通知你"
    )
    try:
        bots = get_bots()
        if bots:
            bot = list(bots.values())[0]
            await _notify_superusers(bot, msg)
    except Exception:
        pass
    logger.error(msg.replace("\n", " | "))


# ============================================================
# 心跳看门狗 — 周期性真实连通性检测
# ============================================================
async def _heartbeat_watchdog():
    """每 HEARTBEAT_INTERVAL 秒用 get_status 检测 QQ 内核是否在线"""
    await asyncio.sleep(20)  # 等 NoneBot 完全启动

    global _bot_was_offline, _fatal_offline

    while True:
        await asyncio.sleep(HEARTBEAT_INTERVAL)

        try:
            bots = get_bots()
            if not bots:
                continue

            bot = list(bots.values())[0]

            online = await _check_bot_really_online(bot)
            if online:
                if _bot_was_offline:
                    _bot_was_offline = False
                    logger.info("[心跳] ✅ Bot 已恢复在线！")
            else:
                if not _bot_was_offline:
                    _bot_was_offline = True
                    logger.warning("[心跳] ⚠️ get_status 返回不在线，可能已掉线")
                if not _fatal_offline:
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
        f"超时:{HEARTBEAT_TIMEOUT}s, "
        f"致命检测:已启用)"
    )
