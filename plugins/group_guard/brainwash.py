"""
洗脑企鹅模块

机器人每5分钟从最近发过消息的群成员中随机挑一个，@TA并发问：
  "你是凑企鹅，你是凑企鹅你是谁呀？"

被@的人如果回复包含「凑企鹅」或承认自己是凑企鹅 → 回复「咕咕嘎嘎！」
如果不回复凑企鹅（说了别的） → 回复「不对」

规则：
- 不洗脑管理员/群主/机器人自己
- 每次只洗脑一人，等TA回复或2分钟超时后才换下一个人
- 已回复的人本2分钟内不会被重复选中
"""

import random
import time
import asyncio
from nonebot import on_message, get_driver, get_bots, logger
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import Rule


# ============================================================
# 状态
# ============================================================
# 近期活跃成员: group_id -> set(user_id)
_active_members: dict[str, set[str]] = {}

# 当前洗脑目标: group_id -> (target_user_id, timestamp)
_current_target: dict[str, tuple[str, float]] = {}

# 已回复过的人（冷却中，不重复选）
_recently_picked: set[tuple[str, str]] = set()

INTERVAL = 300        # 5分钟一轮
REPLY_TIMEOUT = 120   # 2分钟没回复则放弃，换人

BRAINWASH_MSG = "你是凑企鹅，你是凑企鹅你是谁呀？"


# ============================================================
# 低优先级消息收集器 — 记录所有非管理员的活跃成员
# ============================================================
member_collector = on_message(priority=99, block=False)


@member_collector.handle()
async def _collect_active(event: GroupMessageEvent):
    """悄悄地记录每个发言的群成员"""
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

    if "凑企鹅" in text:
        reply = f"[CQ:at,qq={uid}] 咕咕嘎嘎！"
        logger.info(f"[洗脑] ✅ {uid} 承认是凑企鹅 → 咕咕嘎嘎！")
    else:
        reply = "不对"
        logger.info(f"[洗脑] ❌ {uid} 回复了但没有承认凑企鹅 → 不对")

    await bot.send_group_msg(group_id=event.group_id, message=reply)

    # 本轮洗脑结束
    _current_target.pop(gid, None)
    # 加入冷却集
    _recently_picked.add((gid, uid))


# ============================================================
# 定时洗脑后台任务
# ============================================================
async def _brainwash_loop():
    """每5分钟执行一轮洗脑"""
    # 等待 NoneBot 完全启动（bot 实例就绪）
    await asyncio.sleep(8)

    while True:
        try:
            await _do_brainwash_round()
        except Exception as e:
            logger.error(f"[洗脑] 后台异常: {e}")

        await asyncio.sleep(INTERVAL)


async def _do_brainwash_round():
    """执行一轮洗脑"""
    now = time.time()

    # ---- 清理超时的目标（2分钟没回复就放弃）----
    expired = [
        gid for gid, (uid, t) in _current_target.items()
        if now - t > REPLY_TIMEOUT
    ]
    for gid in expired:
        uid, _ = _current_target.pop(gid)
        logger.info(f"[洗脑] ⏰ {uid} 超时未回复，放弃")

    # ---- 清理冷却集（超过2分钟的移除）----
    # （这里简单处理：每轮都全量清理超过2分钟的记录）
    for key in list(_recently_picked):
        gid, uid = key
        # 我们在轮次开始时清理，但 _recently_picked 没有时间戳
        # 简化：每轮执行完后清空
        pass
    # 直接清空冷却集（每个新轮次重新开始）
    _recently_picked.clear()

    # ---- 获取 bot 实例 ----
    bots = get_bots()
    if not bots:
        logger.warning("[洗脑] 没有可用的 Bot 实例")
        return
    bot = list(bots.values())[0]

    # ---- 遍历每个群，随机洗脑 ----
    for gid, members in list(_active_members.items()):
        # 该群正在洗脑中（等回复），跳过
        if gid in _current_target:
            continue

        # 过滤：排除刚被洗脑过的人
        available = [
            m for m in members
            if (gid, m) not in _recently_picked
        ]
        if not available:
            continue

        target = random.choice(available)

        # 发送洗脑消息
        try:
            await bot.send_group_msg(
                group_id=int(gid),
                message=f"[CQ:at,qq={target}] {BRAINWASH_MSG}",
            )
            _current_target[gid] = (target, now)
            _recently_picked.add((gid, target))
            logger.info(f"[洗脑] 🎯 群:{gid} → @{target} 洗脑中")
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
    logger.info("[洗脑] 🐧 凑企鹅洗脑模块已启动，每5分钟执行一次")
