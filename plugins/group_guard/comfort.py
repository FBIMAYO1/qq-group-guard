"""
负面情绪检测与安慰模块

检测群友的负面情绪发言（emo、伤心、焦虑、压力大等），
@TA 并以凑企鹅风格发送一句简短冰冷但温暖的安慰。
限制：每人每30分钟只安慰一次，避免刷屏。
"""

import time
from nonebot import on_message, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import Rule
from openai import OpenAI

from .ai_checker import API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL


# ============================================================
# 限流: user_id -> 上次安慰时间戳
# ============================================================
_cooldown: dict[str, float] = {}
COOLDOWN_SECONDS = 1800  # 30分钟


# ============================================================
# AI Prompt — 情绪检测 + 企鹅安慰
# ============================================================
EMOTION_SYSTEM_PROMPT = """你是"凑企鹅"，一只生活在南极的胖企鹅，同时也是群聊的情绪观察员。

你的任务：
1. 判断群友发言是否含有明显的负面情绪
2. 如果有，用你冰冷但关心的企鹅风格，写一句极简安慰（1句话，含"咕咕嘎嘎!"）

【需要安慰的负面情绪】
- 伤心/难过/想哭/emo
- 焦虑/压力大/崩溃/受不了了
- 孤独/没人理解/被忽视
- 失恋/分手/感情受伤
- 考试失利/工作不顺/被骂了
- 自我否定/觉得自己没用/活着好累
- 愤怒/委屈/被冤枉（非辱骂他人，是表达自身情绪）
- 亲人/宠物离世或生病

【不需要安慰的情况】
- 开玩笑/玩梗："我死了""我emo了"只是跟风说
- 朋友互损："你滚""你好烦"打闹
- 正常吐槽："今天好热""作业好多"轻度吐槽
- 游戏聊天："我输了""队友好菜"
- 剧情讨论/小说/动漫情绪（不是本人情绪）
- 已经包含辱骂/违规的内容 → 不安慰（让群管处理）

【安慰风格】
- 凑企鹅式：冰冷开头，但话里有温度
- 极短：15字以内，1句话
- 必须含"咕咕嘎嘎!"
- 不需要长篇大论，不需要讲道理

正确示范：
- 伤心 → "咕咕嘎嘎! 冰面也有裂缝，但不会碎。"
- 焦虑 → "咕咕嘎嘎! 企鹅走路也摔跤，没事。"
- 失恋 → "咕咕嘎嘎! 海里有的是鱼。"
- 委屈 → "咕咕嘎嘎! 南极的暴风雪也会停。"
- 自我否定 → "咕咕嘎嘎! 企鹅觉得你挺好的。"
- 累了 → "咕咕嘎嘎! 歇会儿，冰面又不会跑。"

【输出格式】只输出一个JSON：
{"has_emotion": true/false, "emotion_type": "伤心"或"焦虑"等, "comfort": "安慰内容"}
{"has_emotion": false, "emotion_type": "", "comfort": ""}"""


# ============================================================
# 规则：群消息、非管理员、内容够长
# ============================================================
async def _should_detect_emotion(event: GroupMessageEvent) -> bool:
    """判断是否需要做情绪检测"""
    # 跳过管理员/群主（不检测管理层情绪）
    if event.sender.role in ("admin", "owner"):
        return False

    # 跳过机器人自己
    if str(event.user_id) == str(event.self_id):
        return False

    # 太短的消息跳过
    text = event.get_plaintext().strip()
    if len(text) < 5:
        return False

    return True


# ============================================================
# 事件处理器
# ============================================================
emotion_detector = on_message(
    rule=Rule(_should_detect_emotion),
    priority=2,    # 低于违规检测(1)，高于普通消息
    block=False,   # 不阻塞，消息继续流转
)


@emotion_detector.handle()
async def handle_emotion(bot: Bot, event: GroupMessageEvent):
    """检测负面情绪并安慰"""

    user_id = str(event.user_id)
    text = event.get_plaintext().strip()

    # ---- 限流检查 ----
    now = time.time()
    if user_id in _cooldown:
        if now - _cooldown[user_id] < COOLDOWN_SECONDS:
            return  # 冷却中，沉默跳过

    # ---- 调用 AI 检测情绪 ----
    if not API_KEY:
        return

    try:
        client = OpenAI(api_key=API_KEY, base_url=DEEPSEEK_BASE_URL)
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": EMOTION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=80,
            temperature=0.3,
        )

        raw = response.choices[0].message.content.strip()

        # 解析 JSON
        import json as _json
        import re as _re

        # 清理可能的 markdown 标记
        cleaned = raw
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

        result = _json.loads(cleaned)

        if not result.get("has_emotion"):
            return

        comfort_msg = result.get("comfort", "").strip()
        if not comfort_msg:
            return

        # ---- 发送安慰 ----
        _cooldown[user_id] = now

        msg = f"[CQ:at,qq={user_id}] {comfort_msg}"
        await bot.send_group_msg(group_id=event.group_id, message=msg)

        logger.info(
            f"[安慰] 群:{event.group_id} 用户:{user_id} | "
            f"情绪:{result.get('emotion_type')} | "
            f"原文:{text[:30]}"
        )

    except Exception:
        # 情绪检测失败不打扰用户（静默忽略）
        pass
