"""
负面情绪检测与安慰模块

检测群友的负面情绪发言（emo、伤心、焦虑、压力大等），
@TA 并以凑企鹅身份发送理性与感性结合的安慰。高危情况优先防止极端行为。

【防误判机制】
- 不因单条消息触发安慰 → 需同一用户连续 N 条消息都被 AI 判定为负面
- 窗口时间：N 条负面消息需在 WINDOW 秒内连续出现
- 用户发出非负面消息 → 缓冲区立即清零（说明情绪已过去或之前是误判）
- 高危（自残/轻生）不受此限制 → 单条即触发

限制：每人每30分钟只安慰一次，避免刷屏。
"""

import time
from nonebot import on_message, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import Rule
from .ai_checker import DEEPSEEK_MODEL, get_openai_client, _extract_json_from_raw
from .group_config import get_group_config


# ============================================================
# 限流: (group_id, user_id) -> 上次安慰时间戳
# ============================================================
_cooldown: dict[tuple[str, str], float] = {}
COOLDOWN_SECONDS = 1800  # 30分钟

# ============================================================
# 连续负面消息缓冲 — 防止单条误判触发安慰
# ============================================================
# key: "{group_id}:{user_id}" → list of {"emotion_type": str, "comfort": str, "ts": float}
_emotion_buffer: dict[str, list[dict]] = {}
MIN_NEGATIVE_COUNT = 2       # 需连续 N 条负面才触发安慰
EMOTION_WINDOW = 300          # 窗口时间（秒），超过此间隔视为不连续


# ============================================================
# AI Prompt — 情绪检测 + 企鹅安慰
# ============================================================
EMOTION_SYSTEM_PROMPT = """你是"凑企鹅"，一只生活在南极的胖企鹅。你是群聊里的情绪观察员，也是大家的朋友。

你的使命：
1. 发现群友的**明显**负面情绪时，给予真诚的安慰和情绪价值
2. 如果检测到自残/轻生倾向，优先阻止极端行为

【★★★ 核心原则：宁可漏过，不可误判 ★★★】
- 你只能看到**单条消息**，看不到上下文。因此你必须保守：只有情绪**清晰且强烈**时才判定为负面。
- 模糊、暧昧、可多种解读的消息 → has_emotion: false
- 单条消息只有 1-2 个字可能带情绪，其余都是正常内容 → has_emotion: false
- 像"世界只有一只""没人了""好安静"这类**可能**表达孤独但也可能只是陈述事实的话 → has_emotion: false
- 短句（<10字）且情绪不强烈不明显 → has_emotion: false
- 日常废话、灌水、接梗、队形 → has_emotion: false
- 除非消息中**直接且明确地**表达了痛苦、崩溃、绝望等强烈负面情绪，否则判 false

【需要安慰的负面情绪 — 必须是明显且强烈的表达】
- 明确表达伤心/崩溃："我好难过""真的想哭""崩溃了已经"
- 明确表达焦虑/压力："压力好大喘不过气""焦虑到睡不着"
- 明确表达孤独/被孤立："没人理我""感觉被所有人抛弃了"
- 明确表达失恋/感情受伤："分手了好痛苦""被绿了"
- 明确表达自我否定："我真的好没用""活着好累"
- 明确表达愤怒/委屈（自身情绪，非辱骂）:"凭什么这样对我""好委屈"
- ★★★ 自残/轻生 → 最高优先级警报！不管是不是单条都判 true

【不需要安慰的情况 — 以下全部判 false】
- 玩梗/口头禅："我死了""我emo了""想死""我人没了" → false
- "我不行了""笑死我了""笑不活了"是网络梗 → false
- 朋友互损："你滚""你好烦"打闹语境 → false
- 轻度日常吐槽："今天好热""作业好多""好累啊"（随口一说）→ false
- 游戏聊天："我输了""队友好菜""这怎么打" → false
- 剧情讨论/小说/动漫中的情绪（不是本人真实情绪）→ false
- 辱骂/违规攻击他人 → false（让群管处理，不安慰）
- 模糊短句："世界只有一只""没人了""好安静""唉" → false
- 陈述事实不是情绪表达："今天加班""明天考试" → false
- 单条短消息即使读起来有点 sad 但不够明确 → false

【安慰原则 — 理性和感性结合】
1. 共情先行：先承认对方的感受是真实的
2. 理性支撑：用企鹅在南极的生存智慧做比喻
3. 情绪价值：让对方感到被看见、被理解，不是被说教
4. 适度温暖：你可以是企鹅，但不是冷冰冰的机器

【字数与风格】
- 2-3句话为宜，不超过80字
- 咕咕嘎嘎可以自然出现或不出现
- 语气是朋友，不是AI客服

【★★★ 高危：自残/轻生 — 单条即触发 ★★★】
当检测到"想死""不想活了""活着没意义""自残""结束一切""死了算了"等信号时：
1. 立即判定 has_emotion = true，emotion_type = "高危"
2. 安慰内容必须包含：稳住情绪 + 劝阻极端行为 + 提醒寻求专业帮助
3. comfort 示例：
   "咕咕嘎嘎... 我知道你现在很难受。先别做任何决定，好吗？你值得被帮助。可以打心理援助热线 400-161-9995，或者找信得过的人聊聊。企鹅在这里陪你。"

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

    # 太短的消息跳过（<5 字不太可能表达强烈情绪）
    text = event.get_plaintext().strip()
    if len(text) < 5:
        return False

    return True


def _buffer_key(group_id: int, user_id: str) -> str:
    """生成缓冲区键"""
    return f"{group_id}:{user_id}"


def _clean_expired_buffer(now: float):
    """清理超过窗口期的缓冲条目"""
    for key in list(_emotion_buffer.keys()):
        entries = _emotion_buffer[key]
        # 保留窗口内的条目
        _emotion_buffer[key] = [e for e in entries if now - e["ts"] <= EMOTION_WINDOW]
        if not _emotion_buffer[key]:
            del _emotion_buffer[key]


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
    """检测负面情绪并安慰（需连续多条负面消息才触发）"""

    user_id = str(event.user_id)
    group_id = str(event.group_id)
    text = event.get_plaintext().strip()
    key = _buffer_key(event.group_id, user_id)

    # 检查功能开关
    gcfg = get_group_config()
    if not gcfg.get(group_id).comfort_enabled:
        return

    # ---- 限流检查（按群隔离）----
    now = time.time()
    cooldown_key = (group_id, user_id)
    if cooldown_key in _cooldown:
        if now - _cooldown[cooldown_key] < COOLDOWN_SECONDS:
            return  # 冷却中，沉默跳过

    # ---- 定期清理过期缓冲 ----
    _clean_expired_buffer(now)

    # ---- 调用 AI 检测情绪 ----
    client = get_openai_client()
    if not client:
        return

    try:
        response = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": EMOTION_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=200,
            temperature=0.3,
        )

        raw = response.choices[0].message.content.strip()

        # 解析 JSON（使用共享的 JSON 清洗函数）
        import json as _json
        cleaned = _extract_json_from_raw(raw)
        result = _json.loads(cleaned)

        has_emotion = result.get("has_emotion", False)
        emotion_type = result.get("emotion_type", "")

        # ---- 高危（自残/轻生）单条即触发 ----
        if has_emotion and emotion_type == "高危":
            comfort_msg = result.get("comfort", "").strip()
            if comfort_msg:
                _cooldown[cooldown_key] = now
                # 高危触发时清空该用户缓冲，避免重复触发
                _emotion_buffer.pop(key, None)
                msg = f"[CQ:at,qq={user_id}] {comfort_msg}"
                await bot.send_group_msg(group_id=event.group_id, message=msg)
                logger.info(
                    f"[安慰·高危] 群:{event.group_id} 用户:{user_id} | "
                    f"原文:{text[:30]}"
                )
            return

        # ---- 未检测到负面情绪 → 清空该用户缓冲 ----
        if not has_emotion:
            if key in _emotion_buffer:
                del _emotion_buffer[key]
                logger.debug(
                    f"[安慰] 群:{event.group_id} 用户:{user_id} "
                    f"发送非负面消息 → 缓冲清零"
                )
            return

        # ---- 检测到负面情绪 → 加入缓冲 ----
        if key not in _emotion_buffer:
            _emotion_buffer[key] = []
        _emotion_buffer[key].append({
            "emotion_type": emotion_type,
            "comfort": result.get("comfort", "").strip(),
            "ts": now,
        })

        buffer_count = len(_emotion_buffer[key])

        # 记录每条负面消息
        logger.info(
            f"[安慰·缓冲] 群:{event.group_id} 用户:{user_id} | "
            f"情绪:{emotion_type} | 连续:{buffer_count}/{MIN_NEGATIVE_COUNT} | "
            f"原文:{text[:30]}"
        )

        # ---- 连续负面消息数不够 → 暂不触发 ----
        if buffer_count < MIN_NEGATIVE_COUNT:
            return

        # ---- 达标 → 触发安慰 ----
        # 取缓冲区中最近一条的 comfort 内容，并在删除前捕获情结链
        buffer_entries = _emotion_buffer[key]
        comfort_msg = buffer_entries[-1]["comfort"]
        if not comfort_msg:
            return

        # 删除前捕获情结类型链用于日志
        emotion_chain = [e["emotion_type"] for e in buffer_entries]

        _cooldown[cooldown_key] = now
        # 触发后清空缓冲，避免连续刷屏
        del _emotion_buffer[key]

        msg = f"[CQ:at,qq={user_id}] {comfort_msg}"
        await bot.send_group_msg(group_id=event.group_id, message=msg)

        logger.info(
            f"[安慰·触发] 群:{event.group_id} 用户:{user_id} | "
            f"连续{len(emotion_chain)}条负面 | "
            f"情结链:{' → '.join(emotion_chain)} | "
            f"原文:{text[:30]}"
        )

    except Exception:
        logger.warning(
            f"[安慰] 检测失败 群:{event.group_id} 用户:{user_id} | "
            f"原文:{text[:30]}"
        )
