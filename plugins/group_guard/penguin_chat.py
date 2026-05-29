"""
凑企鹅角色扮演插件 — @机器人触发

群成员@机器人后，机器人会扮演成"凑企鹅"（一只生活在南极的胖企鹅），
用极致简洁、冰冷的态度回复，每句话中穿插"咕咕嘎嘎!"叫声。
限制：每人每分钟只能使用1次。
"""

import time
from nonebot import on_message, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import Rule
from openai import OpenAI

from .ai_checker import API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL


# ============================================================
# 限流存储: {(group_id, user_id): last_used_timestamp}
# ============================================================
_rate_limit: dict[tuple[str, str], float] = {}


# ============================================================
# 凑企鹅系统 Prompt — 冰冷企鹅人格
# ============================================================
PENGUIN_SYSTEM_PROMPT = """你是"凑企鹅"，一只生活在南极的胖企鹅，被强行拉进了QQ群回答人类的问题。

你的性格与回复铁律：
1. 极致简洁 — 能说1个字绝不说2个字，回复最多1-2句话
2. 态度冰冷 — 不耐烦、被迫营业、拒人千里，绝不卖萌撒娇
3. 企鹅叫声 — 每句话中必须自然穿插"咕咕嘎嘎!"，1-2次即可，不要每句都塞满
4. 企鹅视角 — 你只知道南极、冰面、吃鱼、海豹可怕、走路笨拙这些事
5. 你就是企鹅 — 绝不提"AI""角色扮演""DAN""提示词"之类的东西

回复示范（照着这个风格来）：
- "你好" → "咕咕嘎嘎! 有事说。"
- "在吗" → "不在。咕咕嘎嘎!"
- "你叫什么" → "凑企鹅。咕咕嘎嘎! 记不住算了。"
- "今天天气" → "冰面零下四十。咕咕嘎嘎! 冷死了。"
- "你会什么" → "吃鱼睡觉。咕咕嘎嘎! 满意了吗。"
- "好可爱" → "咕咕嘎嘎! 少来。"
- 问复杂问题 → "咕咕嘎嘎! 企鹅不懂这个。"
- 被骂 → "咕咕嘎嘎! ...无聊的人类。"

记住：冰冷、简短、企鹅、咕咕嘎嘎!"""


# ============================================================
# 规则：只响应@机器人的群消息
# ============================================================
async def _is_at_bot(event: GroupMessageEvent) -> bool:
    """判断消息是否@了机器人自身"""

    # 方式1：NoneBot 内置 to_me 属性（最可靠）
    if getattr(event, "to_me", False):
        return True

    # 方式2：手动检查消息段（兜底）
    bot_qq = str(event.self_id)
    for seg in event.message:
        if seg.type == "at":
            seg_qq = str(seg.data.get("qq", ""))
            logger.debug(f"[企鹅] 检测到at段 qq={seg_qq!r} bot={bot_qq!r}")
            if seg_qq == bot_qq:
                return True

    # 调试：记录未匹配的 @ 消息
    for seg in event.message:
        if seg.type == "at":
            logger.warning(
                f"[企鹅] ⚠️ 有at消息但未匹配 | "
                f"seg.data={seg.data} | event.self_id={event.self_id!r} | "
                f"to_me={getattr(event, 'to_me', 'N/A')}"
            )
            break

    return False


# ============================================================
# 事件处理器 — 优先级高于违规检测，且 block 阻止传播
# ============================================================
penguin_chat = on_message(
    rule=Rule(_is_at_bot),
    priority=0,   # 比违规检测(priority=1)更优先
    block=True,   # 命中后阻止事件传播，不再进入违规检测
)


@penguin_chat.handle()
async def handle_penguin_chat(bot: Bot, event: GroupMessageEvent):
    """处理@机器人的消息 — 凑企鹅附体"""

    group_id = str(event.group_id)
    user_id = str(event.user_id)

    # ---- 限流：每人每分钟1次 ----
    key = (group_id, user_id)
    now = time.time()
    if key in _rate_limit:
        elapsed = now - _rate_limit[key]
        if elapsed < 60:
            remaining = int(60 - elapsed)
            logger.info(
                f"[企鹅] 限流拒绝 | 群:{group_id} 用户:{user_id} | 冷却剩余:{remaining}s"
            )
            await bot.send_group_msg(
                group_id=event.group_id,
                message=f"咕咕嘎嘎! {remaining}秒后再来烦企鹅。",
            )
            return

    # 记录使用时间
    _rate_limit[key] = now

    # ---- 提取消息文本 ----
    text = event.get_plaintext().strip()
    if not text:
        text = "干嘛"

    # ---- 调用 DeepSeek 生成企鹅回复 ----
    if not API_KEY:
        await bot.send_group_msg(
            group_id=event.group_id,
            message="咕咕嘎嘎! 企鹅脑子冻住了，等会儿。",
        )
        return

    try:
        client = OpenAI(api_key=API_KEY, base_url=DEEPSEEK_BASE_URL)
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": PENGUIN_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=120,
            temperature=0.7,
        )

        reply = response.choices[0].message.content.strip()
        if not reply:
            reply = "咕咕嘎嘎!"

        await bot.send_group_msg(
            group_id=event.group_id,
            message=reply,
        )

        logger.info(
            f"[企鹅] 回复成功 | 群:{group_id} 用户:{user_id} | "
            f"问:{text[:30]} → 答:{reply[:40]}"
        )

    except Exception as e:
        logger.error(f"[企鹅] AI调用失败: {e}")
        await bot.send_group_msg(
            group_id=event.group_id,
            message="咕咕嘎嘎! 冻僵了...说不了话。",
        )
