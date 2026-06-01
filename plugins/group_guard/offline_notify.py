"""
掉线通知 + 自动恢复 + 会话清理模块

区分两类掉线：
  - 致命掉线（登录失效/token 过期）→ 清除 QQ 会话数据 + 重启 NapCat + 通知扫码
  - 临时掉线（网络波动/服务重启）→ 指数退避自动重连

恢复确认：用 get_status（查 QQ 内核运行时状态）而非 get_login_info（缓存值）
"""

import asyncio
import os
import shutil
import subprocess

from nonebot import on_notice, get_driver, get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, NoticeEvent
from nonebot.rule import Rule

from .settings import NAPCAT_DIR, QQ_DATA_DIR, napcat_app_dir


# ============================================================
# 重连配置
# ============================================================
RECONNECT_MAX_ATTEMPTS = 10       # 最大重连次数
RECONNECT_BASE_DELAY = 5          # 首次重连延迟（秒）
RECONNECT_MAX_DELAY = 300         # 最大重连延迟（秒，5分钟）
HEARTBEAT_INTERVAL = 30           # 心跳检测间隔（秒）
HEARTBEAT_TIMEOUT = 10            # 心跳 API 调用超时（秒）

# 致命掉线后自动清除会话 + 重启 NapCat
AUTO_CLEAR_ON_FATAL = True        # 致命掉线自动清除会话
NAPCAT_RESTART_DELAY = 3          # 杀进程后等几秒再启动
# NAPCAT_DIR / QQ_DATA_DIR 由 settings.py 集中提供（路径不再硬编码）

# 致命掉线关键字 — 匹配到则跳过自动重连（必须扫码）
FATAL_OFFLINE_KEYWORDS = [
    "登录已失效", "登录失效", "token过期", "token 过期",
    "账号冻结", "账号被封", "密码已修改", "设备锁",
    "安全提醒", "身份验证",
]

# 重连状态
_reconnect_lock = asyncio.Lock()
_bot_was_offline = False
_fatal_offline = False


# ============================================================
# NapCat 会话清理
# ============================================================
def _clear_qq_session():
    """清除 QQ 登录会话数据（同步，在线程池执行）

    删除的目录：
      - %APPDATA%/QQ/Partitions/  (登录分区，核心)
      - %APPDATA%/QQ/auth/        (加密的登录凭据)
      - %APPDATA%/QQ/blob_storage/
      - NapCat cache/

    不清除：
      - NapCat 配置文件 (onebot11_*.json, napcat*.json) — 保留 WebSocket 配置
      - QQ 程序文件
    """
    cleared = []
    failed = []

    # ---- QQ 会话数据 ----
    qq_targets = [
        QQ_DATA_DIR / "Partitions",
        QQ_DATA_DIR / "auth",
        QQ_DATA_DIR / "blob_storage",
        QQ_DATA_DIR / "arks",
        QQ_DATA_DIR / "Cache",
        QQ_DATA_DIR / "Code Cache",
        QQ_DATA_DIR / "Local Storage",
        QQ_DATA_DIR / "Network",
        QQ_DATA_DIR / "Shared Dictionary",
        QQ_DATA_DIR / "dynamic_module",
        QQ_DATA_DIR / "dynamic_package",
        QQ_DATA_DIR / "qqex",
    ]

    for target in qq_targets:
        if target.exists():
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
                cleared.append(str(target))
            except Exception as e:
                failed.append(f"{target}: {e}")

    # ---- 清理残留的数据库文件 ----
    for f in QQ_DATA_DIR.glob("*.db*"):
        try:
            f.unlink()
            cleared.append(str(f))
        except Exception as e:
            failed.append(f"{f}: {e}")
    for f in QQ_DATA_DIR.glob("SharedStorage*"):
        try:
            f.unlink()
            cleared.append(str(f))
        except Exception as e:
            failed.append(f"{f}: {e}")

    # ---- NapCat 缓存 / 日志（版本目录自动探测，不写死版本号）----
    napcat_app = napcat_app_dir()
    if napcat_app:
        napcat_cache = napcat_app / "cache"
        if napcat_cache.exists():
            try:
                shutil.rmtree(napcat_cache)
                cleared.append(str(napcat_cache))
            except Exception as e:
                failed.append(f"{napcat_cache}: {e}")

        napcat_logs = napcat_app / "logs"
        if napcat_logs.exists():
            try:
                for log_file in napcat_logs.glob("*.log"):
                    try:
                        log_file.unlink()
                    except Exception:
                        pass
            except Exception:
                pass
    else:
        logger.warning(
            f"[掉线通知] ⚠️ 未找到 NapCat app 目录（NAPCAT_DIR={NAPCAT_DIR}），"
            f"跳过 NapCat 缓存清理"
        )

    # ---- QQ 日志 ----
    qq_logs = QQ_DATA_DIR / "log"
    if qq_logs.exists():
        try:
            shutil.rmtree(qq_logs)
            cleared.append(str(qq_logs))
        except Exception as e:
            failed.append(f"{qq_logs}: {e}")

    return cleared, failed


def _kill_qq_processes():
    """杀掉所有 QQ 和 NapCat 相关进程"""
    killed = []
    for proc_name in ["QQ.exe", "NapCatWinBootMain.exe", "NapCatWinBootHook.dll"]:
        try:
            # /f = force, /im = image name
            result = subprocess.run(
                ["taskkill", "/f", "/im", proc_name],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                killed.append(proc_name)
        except Exception:
            pass
    return killed


def _restart_napcat():
    """异步重启 NapCat（非阻塞）"""
    napcat_bat = NAPCAT_DIR / "napcat.bat"
    if not napcat_bat.exists():
        logger.error(f"[掉线通知] ❌ 找不到 NapCat 启动脚本: {napcat_bat}")
        return False

    try:
        # 用 cmd 启动 bat，后台运行不等待
        subprocess.Popen(
            f'start "" "{napcat_bat}"',
            shell=True,
            cwd=str(NAPCAT_DIR),
            creationflags=subprocess.CREATE_NEW_CONSOLE
            if os.name == "nt" else 0,
        )
        logger.info(f"[掉线通知] 🔄 NapCat 启动中... ({napcat_bat})")
        return True
    except Exception as e:
        logger.error(f"[掉线通知] ❌ 启动 NapCat 失败: {e}")
        return False


async def _auto_clear_and_restart():
    """致命掉线后：杀进程 → 清会话 → 重启 NapCat（在线程池执行 IO 操作）"""
    loop = asyncio.get_running_loop()
    logger.info("[掉线通知] 🧹 开始自动清除 QQ 会话数据...")

    # 1. 杀进程
    killed = await loop.run_in_executor(None, _kill_qq_processes)
    logger.info(f"[掉线通知] 🔪 已终止进程: {killed}")

    # 2. 等进程完全退出
    await asyncio.sleep(1)

    # 3. 清数据
    cleared, failed = await loop.run_in_executor(None, _clear_qq_session)
    for path in cleared:
        logger.info(f"[掉线通知] 🗑️ 已清除: {path}")
    for err in failed:
        logger.warning(f"[掉线通知] ⚠️ 清除失败: {err}")

    # 4. 等一会再启动
    await asyncio.sleep(NAPCAT_RESTART_DELAY)

    # 5. 重启 NapCat
    ok = await loop.run_in_executor(None, _restart_napcat)
    if ok:
        logger.info("[掉线通知] ✅ NapCat 已重新启动，等待扫码...")
    else:
        logger.error("[掉线通知] ❌ NapCat 重启失败，请手动启动")


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
    """真实连通性检查 — 调 get_status 查 QQ 内核运行时状态"""
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
    """机器人掉线时通知 + 按原因决定处理策略"""

    global _bot_was_offline, _fatal_offline
    _bot_was_offline = True

    tag = getattr(event, "tag", "未知原因")
    message = getattr(event, "message", "")
    reason = message or tag

    fatal = _is_fatal_offline(reason)
    _fatal_offline = fatal

    logger.error(f"[掉线通知] ⚠️ Bot 已离线！原因: {reason} | 致命={fatal}")

    if fatal:
        # ---- 致命掉线：清数据 + 重启 NapCat + 通知扫码 ----
        notify_msg = (
            f"⚠️ 狗三掉线 — 正在自动重置登录环境\n\n"
            f"原因: {reason}\n\n"
            f"已自动执行：\n"
            f"1. 终止 QQ / NapCat 进程\n"
            f"2. 清除过期登录会话数据\n"
            f"3. 重启 NapCat\n\n"
            f"请在 NapCat WebUI 重新扫码：\n"
            f"http://127.0.0.1:6099"
        )
        await _notify_superusers(bot, notify_msg)

        if AUTO_CLEAR_ON_FATAL:
            asyncio.create_task(_auto_clear_and_restart())
        else:
            logger.info("[掉线通知] 🛑 致命掉线，自动清除已禁用，等待手动扫码...")
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
# 重新上线监听器 — 扫码 / 自动重连成功后触发
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
            delay = min(RECONNECT_BASE_DELAY * (2 ** (attempt - 1)), RECONNECT_MAX_DELAY)
            logger.info(
                f"[掉线通知] ⏳ 第 {attempt}/{RECONNECT_MAX_ATTEMPTS} 次重连，等待 {delay}s..."
            )
            await asyncio.sleep(delay)

            if _fatal_offline:
                logger.info("[掉线通知] 🛑 检测到致命掉线，放弃自动重连")
                return

            try:
                bots = get_bots()
                if not bots:
                    logger.warning("[掉线通知] ❌ 无可用 bot 实例")
                    continue

                bot = list(bots.values())[0]

                if await _check_bot_really_online(bot):
                    _bot_was_offline = False
                    login_info = await _get_login_info_safe(bot)
                    nickname = login_info.get("nickname", "狗三")
                    logger.info(
                        f"[掉线通知] ✅ {nickname} 已恢复在线！（第 {attempt} 次重连成功）"
                    )
                    return
                else:
                    logger.warning(f"[掉线通知] ⚠️ 第 {attempt} 次 — get_status 返回不在线")

            except Exception as e:
                logger.error(f"[掉线通知] 重连检测异常: {e}")

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
    await asyncio.sleep(20)

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
        f"自动清除会话:{AUTO_CLEAR_ON_FATAL})"
    )
