"""
早安短报模块

每天早上8:00 @全体成员发送早安短报，包含：
1. 当天日期 + 问候语
2. 今日热点新闻（3-5条）
3. 距离最近法定节假日的倒计时
"""

import asyncio
import json
from datetime import datetime, date, timedelta

import httpx
from nonebot import on_message, get_driver, get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent

from .group_config import get_group_config


# ============================================================
# 法定节假日
# ============================================================
HOLIDAYS_2026 = [
    ("元旦",       date(2026, 1,  1),  "🎉 新的一年开始啦"),
    ("春节",       date(2026, 2, 17),  "🧧 新春快乐，阖家团圆"),
    ("清明节",     date(2026, 4,  5),  "🌿 踏青祭祖，缅怀先人"),
    ("劳动节",     date(2026, 5,  1),  "💪 致敬每一位劳动者"),
    ("端午节",     date(2026, 6, 19),  "🐲 粽叶飘香，龙舟竞渡"),
    ("中秋节",     date(2026, 9, 25),  "🌕 月圆人团圆"),
    ("国庆节",     date(2026, 10, 1),  "🇨🇳 祖国生日快乐"),
    # 2027年
    ("元旦",       date(2027, 1,  1),  "🎉 新的一年开始啦"),
    ("春节",       date(2027, 2,  6),  "🧧 新春快乐，阖家团圆"),
    ("清明节",     date(2027, 4,  5),  "🌿 踏青祭祖，缅怀先人"),
    ("劳动节",     date(2027, 5,  1),  "💪 致敬每一位劳动者"),
    ("端午节",     date(2027, 6,  9),  "🐲 粽叶飘香，龙舟竞渡"),
    ("中秋节",     date(2027, 9, 15),  "🌕 月圆人团圆"),
    ("国庆节",     date(2027, 10, 1),  "🇨🇳 祖国生日快乐"),
]

# 新闻API列表（并行请求，合并去重后取TOP N）
# orz.ai 每日热点 API — 免费，约半小时刷新
NEWS_SOURCES = [
    ("orz_baidu",  "https://orz.ai/api/v1/dailynews?platform=baidu"),
    ("orz_weibo",  "https://orz.ai/api/v1/dailynews?platform=weibo"),
    ("orz_zhihu",  "https://orz.ai/api/v1/dailynews?platform=zhihu"),
]

NEWS_COUNT = 5  # 最多展示5条新闻


# ============================================================
# 新闻获取
# ============================================================

def _parse_orz(data: dict) -> list[str]:
    """解析 orz.ai 返回格式: {status:"200", data:[{title:"xxx"}, ...]}"""
    if str(data.get("status")) != "200":
        return []
    items = data.get("data", [])
    headlines = []
    for item in items:
        title = item.get("title", "").strip()
        if title:
            headlines.append(title)
    return headlines


async def _fetch_news() -> list[str]:
    """并行请求多个平台，合并去重后取 TOP N 条"""

    async def _fetch_one(name: str, url: str) -> list[str]:
        """请求单个平台并解析"""
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                resp = await client.get(url, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                })
                if resp.status_code != 200:
                    logger.warning(f"[早报] {name} 返回 {resp.status_code}")
                    return []
                data = resp.json()
                headlines = _parse_orz(data)
                if headlines:
                    logger.info(f"[早报] ✅ {name} 获取到 {len(headlines)} 条")
                else:
                    logger.warning(f"[早报] {name} 解析结果为空")
                return headlines
        except Exception as e:
            logger.warning(f"[早报] {name} 请求失败: {e}")
            return []

    # 并行请求所有平台（ensure_future + await，避免 gather 兼容性问题）
    futures = [asyncio.ensure_future(_fetch_one(name, url)) for name, url in NEWS_SOURCES]
    results = [await f for f in futures]

    # 合并去重（按前缀30字去重，避免同条新闻标题略有差异）
    seen: set[str] = set()
    merged: list[str] = []
    for headlines in results:
        for h in headlines:
            key = h[:30]
            if key not in seen:
                seen.add(key)
                merged.append(h)

    if merged:
        logger.info(f"[早报] 合并去重后共 {len(merged)} 条，取前 {NEWS_COUNT} 条")
        return merged[:NEWS_COUNT]

    return []


# ============================================================
# 节假日计算
# ============================================================

def _get_nearest_holiday(today: date) -> tuple[str, int, str]:
    """
    找到今天之后最近的法定节假日

    Returns:
        (节日名, 距离天数, emoji描述)
    """
    nearest = None
    nearest_days = 99999

    for name, d, desc in HOLIDAYS_2026:
        if d >= today:
            days = (d - today).days
            if days < nearest_days:
                nearest_days = days
                nearest = (name, desc)

    if nearest is None:
        # 所有节日都已过 → 指向明年元旦
        next_new_year = date(today.year + 1, 1, 1)
        days = (next_new_year - today).days
        return ("元旦", days, "🎉 新的一年即将到来")

    if nearest_days == 0:
        suffix = "就是今天！"
    else:
        suffix = f"还有 {nearest_days} 天"

    return (nearest[0], nearest_days, nearest[1])


# ============================================================
# 构建早报文本
# ============================================================

async def get_brief() -> str:
    """获取早报内容（供外部命令调用）"""
    return await _build_brief()


async def _build_brief() -> str:
    """构建早安短报完整内容"""
    today = date.today()
    today_str = today.strftime("%Y年%m月%d日")
    weekday = ["一", "二", "三", "四", "五", "六", "日"][today.weekday()]
    holiday_name, holiday_days, holiday_desc = _get_nearest_holiday(today)

    # 问候语
    lines = [f"☀️ @全体成员 早上好！今天是 {today_str} 星期{weekday}", ""]

    # 新闻速报
    headlines = await _fetch_news()
    if headlines:
        lines.append("📰 今日速报")
        for i, h in enumerate(headlines, 1):
            lines.append(f"  {i}. {h}")
    else:
        lines.append("📰 今日速报")
        lines.append("  （暂未获取到新闻，请稍后查看）")

    lines.append("")

    # 节假日倒计时
    if holiday_days == 0:
        lines.append(f"🎊 今天是{holiday_name}！{holiday_desc}")
    else:
        lines.append(f"📅 距离【{holiday_name}】还有 {holiday_days} 天")
        lines.append(f"   {holiday_desc}")

    return "\n".join(lines)


# ============================================================
# 记录已发送的群 — 防止重启后重复发
# ============================================================
# 收集所有活跃群号
_active_groups: set[str] = set()


# 注意：与 brainwash.py 的 member_collector (priority=99) 同时运行，
# 两者独立收集，可考虑未来合并为一个统一的元数据收集器
group_collector = on_message(priority=99, block=False)


@group_collector.handle()
async def _collect_group(event: GroupMessageEvent):
    """记录所有出现过消息的群"""
    _active_groups.add(str(event.group_id))


# ============================================================
# 定时早报任务
# ============================================================
async def _morning_brief_loop():
    """每天早上8:00发送早报"""
    await asyncio.sleep(8)

    last_send_date = ""

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # 新的一天
            if today_str != last_send_date:
                # 等到了8点再发
                pass

            # 检查是否到了8:00（±4分钟窗口，避免因高负载错过）
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

                # 获取早报内容（含新闻请求）
                brief = await _build_brief()

                # 发送到所有已知的群
                groups = list(_active_groups)
                if not groups:
                    logger.warning("[早报] 没有已知的活跃群")
                else:
                    sent_count = 0
                    gcfg = get_group_config()
                    for gid in groups:
                        # 检查功能开关 — 该群是否开启了早安短报
                        if not gcfg.get(gid).morning_brief_enabled:
                            logger.info(f"[早报] 群{gid} 已关闭早安短报，跳过")
                            continue
                        try:
                            await bot.send_group_msg(
                                group_id=int(gid),
                                message=brief,
                            )
                            sent_count += 1
                            await asyncio.sleep(1.5)  # 群间间隔，避免风控
                        except Exception as e:
                            logger.error(f"[早报] 群{gid}发送失败: {e}")

                    logger.info(f"[早报] ✅ 已发送到 {sent_count}/{len(groups)} 个群")

        except Exception as e:
            logger.error(f"[早报] 后台异常: {e}")

        await asyncio.sleep(60)  # 每分钟检查一次


# ============================================================
# 注册启动钩子
# ============================================================
_driver = get_driver()


@_driver.on_startup
async def _start_morning_brief():
    """NoneBot启动后拉起早安短报任务"""
    asyncio.create_task(_morning_brief_loop())
    logger.info("[早报] 📰 早安短报模块已启动，每天早上8:00发送")
