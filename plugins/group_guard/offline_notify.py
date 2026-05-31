"""
掉线通知模块

监听 bot_offline 通知事件，在机器人被踢下线时私聊通知超级管理员。
"""

from nonebot import on_notice, get_driver, logger
from nonebot.adapters.onebot.v11 import Bot, NoticeEvent
from nonebot.rule import Rule


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
    """机器人掉线时通知超级管理员"""

    # 获取掉线原因
    tag = getattr(event, "tag", "未知原因")
    message = getattr(event, "message", "")
    reason = message or tag

    logger.error(
        f"[掉线通知] ⚠️ Bot 已离线！原因: {reason}"
    )

    # 给所有超级管理员发私聊通知
    superusers = get_driver().config.superusers
    if not superusers:
        logger.warning("[掉线通知] 未配置超级管理员，跳过私聊通知")
        return

    notify_msg = (
        f"⚠️ 狗三掉线通知\n\n"
        f"时间: 刚刚\n"
        f"原因: {reason}\n\n"
        f"请打开 NapCat WebUI 重新扫码登录：\n"
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


# ============================================================
# 启动日志
# ============================================================
_driver = get_driver()


@_driver.on_startup
async def _log_offline_notify_ready():
    logger.info("[掉线通知] 🔔 掉线通知模块已就绪")
