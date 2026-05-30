"""
广告/链接检测模块

纯正则检测，不消耗 AI token。检测以下内容：
- 外部链接（http/https/www 开头）
- 短链接（t.cn, dwz.cn 等 12 个短链域名）
- 广告关键词（扫码/加V/日入/代理等 20+ 词）
- 可疑 QQ 号（结合上下文判断）

动作：尝试撤回 + @警告
"""

import re

from nonebot import on_message, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from .config import plugin_config
from .storage import get_storage


# ============================================================
# 正则模式
# ============================================================

# URL 检测
URL_PATTERN = re.compile(
    r'https?://\S+|'
    r'(?:www\.)\S+\.\S+|'
    r'(?:[a-zA-Z0-9-]+\.)+(?:com|cn|net|org|xyz|top|vip|club|cc|'
    r'me|io|info|site|pw|ws|icu|ink|life)\S*',
    re.IGNORECASE,
)

# 短链接域名
SHORT_LINK_PATTERN = re.compile(
    r'(?:t\.cn|dwz\.cn|suo\.im|6du\.in|url\.cn|t\.co|bit\.ly|'
    r'is\.gd|ow\.ly|buff\.ly|soo\.gd|w\.url\.cn|u6v\.cn)\S*',
    re.IGNORECASE,
)

# QQ 号（5-11 位数字）
QQ_NUMBER_PATTERN = re.compile(r'(?:[^0-9]|^)(\d{5,11})(?:[^0-9]|$)')

# 广告关键词
AD_KEYWORD_PATTERN = re.compile(
    r'(扫码|加V|加微|加Q|日入|日赚|代理|白菜价|免费送|'
    r'点击领取|限时优惠|内部价|招代理|兼职招聘|'
    r'加群|加我|私聊|代发|接单|秒杀|拼团|返利|'
    r'刷单|好评返现|亏本甩卖|清仓|绝版|'
    r'注册送|推广|引流|变现|躺赚|网赚)',
    re.IGNORECASE,
)


# ============================================================
# 辅助函数
# ============================================================

def _check_qq_number(text: str) -> bool:
    """检查是否存在可疑 QQ 号"""
    matches = QQ_NUMBER_PATTERN.findall(text)
    if not matches:
        return False

    # 如果伴随广告关键词，则是广告
    if AD_KEYWORD_PATTERN.search(text):
        return True

    # 单个 QQ 号且消息很短 → 可疑
    if len(matches) == 1 and len(text.strip()) <= 15:
        return True

    return False


# ============================================================
# 消息处理器
# ============================================================
ad_detector = on_message(priority=3, block=False)


@ad_detector.handle()
async def handle_ad(bot: Bot, event: GroupMessageEvent):
    """检测广告/链接"""
    gid = str(event.group_id)
    uid = str(event.user_id)

    # 跳过管理员和群主
    if event.sender.role in ("admin", "owner"):
        return

    # 跳过白名单用户
    if uid in plugin_config.whitelist_users:
        return
    storage = get_storage()
    if storage.is_whitelisted(gid, uid):
        return

    text = event.get_plaintext().strip()
    if not text:
        return

    # 逐一检测
    match_reason = None
    if SHORT_LINK_PATTERN.search(text):
        match_reason = "短链接"
    elif URL_PATTERN.search(text):
        match_reason = "外部链接"
    elif AD_KEYWORD_PATTERN.search(text):
        match_reason = "疑似广告"
    elif _check_qq_number(text):
        match_reason = "疑似广告QQ号"

    if not match_reason:
        return

    # 尝试撤回消息
    try:
        await bot.delete_msg(message_id=event.message_id)
    except Exception:
        pass

    # 发送警告
    await bot.send_group_msg(
        group_id=event.group_id,
        message=(
            f"咕咕嘎嘎！[CQ:at,qq={uid}] 检测到{match_reason}，"
            f"请勿在群内发送广告内容。"
        ),
    )

    logger.info(
        f"[广告检测] 群:{gid} 用户:{uid} | "
        f"类型:{match_reason} | 原文:{text[:50]}"
    )
