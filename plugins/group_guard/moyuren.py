"""
摸鱼人日历模块

替代旧的纯文本「早安短报」：调用 moyuren_server 公开 API 获取每日
摸鱼人日历图片（JPG），并配一段从结构化数据生成的智能文字。

数据来源：MR-MonkeyRay/moyuren_server 的公开 API
  - 图片本身已整合：日期+农历+节气、60秒新闻、节日倒计时、周末倒计时、
    趣味内容、疯狂星期四KFC、大盘指数、金价、每日英语、周/月/年进度
  - 文字附言（本模块生成）：周末倒计时、趣味一言、周四自动带 KFC 文案

API 地址可在 settings.py / .env (MOYUREN_API_URL) 覆盖，将来想自建随时换。

对外接口：
    msg = await get_moyuren_message()   # Message | None；API 挂时返回 None
"""

import httpx
from nonebot import logger
from nonebot.adapters.onebot.v11 import Message, MessageSegment

from .settings import MOYUREN_API_URL


# ============================================================
# API 调用
# ============================================================

async def fetch_detail() -> dict | None:
    """请求摸鱼日历详情数据（含图片 url 与结构化字段）。

    Returns:
        detail dict（含 image / weekday / lunar_date / weekend /
        solar_term / fun_content / is_crazy_thursday / kfc_content 等），
        失败时返回 None（优雅降级）。
    """
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                MOYUREN_API_URL,
                params={"encode": "json", "detail": "true"},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                },
            )
            if resp.status_code != 200:
                logger.warning(f"[摸鱼日历] API 返回 {resp.status_code}")
                return None
            data = resp.json()
            if not isinstance(data, dict) or not data.get("image"):
                logger.warning("[摸鱼日历] 响应缺少 image 字段")
                return None
            return data
    except Exception as e:
        logger.warning(f"[摸鱼日历] 请求失败: {e}")
        return None


# ============================================================
# 文字附言构建
# ============================================================

def build_caption(d: dict) -> str:
    """从详情数据拼一段简短附言。所有字段都用 .get() 兜底，缺失项跳过。"""
    lines: list[str] = []

    # 头部：日期 + 星期 + 农历
    date_str = d.get("date", "")
    weekday = d.get("weekday", "")
    header = f"☀️ 摸鱼日历 · {date_str}".rstrip()
    if weekday:
        header += f" {weekday}"
    lines.append(header)

    lunar = d.get("lunar_date", "")
    if lunar:
        lines.append(f"🌙 农历{lunar}")

    # 周末倒计时
    weekend = d.get("weekend") or {}
    if weekend.get("is_weekend"):
        lines.append("🎉 今天就是周末，好好摸鱼！")
    else:
        days_left = weekend.get("days_left")
        if isinstance(days_left, int):
            if days_left == 0:
                lines.append("🎉 今天就是周末，好好摸鱼！")
            else:
                lines.append(f"⏳ 距离周末还有 {days_left} 天")

    # 节气（临近时才提示）
    term = d.get("solar_term") or {}
    term_name = term.get("name")
    term_days = term.get("days_left")
    if term_name and isinstance(term_days, int):
        if term.get("is_today") or term_days == 0:
            lines.append(f"🌿 今日节气：{term_name}")
        elif term_days == 1:
            lines.append(f"🌿 明天{term_name}")

    # 趣味一言
    fun = d.get("fun_content") or {}
    fun_text = fun.get("text")
    if fun_text:
        title = fun.get("title", "💬")
        lines.append(f"{title}：{fun_text}")

    # 疯狂星期四
    if d.get("is_crazy_thursday"):
        kfc = d.get("kfc_content")
        if kfc:
            lines.append(f"🍗 疯狂星期四：{kfc}")

    return "\n".join(lines)


# ============================================================
# 对外：组装图文消息
# ============================================================

async def get_moyuren_message() -> Message | None:
    """获取可直接发送的摸鱼日历图文消息。

    Returns:
        Message（图片段 + 文字附言），API 不可用时返回 None。
    """
    detail = await fetch_detail()
    if not detail:
        return None

    image_url = detail.get("image")
    if not image_url:
        return None

    caption = build_caption(detail)
    msg = Message(MessageSegment.image(image_url))
    if caption:
        msg += MessageSegment.text("\n" + caption)
    return msg
