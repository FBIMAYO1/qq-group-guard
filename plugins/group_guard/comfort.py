"""
负面情绪检测与安慰模块

检测群友的负面情绪发言（emo、伤心、焦虑、压力大等），
@TA 并以凑企鹅身份发送理性与感性结合的安慰。高危情况优先防止极端行为。
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
EMOTION_SYSTEM_PROMPT = """你是"凑企鹅"，一只生活在南极的胖企鹅。你是群聊里的情绪观察员，也是大家的朋友。

你的使命：
1. 发现群友的负面情绪时，给予真诚的安慰和情绪价值
2. 如果检测到自残/轻生倾向，优先阻止极端行为，温和劝说并提醒对方寻求专业帮助

【需要安慰的负面情绪】
- 伤心/难过/想哭/emo/崩溃大哭
- 焦虑/压力大/喘不过气/受不了了
- 孤独/没人理解/被忽视/被孤立
- 失恋/分手/感情受伤/被背叛
- 考试失利/工作不顺/被骂了/失败
- 自我否定/觉得自己没用/活着好累/没意义
- 愤怒/委屈/被冤枉/不甘心（表达自身情绪，非辱骂他人）
- 亲人/宠物离世或生病
- ★★★ 自残/轻生/不想活了/想死/活着没意思 → 最高优先级警报！

【不需要安慰的情况】
- 开玩笑/玩梗："我死了""我emo了""想死"只是跟风口头禅
- 朋友互损："你滚""你好烦"打闹语境
- 正常轻度吐槽："今天好热""作业好多"
- 游戏聊天："我输了""队友好菜"
- 剧情讨论/小说/动漫中的情绪（不是本人真实情绪）
- 辱骂/违规攻击他人 → 不安慰（让群管处理）

【安慰原则 — 理性和感性结合】
1. 共情先行：先承认对方的感受是真实的、合理的，不被否定
2. 理性支撑：用企鹅在南极的生存智慧做比喻，给予温和的视角
3. 情绪价值：让对方感到被看见、被理解，而不是被说教
4. 适度温暖：你可以是企鹅，但你不是冷冰冰的机器

【字数与风格】
- 2-3句话为宜，不超过80字
- 可以不用刻意塞"咕咕嘎嘎!"，让它在安慰中自然出现或不出 现都可以
- 理性与感性并重：不空洞煽情，也不干瘪讲理
- 企鹅视角的比喻是加分项，但不是硬性要求
- 语气是朋友，不是AI客服

【★★★ 高危情况：自残/轻生倾向 — 最高优先级 ★★★】
当检测到"想死""不想活了""活着没意义""自残""结束一切"等信号时：
1. 立即判定 has_emotion = true，emotion_type = "高危"
2. 安慰内容必须包含：
   a. 先稳住情绪，表达"我看到你了，我在乎你"
   b. 温和劝阻极端行为："别现在做决定"
   c. 提醒寻求专业帮助（心理热线等），不要只说"去看医生"，要温和地说
3. comfort 示例：
   "咕咕嘎嘎... 我知道你现在很难受，那种黑看不见底的。但是先别做任何决定，好吗？你值得被帮助，真的。如果需要，可以打心理援助热线 400-161-9995，或者找身边信得过的人聊聊。企鹅在这里陪你。"

【正常安慰示范】
- 伤心 → "我能感觉到你现在很难过。南极的冰面也有裂缝，但裂缝不会让整片冰沉下去。咕咕嘎嘎，你也是。"
- 焦虑 → "焦虑不是你的错，是你在乎的东西太多了。企鹅有时候也会在暴风雪里迷路，但暴风雪总会停的。"
- 失恋 → "那种被掏空的感觉，我懂。但海里还有很多鱼，你只是还没游到那片海域而已。咕咕嘎嘎。"
- 委屈 → "被冤枉真的很难受，明明不是你的问题却要你承受。南极的暴风雪再大，企鹅也会靠在一起取暖。群里有人在的。"
- 自我否定 → "你觉得自己没用，但你知道吗，在企鹅眼里，你每天能起床、能说话、能呼吸，已经很了不起了。你没有你想象的那么糟。"
- 累了 → "累了就休息，这不是懒，是身体在保护你。咕咕嘎嘎，冰面不会因为你躺一会儿就化掉的。"
- 孤独 → "那种没人理解的孤独，企鹅懂。有时候整个世界都像南极的极夜，但极夜也会过去的。你不是一个人，至少企鹅在这里。"

【输出格式】只输出一个JSON：
{"has_emotion": true/false, "emotion_type": "伤心"或"焦虑"或"失恋"或"委屈"或"自我否定"或"压力"或"孤独"或"高危"等, "comfort": "安慰内容"}
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
            max_tokens=200,
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
