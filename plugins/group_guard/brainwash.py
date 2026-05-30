"""
洗脑企鹅模块

每天随机生成3个时段，到点选取该群最近发言的群成员进行洗脑。

被@的人如果回复包含「凑企鹅」或承认自己是凑企鹅 → 回复「咕咕嘎嘎！」
如果不回复 → 回复"不对，你是凑企鹅……"并再次@追问，最多循环3次

规则：
- 触发时段每天随机，范围 09:00~23:00，间隔≥2小时
- 不洗脑管理员/群主/机器人自己
- 每天最多触发3次（每个随机时段各1次），选取该群最近发言的人
- 每次只洗脑一人，追问最多3轮，全部否认或2分钟超时才换人
- 当天已被选过的人不会重复选
"""

import random
import time
import asyncio
from datetime import datetime
from nonebot import on_message, get_driver, get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import Rule


# ============================================================
# 配置
# ============================================================
CHECK_INTERVAL = 60       # 每60秒检查一次
REPLY_TIMEOUT = 120        # 2分钟没回复则放弃
MAX_ROUNDS = 3             # 最多追问3轮（含首次）
TRIGGER_COUNT = 3           # 每天触发次数
TRIGGER_FROM = 9            # 最早触发时间（小时）
TRIGGER_TO = 23             # 最晚触发时间（小时）
SPACING_MINUTES = 120       # 各触发点之间至少间隔2小时

BRAINWASH_FIRST = "饿啊！你是凑企鹅你是凑企鹅，你是谁呀？"   # 首轮
BRAINWASH_MSG = "你是凑企鹅，你是凑企鹅你是谁呀？"                # 追问轮


# ============================================================
# 状态
# ============================================================
# 近期活跃成员: group_id -> set(user_id)
_active_members: dict[str, set[str]] = {}

# 最近发言者: group_id -> (user_id, timestamp)
_last_speaker: dict[str, tuple[str, float]] = {}

# 当前洗脑目标: group_id -> (target_user_id, timestamp, round)
_current_target: dict[str, tuple[str, float, int]] = {}

# 今日已触发的时段: (group_id, date_str) -> set(minutes_of_day)
_triggered_today: dict[tuple[str, str], set[int]] = {}

# 今天随机生成的触发时间: date_str -> list[int] (分钟数: hour*60+minute)
_daily_triggers: dict[str, list[int]] = {}

# 当天已被选过的人（不重复选，每天0点清空）
_recently_picked: set[tuple[str, str]] = set()


# ============================================================
# 工具函数
# ============================================================

def _generate_random_triggers() -> list[int]:
    """生成当天3个随机触发时间，09:00~23:00之间，间隔≥2小时"""
    start = TRIGGER_FROM * 60      # 540
    end = TRIGGER_TO * 60           # 1380
    attempts = 0
    while attempts < 200:
        candidates = sorted(random.sample(range(start, end + 1), TRIGGER_COUNT))
        # 检查间隔
        ok = True
        for i in range(1, len(candidates)):
            if candidates[i] - candidates[i - 1] < SPACING_MINUTES:
                ok = False
                break
        if ok:
            return candidates
        attempts += 1
    # 兜底：手动均分
    span = end - start
    return [start + span * (i + 1) // (TRIGGER_COUNT + 1) for i in range(TRIGGER_COUNT)]


def _format_time(minutes: int) -> str:
    """分钟数 → 可读时间字符串"""
    h, m = divmod(minutes, 60)
    return f"{h:02d}:{m:02d}"


# ============================================================
# 低优先级消息收集器 — 记录所有非管理员的活跃成员 + 发言时间
# ============================================================
member_collector = on_message(priority=99, block=False)


@member_collector.handle()
async def _collect_active(event: GroupMessageEvent):
    """悄悄地记录每个发言的群成员及发言时间"""
    gid = str(event.group_id)
    uid = str(event.user_id)
    bot_qq = str(event.self_id)

    # 跳过机器人自己
    if uid == bot_qq:
        return

    # 跳过管理员/群主（不洗脑管理层）
    if event.sender.role in ("admin", "owner"):
        return

    if gid not in _active_members:
        _active_members[gid] = set()
    _active_members[gid].add(uid)

    # 记录最近发言者
    _last_speaker[gid] = (uid, time.time())


# ============================================================
# 洗脑回复检测器 — 最高优先级，检测被@的人是否回复
# ============================================================
async def _is_brainwash_target(event: GroupMessageEvent) -> bool:
    """检查发消息的人是否正在被洗脑"""
    gid = str(event.group_id)
    uid = str(event.user_id)
    if gid in _current_target:
        target_uid, _ = _current_target[gid]
        if uid == target_uid:
            return True
    return False


brainwash_reply = on_message(
    rule=Rule(_is_brainwash_target),
    priority=0,     # 最高优先级
    block=True,     # 阻止企鹅聊天和违规检测
)


@brainwash_reply.handle()
async def _handle_brainwash_reply(bot: Bot, event: GroupMessageEvent):
    """被洗脑对象发了消息 → 判断是否包含「凑企鹅」"""
    gid = str(event.group_id)
    uid = str(event.user_id)
    text = event.get_plaintext().strip()

    target_uid, started_at, round_num = _current_target.get(gid, ("", 0, 0))

    if "凑企鹅" in text:
        # 承认了 → 结束
        reply = f"[CQ:at,qq={uid}] 咕咕嘎嘎！"
        await bot.send_group_msg(group_id=event.group_id, message=reply)
        _current_target.pop(gid, None)
        _recently_picked.add((gid, uid))
        logger.info(f"[洗脑] ✅ {uid} 承认是凑企鹅 → 咕咕嘎嘎！（第{round_num}轮）")
        return

    # 没承认
    next_round = round_num + 1
    if next_round > MAX_ROUNDS:
        # 3轮都没承认 → 放弃
        await bot.send_group_msg(
            group_id=event.group_id,
            message=f"[CQ:at,qq={uid}] 唉，算了……",
        )
        _current_target.pop(gid, None)
        _recently_picked.add((gid, uid))
        logger.info(f"[洗脑] 😔 {uid} {MAX_ROUNDS}轮都没承认凑企鹅，放弃")
        return

    # 还没到上限 → 继续追问
    _current_target[gid] = (target_uid, time.time(), next_round)
    await bot.send_group_msg(
        group_id=event.group_id,
        message=f"[CQ:at,qq={uid}] 不对，{BRAINWASH_MSG}",
    )
    logger.info(f"[洗脑] 🔄 {uid} 第{round_num}轮否认 → 继续追问（第{next_round}轮）")


# ============================================================
# 定时洗脑后台任务 — 每分钟检查，到点触发
# ============================================================
async def _brainwash_loop():
    """每分钟检查一次，到了随机触发时间就执行洗脑"""
    await asyncio.sleep(8)

    last_date = ""
    _active_members.clear()
    _last_speaker.clear()

    while True:
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            if today != last_date:
                # 新的一天 → 生成新的随机触发时间、清空所有今日状态
                _recently_picked.clear()
                _triggered_today.clear()
                _daily_triggers.clear()
                last_date = today
                triggers = _generate_random_triggers()
                _daily_triggers[today] = triggers
                trigger_strs = " / ".join(_format_time(t) for t in triggers)
                logger.info(f"[洗脑] 🌅 {today} — 今日随机触发时段: {trigger_strs}")

            await _do_brainwash_check()
        except Exception as e:
            logger.error(f"[洗脑] 后台异常: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


async def _do_brainwash_check():
    """检查当前是否到了随机触发时间，是则执行洗脑"""
    now = time.time()
    now_dt = datetime.now()
    today_str = now_dt.strftime("%Y-%m-%d")
    current_minutes = now_dt.hour * 60 + now_dt.minute

    # ---- 清理超时的目标（2分钟没回复就放弃）----
    expired = [
        gid for gid, (uid, t, r) in _current_target.items()
        if now - t > REPLY_TIMEOUT
    ]
    for gid in expired:
        uid, _, r = _current_target.pop(gid)
        logger.info(f"[洗脑] ⏰ {uid} 超时未回复（第{r}轮），放弃")

    # ---- 判断当前是否命中某个随机触发点（±1分钟）----
    daily = _daily_triggers.get(today_str, [])
    matched_m = None
    for m in daily:
        if abs(current_minutes - m) <= 1:
            matched_m = m
            break

    if matched_m is None:
        return  # 没到触发时间

    # ---- 获取 bot 实例 ----
    bots = get_bots()
    if not bots:
        return
    bot = list(bots.values())[0]

    # ---- 遍历每个群，按条件洗脑 ----
    for gid, members in list(_active_members.items()):
        # 该群正在洗脑中（等回复），跳过
        if gid in _current_target:
            continue

        # 今天此时段已经触发过，跳过
        group_key = (gid, today_str)
        if group_key not in _triggered_today:
            _triggered_today[group_key] = set()
        if matched_m in _triggered_today[group_key]:
            continue

        # ---- 该群最近发言的人 ----
        last = _last_speaker.get(gid)
        if last is None:
            logger.info(f"[洗脑] ⏭️ 群:{gid} 没有发言记录，跳过")
            continue

        last_uid, _ = last
        # 当天已经被选过 → 从活跃成员中随机挑一个没被选过的
        if (gid, last_uid) in _recently_picked:
            available = [
                m for m in members
                if (gid, m) not in _recently_picked
            ]
            if not available:
                logger.info(f"[洗脑] ⏭️ 群:{gid} 所有成员今天都已被洗脑过")
                continue
            target = random.choice(available)
        else:
            target = last_uid

        # ---- 发送洗脑消息 ----
        try:
            await bot.send_group_msg(
                group_id=int(gid),
                message=f"[CQ:at,qq={target}] {BRAINWASH_FIRST}",
            )
            _current_target[gid] = (target, now, 1)
            _recently_picked.add((gid, target))
            _triggered_today[group_key].add(matched_m)
            logger.info(
                f"[洗脑] 🎯 群:{gid} → @{target} 洗脑中 "
                f"(时段 {_format_time(matched_m)})"
            )
        except Exception as e:
            logger.error(f"[洗脑] 发送失败 {gid}/{target}: {e}")


# ============================================================
# 注册启动钩子
# ============================================================
_driver = get_driver()


@_driver.on_startup
async def _start_brainwash():
    """NoneBot 启动后拉起洗脑定时任务"""
    asyncio.create_task(_brainwash_loop())
    logger.info("[洗脑] 🐧 凑企鹅洗脑模块已启动，每天随机3个时段触发")


# ============================================================
# 公开接口 — 供管理命令手动触发洗脑
# ============================================================

async def brainwash_target(bot: Bot, group_id: int, user_id: int) -> str:
    """手动触发对指定用户的洗脑

    Args:
        bot: Bot 实例
        group_id: 群号
        user_id: 目标用户 QQ 号

    Returns:
        操作结果说明文本
    """
    gid = str(group_id)
    uid = str(user_id)

    # 该群正在洗脑中 → 先清理
    if gid in _current_target:
        old_target, _, old_round = _current_target.pop(gid)
        logger.info(f"[洗脑] 🛑 管理员手动中断对 {old_target} 的洗脑（第{old_round}轮）")

    now = time.time()
    _current_target[gid] = (uid, now, 1)
    _recently_picked.add((gid, uid))

    try:
        await bot.send_group_msg(
            group_id=group_id,
            message=f"[CQ:at,qq={uid}] {BRAINWASH_FIRST}",
        )
        logger.info(f"[洗脑] 🔧 管理员手动触发 → @{uid}")
        return f"🐧 已对 [CQ:at,qq={uid}] 发起凑企鹅洗脑！\n  {BRAINWASH_FIRST}"
    except Exception as e:
        _current_target.pop(gid, None)
        _recently_picked.discard((gid, uid))
        raise e
