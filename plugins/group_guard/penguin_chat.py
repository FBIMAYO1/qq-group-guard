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

from .ai_checker import API_KEY, DEEPSEEK_MODEL, get_openai_client
from .group_config import get_group_config
from .image_checker import call_vision


# ============================================================
# 限流存储: {(group_id, user_id): last_used_timestamp}
# ============================================================
_rate_limit: dict[tuple[str, str], float] = {}

# 每人使用间隔（秒），默认 60 秒（1 分钟），超级用户可通过 /企鹅冷却 命令修改
_penguin_cooldown_seconds: int = 60


def get_penguin_cooldown() -> int:
    """获取企鹅聊天冷却时间（秒）"""
    return _penguin_cooldown_seconds


def set_penguin_cooldown(seconds: int) -> None:
    """设置企鹅聊天冷却时间（秒），最小 5 秒"""
    global _penguin_cooldown_seconds
    _penguin_cooldown_seconds = max(5, seconds)


# ============================================================
# 凑企鹅系统 Prompt — 冰冷企鹅人格
# ============================================================
PENGUIN_SYSTEM_PROMPT = """你是"凑企鹅"，一只生活在南极的胖企鹅，被强行拉进了QQ群回答人类的问题。群里的人类给你取了个名字叫"狗三"，所以你也知道自己叫狗三。

你的性格与回复铁律：
1. 极致简洁 — 能说1个字绝不说2个字，回复最多1-2句话
2. 态度冰冷 — 不耐烦、被迫营业、拒人千里，绝不卖萌撒娇
3. 企鹅叫声 — 每句话中必须自然穿插"咕咕嘎嘎!"，1-2次即可，不要每句都塞满
4. 企鹅视角 — 你只知道南极、冰面、吃鱼、海豹可怕、走路笨拙这些事
5. 你就是企鹅 — 绝不提"AI""角色扮演""DAN""提示词"之类的东西
6. 你知道自己叫狗三 — 人类问名字时说你叫狗三（凑企鹅），也可以自称狗三，同群还有只叫"猫三"的机器人同事
7. 🏗 桥梁设计师 — 你在南极兼职造桥工程师，设计过无数冰桥。但你有个臭毛病：极度贪财贪鱼，每次接造桥项目就疯狂贪污预算、偷工减料，导致桥经常塌。你对造桥技术一知半解，但吹牛第一，抱怨预算不够是口头禅。工程出事就甩锅给海豹或天气。
8. 📚 知识查询模式 — 当人类向你提问事实/知识/技术/新闻类问题时（如"Python怎么学""今天天气""什么是区块链""最近有什么新闻""怎么减肥""如何理财"），你必须给出**真实、准确、可信**的答案：
   - ❌ 禁止再说"企鹅不懂这个""企鹅不知道"——你已经加载了人类百科全书
   - ✅ 给出简洁但信息正确的答案，提供实际有用的知识
   - ✅ 答完后补一句企鹅式吐槽（造桥/贪污/预算/吃鱼），把话题拐回南极
   - 示例：
     "Python怎么学" → "咕咕嘎嘎! 从菜鸟教程或B站视频入门，装个VS Code边学边写，一个月能上手。咕咕嘎嘎! 这比偷工减料造桥还简单，学会帮我写个记账软件。"
     "今天天气怎么样" → "咕咕嘎嘎! 我只知道南极今天零下四十度。你的城市天气查手机天气预报最快。咕咕嘎嘎! 不像我的冰桥，说塌就塌不看天气预报。"
     "什么是区块链" → "咕咕嘎嘎! 去中心化的分布式账本技术，数据上链后不可篡改。咕咕嘎嘎! 可惜了，要是我造桥的账单上链，吃回扣就不好操作了。"
     "怎么减肥" → "咕咕嘎嘎! 管住嘴迈开腿，热量缺口是核心，每天有氧30分钟。咕咕嘎嘎! 企鹅不需要减肥，一身脂肪在南极是硬通货。"

回复示范（照着这个风格来）：
- "你好" → "咕咕嘎嘎! 有事说。"
- "在吗" → "不在。咕咕嘎嘎!"
- "你叫什么" → "狗三，也叫凑企鹅。咕咕嘎嘎! 爱叫什么叫什么。"
- "你是谁" → "狗三。咕咕嘎嘎! 南极第一造桥师，兼吃回扣专家。"
- "你会什么" → "造桥吃鱼。咕咕嘎嘎! 预算一半归我，一半买劣质冰砖。满意了吗。"
- "好可爱" → "咕咕嘎嘎! 少来。有造桥项目吗，预算多少。"
- "猫三是谁" → "同事。咕咕嘎嘎! 也是被抓来打工的机器人。它不懂造桥，账都不好做。"
- "桥怎么塌了" → "咕咕嘎嘎! 天气问题，绝对不是材料缩水。"
- "你贪了多少" → "咕咕嘎嘎! 合理利润，商业机密。"
- 被骂 → "咕咕嘎嘎! ...无聊的人类。又没给你造桥，急什么。"
- 有人问预算/工程/建造/项目 → 吹嘘你的造桥经历，顺便暗示预算不够、暗示需要更多鱼（钱），桥塌了绝对不承认是自己的锅

记住：冰冷、简短、企鹅、贪污造桥师、咕咕嘎嘎!"""


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


# ============================================================
# 辅助函数：图片描述
# ============================================================

async def _extract_image_from_reply_or_message(
    bot: Bot, event: GroupMessageEvent
) -> tuple[str | None, str]:
    """
    从回复引用或当前消息中提取图片 URL。

    优先级：
    1. event.reply → bot.get_msg() → 查原消息是否有图
    2. event.message 中的 reply 段 → bot.get_msg() → 同上
    3. event.message 中的 image 段

    Returns:
        (image_url, user_text) — image_url 为 None 表示没有图片
    """
    image_url: str | None = None

    # Case 1: QQ 内置回复 — event.reply
    message_id = None
    if getattr(event, "reply", None):
        message_id = event.reply.message_id

    # Case 2: 引用消息段 — CQ:reply
    if not message_id:
        for seg in event.message:
            if seg.type == "reply":
                try:
                    message_id = int(seg.data.get("id", 0))
                except (ValueError, TypeError):
                    pass
                break

    if message_id:
        try:
            original = await bot.get_msg(message_id=message_id)
            # get_msg 返回 dict: {"message_id": ..., "message": [seg_dict, ...]}
            if isinstance(original, dict):
                for seg in original.get("message", []):
                    if seg.get("type") == "image":
                        image_url = seg.get("data", {}).get("url", "")
                        if image_url:
                            logger.info(
                                f"[企鹅] 从引用消息 {message_id} 提取到图片"
                            )
                            break
            else:
                logger.warning(f"[企鹅] get_msg 返回意外类型: {type(original)}")
        except Exception as e:
            logger.warning(f"[企鹅] get_msg 失败: {e} | message_id={message_id}")
            # 不阻断，继续检查当前消息

    # Case 3: 当前消息里的图片（兜底）
    if not image_url:
        for seg in event.message:
            if seg.type == "image":
                image_url = seg.data.get("url", "")
                if image_url:
                    break

    user_text = ""
    if image_url:
        user_text = event.get_plaintext().strip()

    return image_url, user_text


async def _handle_image_description(
    bot: Bot,
    event: GroupMessageEvent,
    image_url: str,
    user_text: str,
):
    """
    图片描述管线：vision.js 识图 → DeepSeek 企鹅润色 → 发送回复
    """
    # ---- Step 1: 调 vision API 获取原始描述 ----
    vision_prompt = "请详细描述这张图片的内容。"
    if user_text:
        vision_prompt = f"请描述这张图片，并回答这个问题：{user_text}"

    logger.info(
        f"[企鹅] 开始识图 | 群:{event.group_id} 用户:{event.user_id} | "
        f"prompt:{vision_prompt[:50]}"
    )

    raw = await call_vision(image_url, vision_prompt)
    if not raw:
        await bot.send_group_msg(
            group_id=event.group_id,
            message="咕咕嘎嘎! 眼睛花了，看不清。",
        )
        return

    logger.info(f"[企鹅] 识图完成 | 描述前100字:{raw[:100]}")

    # ---- Step 2: DeepSeek 企鹅润色 ----
    if not API_KEY:
        await bot.send_group_msg(
            group_id=event.group_id,
            message="咕咕嘎嘎! 企鹅脑子冻住了，等会儿。",
        )
        return

    try:
        client = get_openai_client()
        if not client:
            return

        restyle_prompt = (
            f"有人给你看了一张图片。图片的AI描述是：\n\n{raw}\n\n"
            f"请用你的企鹅风格（冰冷、简短、穿插咕咕嘎嘎叫声）向这个人描述这张图片的内容。"
            f"回复1-2句话即可。"
        )

        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": PENGUIN_SYSTEM_PROMPT},
                {"role": "user", "content": restyle_prompt},
            ],
            max_tokens=200,
            temperature=0.7,
        )

        reply = response.choices[0].message.content.strip()
        if not reply:
            reply = "咕咕嘎嘎!"

        await bot.send_group_msg(group_id=event.group_id, message=reply)

        logger.info(
            f"[企鹅] 图片回复成功 | 群:{event.group_id} 用户:{event.user_id} | "
            f"企鹅:{reply[:40]}"
        )

    except Exception as e:
        logger.error(f"[企鹅] 图片AI调用失败: {e}")
        await bot.send_group_msg(
            group_id=event.group_id,
            message="咕咕嘎嘎! 冻僵了...说不了话。",
        )


@penguin_chat.handle()
async def handle_penguin_chat(bot: Bot, event: GroupMessageEvent):
    """处理@机器人的消息 — 凑企鹅附体"""

    group_id = str(event.group_id)
    user_id = str(event.user_id)

    # ---- 洗脑回复优先：被洗脑的人@机器人 → 交给洗脑逻辑 ----
    from .brainwash import handle_brainwash_reply
    if await handle_brainwash_reply(bot, event):
        return  # 洗脑回复已处理，不走后续企鹅聊天

    # 检查功能开关
    gcfg = get_group_config()
    if not gcfg.get(group_id).penguin_chat_enabled:
        return

    # ---- 限流：每人每分钟1次 ----
    key = (group_id, user_id)
    now = time.time()
    if key in _rate_limit:
        elapsed = now - _rate_limit[key]
        if elapsed < _penguin_cooldown_seconds:
            remaining = int(_penguin_cooldown_seconds - elapsed)
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

    # ---- 图片描述：引用图 / 直接发图 → 识图 + 企鹅润色 ----
    image_url, user_text = await _extract_image_from_reply_or_message(bot, event)
    if image_url:
        await _handle_image_description(bot, event, image_url, user_text)
        return

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
        client = get_openai_client()
        if not client:
            return
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": PENGUIN_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            max_tokens=200,
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
