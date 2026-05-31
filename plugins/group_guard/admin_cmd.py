"""
管理员命令 - 供群主/管理员使用的控制命令（/帮助全员可用）

命令列表：
  /帮助            - 查看所有命令（全员可用）
  /查询 @某人      - 查看某人违规记录
  /历史 @某人      - 查看某人违规发言全文
  /刷新 @某人 [N]  - 重置违规次数（默认0），可指定到几
  /添加违规 @某人 [N] - 手动添加违规次数（默认1次）
  /撤销 @某人      - 撤销最近一条违规
  /禁言 @某人 分钟  - 手动禁言
  /解禁 @某人      - 解除禁言
  /踢出 @某人      - 踢出群聊
  /撤回 @某人      - 撤回对方最近一条消息
  /白名单 @某人    - 添加白名单（豁免AI检测）
  /取消白名单 @某人 - 移除白名单
  /白名单          - 查看白名单
  /排行榜 [N]      - 违规排行榜（默认前10）
  /群管开关        - 启用/停用自动检测
  /群管状态        - 查看运行状态
  /洗脑 @某人     - 手动对某人发起凑企鹅洗脑
  /全员警告 文字   - @全体并发送警告通知
  /企鹅冷却 [秒]   - 查看/修改企鹅聊天间隔（🔑超级用户）
"""

import re
from nonebot import on_command, get_driver, logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageSegment,
)

from .storage import get_storage
from .config import plugin_config
from .group_config import get_group_config


# ============================================================
# 权限检查：仅管理员/群主可用
# ============================================================

async def is_admin(event: GroupMessageEvent) -> bool:
    return event.sender.role in ("admin", "owner")


async def is_superuser(event: GroupMessageEvent) -> bool:
    """检查是否是超级用户（.env 中 SUPERUSERS 配置的 QQ 号）"""
    try:
        driver = get_driver()
        superusers = driver.config.superusers
        return str(event.user_id) in superusers
    except Exception:
        return False


# ============================================================
# 工具函数（直接从 event 提取，不依赖 CommandArg）
# ============================================================

def _get_cmd_text(event: GroupMessageEvent) -> str:
    """获取去除命令前缀后的纯文本参数"""
    text = event.get_plaintext().strip()
    # 去掉命令前缀 / ！ !
    for prefix in ("/", "！", "!"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    # 去掉命令名（第一个词），返回剩余部分
    parts = text.split(None, 1)
    if len(parts) > 1:
        return parts[1].strip()
    return ""


def _extract_at_target(event: GroupMessageEvent) -> int | None:
    """从原始消息段中提取被@的用户QQ号（排除@all和机器人自身）"""
    bot_qq = str(event.self_id)
    for seg in event.message:
        if seg.type == "at":
            qq = str(seg.data.get("qq", "0"))
            if qq == "all":
                continue
            if qq == bot_qq:
                continue
            return int(qq) or None
    return None


def _extract_number(text: str) -> int | None:
    """从文本中提取第一个数字"""
    match = re.search(r'\d+', text)
    if match:
        return int(match.group())
    return None


# ============================================================
# /帮助
# ============================================================

help_cmd = on_command("帮助", aliases={"help", "菜单", "命令"}, priority=5, block=True)


@help_cmd.handle()
async def handle_help(bot: Bot, event: GroupMessageEvent):
    msg = (
        "📋 **狗三命令列表**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📅 每日互动（全员可用）\n"
        "  /签到 — 每日打卡领企鹅奖励\n"
        "  /签到排行 [N] — 连续签到排行榜\n"
        "  /抽签 — 今日运势抽签\n"
        "  /活跃榜 [N] — 今日水群排行榜\n"
        "  @机器人群聊 — 凑企鹅陪你聊天\n\n"
        "📊 记录查询\n"
        "  /查询 @某人 — 查看违规记录\n"
        "  /历史 @某人 — 违规发言全文\n"
        "  /排行榜 [N] — 违规排行榜\n"
        "  /群管状态 — 运行状态 + 功能开关\n\n"
        "🛠 记录管理\n"
        "  /刷新 @某人 [次数] — 重置违规次数（默认归零）\n"
        "  /添加违规 @某人 [N] — 手动加违规（默认+1）\n"
        "  /撤销 @某人 — 撤销最近一条违规\n\n"
        "🚫 处罚控制\n"
        "  /禁言 @某人 分钟 — 手动禁言\n"
        "  /解禁 @某人 — 解除禁言\n"
        "  /踢出 @某人 — 踢出群聊\n"
        "  /撤回 [@某人] — 撤回消息（可回复消息后发/撤回）\n\n"
        "🛡 白名单\n"
        "  /白名单 @某人 — 加入豁免名单\n"
        "  /取消白名单 @某人 — 移除豁免\n"
        "  /白名单 — 查看豁免列表\n\n"
        "🎮 趣味\n"
        "  /洗脑 @某人 — 手动发起凑企鹅洗脑\n\n"
        "⚙ 系统开关（仅影响当前群）\n"
        "  /群管开关 — 启用/停用AI检测（本群）\n"
        "  /禁言开关 — 开启/关闭自动禁言（本群）\n"
        "  /功能开关 — 查看/切换各功能开关\n"
        "  /全员警告 文字 — @all发通知\n"
        "  /群列表 — 查看所有群状态（🔑超级用户）\n"
        "  /全局默认 — 管理新群默认配置（🔑超级用户）\n"
        "  /广播 — 向所有群发公告（🔑超级用户）\n\n"
        "📰 早报\n"
        "  /早报 — 手动获取当天早报 + 新闻\n\n"
        "🐧 企鹅聊天\n"
        "  /企鹅冷却 [秒] — 查看/修改@机器人回答间隔（🔑超级用户）\n\n"
        "🛡 自动防护（无需操作）\n"
        "  AI违规检测 | 情绪安慰 | 广告拦截\n"
        "  刷屏检测 | 入群欢迎 | 早安短报\n"
        "  狗三道歉 | 猫三豁免（骂机器人不判违规）\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💡 所有命令以 / 开头，支持 ！ 和 ! 前缀\n"
        "🔑 = 仅超级用户（.env SUPERUSERS）可用"
    )
    await help_cmd.finish(msg)


# ============================================================
# /查询 @某人
# ============================================================

query_cmd = on_command("查询", aliases={"记录"}, priority=5, rule=is_admin, block=True)


@query_cmd.handle()
async def handle_query(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    if not target_id:
        await query_cmd.finish("❌ 用法：/查询 @某人")

    storage = get_storage()
    group_id = str(event.group_id)
    user_id = str(target_id)

    count = storage.get_violation_count(group_id, user_id)
    records = storage.get_user_records(group_id, user_id)
    is_wl = storage.is_whitelisted(group_id, user_id)

    if count == 0:
        wl_tag = " 🛡白名单" if is_wl else ""
        await query_cmd.finish(f"[CQ:at,qq={target_id}] 暂无违规记录 ✅{wl_tag}")

    recent = records[-5:]
    if count < 3:
        next_punish = "⚠️ 警告"
    else:
        next_punish = f"🔇 禁言 {count - 1} 小时"

    lines = [
        f"📋 [CQ:at,qq={target_id}] 的违规记录",
        f"累计违规：{count} 次 | 下次处罚：{next_punish}",
    ]
    if is_wl:
        lines.append("🛡 状态：白名单豁免中")
    lines.append("\n📌 最近记录：")
    for i, r in enumerate(recent, 1):
        lines.append(f"  {i}. {r['time']} | {r['category']}")

    await query_cmd.finish("\n".join(lines))


# ============================================================
# /历史 @某人 — 查看某人的全部违规发言记录
# ============================================================

history_cmd = on_command("历史", aliases={"发言记录", "违规发言", "历史记录"}, priority=5, rule=is_admin, block=True)


@history_cmd.handle()
async def handle_history(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    if not target_id:
        await history_cmd.finish("❌ 用法：/历史 @某人")

    storage = get_storage()
    group_id = str(event.group_id)
    user_id = str(target_id)

    count = storage.get_violation_count(group_id, user_id)
    records = storage.get_user_records(group_id, user_id)

    if not records:
        await history_cmd.finish(f"[CQ:at,qq={target_id}] 暂无违规发言记录 ✅")

    lines = [
        f"📜 [CQ:at,qq={target_id}] 违规发言记录",
        f"今日累计：{count} 次 | 历史总计：{len(records)} 条",
        "━━━━━━━━━━━━━━━━━━",
    ]

    # 倒序显示，最新的在前面
    for i, r in enumerate(reversed(records), 1):
        text = r.get("text", "").strip()
        if text:
            # 截断过长的发言
            display_text = text[:40] + "..." if len(text) > 40 else text
            lines.append(f"{i}. {r['time'][:16]} | {r['category']}")
            lines.append(f"   💬 {display_text}")
        else:
            lines.append(f"{i}. {r['time'][:16]} | {r['category']}")

    await history_cmd.finish("\n".join(lines))


# ============================================================
# /刷新 @某人 [次数] — 重置违规次数
# ============================================================

refresh_cmd = on_command("刷新", aliases={"清除记录", "清记录"}, priority=5, rule=is_admin, block=True)


@refresh_cmd.handle()
async def handle_refresh(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    if not target_id:
        await refresh_cmd.finish("❌ 用法：/刷新 @某人 [次数]\n默认归零，可指定次数如 /刷新 @某人 2")

    target_count = _extract_number(_get_cmd_text(event)) or 0

    storage = get_storage()
    storage.set_violation_count(str(event.group_id), str(target_id), target_count)
    logger.info(f"[管理] /刷新 群:{event.group_id} 操作者:{event.user_id} 目标:{target_id} → {target_count}")
    await refresh_cmd.finish(
        f"✅ 已将 [CQ:at,qq={target_id}] 的违规次数设为 {target_count}"
    )


# ============================================================
# /添加违规 @某人 [N]
# ============================================================

add_vio_cmd = on_command("添加违规", aliases={"加违规", "违规+"}, priority=5, rule=is_admin, block=True)


@add_vio_cmd.handle()
async def handle_add_violation(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    if not target_id:
        await add_vio_cmd.finish("❌ 用法：/添加违规 @某人 [次数]\n如 /添加违规 @某人 2")

    add_count = _extract_number(_get_cmd_text(event)) or 1

    storage = get_storage()
    new_count = storage.add_manual_violation(
        str(event.group_id), str(target_id), add_count
    )
    logger.info(f"[管理] /添加违规 群:{event.group_id} 操作者:{event.user_id} 目标:{target_id} +{add_count} → {new_count}")
    await add_vio_cmd.finish(
        f"✅ 已为 [CQ:at,qq={target_id}] 添加 {add_count} 次违规，当前累计 {new_count} 次"
    )


# ============================================================
# /撤销 @某人 — 撤销最近一条违规
# ============================================================

undo_cmd = on_command("撤销", aliases={"撤销违规", "回退"}, priority=5, rule=is_admin, block=True)


@undo_cmd.handle()
async def handle_undo(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    if not target_id:
        await undo_cmd.finish("❌ 用法：/撤销 @某人")

    storage = get_storage()
    success = storage.remove_last_violation(str(event.group_id), str(target_id))

    if success:
        new_count = storage.get_violation_count(str(event.group_id), str(target_id))
        logger.info(f"[管理] /撤销 群:{event.group_id} 操作者:{event.user_id} 目标:{target_id} → {new_count}")
        await undo_cmd.finish(
            f"✅ 已撤销 [CQ:at,qq={target_id}] 最近一条违规，当前累计 {new_count} 次"
        )
    else:
        await undo_cmd.finish("该用户没有违规记录可撤销")


# ============================================================
# /禁言 @某人 分钟
# ============================================================

mute_cmd = on_command("禁言", aliases={"mute", "闭嘴"}, priority=5, rule=is_admin, block=True)


@mute_cmd.handle()
async def handle_mute(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    if not target_id:
        await mute_cmd.finish("❌ 用法：/禁言 @某人 分钟数\n如 /禁言 @某人 30")

    duration_min = _extract_number(_get_cmd_text(event)) or 10
    duration_sec = duration_min * 60

    logger.info(f"[管理] /禁言 群:{event.group_id} 操作者:{event.user_id} 目标:{target_id} {duration_min}分钟")
    try:
        await bot.set_group_ban(
            group_id=event.group_id,
            user_id=target_id,
            duration=duration_sec,
        )
    except Exception as e:
        await mute_cmd.finish(f"❌ 禁言失败：{e}")
        return

    if duration_min >= 60:
        text = f"{duration_min // 60}小时{duration_min % 60}分钟" if duration_min % 60 else f"{duration_min // 60}小时"
    else:
        text = f"{duration_min}分钟"
    await mute_cmd.finish(f"🔇 已禁言 [CQ:at,qq={target_id}] {text}")


# ============================================================
# /解禁 @某人
# ============================================================

unmute_cmd = on_command("解禁", aliases={"unmute", "解除禁言", "取消禁言"}, priority=5, rule=is_admin, block=True)


@unmute_cmd.handle()
async def handle_unmute(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    if not target_id:
        await unmute_cmd.finish("❌ 用法：/解禁 @某人")

    try:
        await bot.set_group_ban(
            group_id=event.group_id,
            user_id=target_id,
            duration=0,
        )
    except Exception as e:
        await unmute_cmd.finish(f"❌ 解禁失败：{e}")
        return

    await unmute_cmd.finish(f"✅ 已解除 [CQ:at,qq={target_id}] 的禁言")


# ============================================================
# /踢出 @某人
# ============================================================

kick_cmd = on_command("踢出", aliases={"kick", "踢了", "T"}, priority=5, rule=is_admin, block=True)


@kick_cmd.handle()
async def handle_kick(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    if not target_id:
        await kick_cmd.finish("❌ 用法：/踢出 @某人")

    # 提取附言（去除 at 号和数字后的文字）
    text = _get_cmd_text(event)
    reason = re.sub(r'\d+', '', text).strip() or "违反群规"
    logger.info(f"[管理] /踢出 群:{event.group_id} 操作者:{event.user_id} 目标:{target_id} 理由:{reason}")

    try:
        await bot.set_group_kick(
            group_id=event.group_id,
            user_id=target_id,
            reject_add_request=False,
        )
    except Exception as e:
        await kick_cmd.finish(f"❌ 踢出失败（可能需要群主权限）：{e}")
        return

    await bot.send_group_msg(
        group_id=event.group_id,
        message=f"🚫 [CQ:at,qq={target_id}] 已被移出群聊\n原因：{reason}",
    )
    await kick_cmd.finish()


# ============================================================
# /撤回 — 回复消息后发送，或 @某人 撤回其最近消息
# ============================================================

recall_cmd = on_command("撤回", aliases={"recall", "撤"}, priority=5, rule=is_admin, block=True)


@recall_cmd.handle()
async def handle_recall(bot: Bot, event: GroupMessageEvent):
    # 如果是回复消息，撤回被回复的那条
    if event.reply:
        try:
            await bot.delete_msg(message_id=event.reply.message_id)
        except Exception as e:
            await recall_cmd.finish(f"❌ 撤回失败：{e}")
            return
        await recall_cmd.finish("✅ 已撤回该消息")

    # 检查是否 @了某人 — 没@也没回复就是用法错误
    target_id = _extract_at_target(event)
    if not target_id:
        await recall_cmd.finish("❌ 请回复要撤回的消息后发送 /撤回\n或使用 /撤回 @某人")

    await recall_cmd.finish(f"💡 提示：请直接回复对方的消息，然后发送 /撤回")


# ============================================================
# /白名单
# ============================================================

wl_add_cmd = on_command("白名单", aliases={"加白", "豁免"}, priority=5, rule=is_admin, block=True)


@wl_add_cmd.handle()
async def handle_whitelist(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    group_id = str(event.group_id)
    storage = get_storage()

    # 没@人 → 查看白名单列表
    if not target_id:
        wl = storage.get_whitelist(group_id)
        if not wl:
            await wl_add_cmd.finish("当前白名单为空")
        lines = ["🛡 当前白名单："]
        for uid in wl:
            lines.append(f"  • {uid}")
        await wl_add_cmd.finish("\n".join(lines))

    # @了人 → 加入白名单
    storage.add_to_whitelist(group_id, str(target_id))
    logger.info(f"[管理] /白名单 添加 群:{event.group_id} 操作者:{event.user_id} 目标:{target_id}")
    await wl_add_cmd.finish(
        f"🛡 已将 [CQ:at,qq={target_id}] 加入白名单\n该用户不再受AI检测"
    )


# ============================================================
# /取消白名单 @某人
# ============================================================

wl_remove_cmd = on_command("取消白名单", aliases={"去白", "移除白名单", "取消豁免"}, priority=5, rule=is_admin, block=True)


@wl_remove_cmd.handle()
async def handle_whitelist_remove(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    if not target_id:
        await wl_remove_cmd.finish("❌ 用法：/取消白名单 @某人")

    storage = get_storage()
    success = storage.remove_from_whitelist(str(event.group_id), str(target_id))

    if success:
        logger.info(f"[管理] /取消白名单 群:{event.group_id} 操作者:{event.user_id} 目标:{target_id}")
        await wl_remove_cmd.finish(f"✅ 已将 [CQ:at,qq={target_id}] 移出白名单，恢复AI检测")
    else:
        await wl_remove_cmd.finish("该用户不在白名单中")


# ============================================================
# /排行榜 [N]
# ============================================================

leaderboard_cmd = on_command("排行榜", aliases={"lb", "排名", "榜单"}, priority=5, rule=is_admin, block=True)


@leaderboard_cmd.handle()
async def handle_leaderboard(bot: Bot, event: GroupMessageEvent):
    top_n = _extract_number(_get_cmd_text(event)) or 10

    storage = get_storage()
    lb = storage.get_violation_leaderboard(str(event.group_id), top_n)

    if not lb:
        await leaderboard_cmd.finish("🏆 本群暂无违规记录，大家都很棒！")

    lines = ["🏆 违规排行榜", "━━━━━━━━━━━━━━"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (uid, count) in enumerate(lb):
        prefix = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{prefix} [CQ:at,qq={uid}] — {count}次")

    await leaderboard_cmd.finish("\n".join(lines))


# ============================================================
# /群管开关
# ============================================================

toggle_cmd = on_command("群管开关", aliases={"开关", "启用", "停用"}, priority=5, rule=is_admin, block=True)


@toggle_cmd.handle()
async def handle_toggle(bot: Bot, event: GroupMessageEvent):
    text = _get_cmd_text(event)
    gid = str(event.group_id)
    gcfg = get_group_config()

    if text in ("开", "on", "启用", "打开"):
        gcfg.set(gid, "guard_enabled", True)
        logger.info(f"[管理] /群管开关 开 群:{gid} 操作者:{event.user_id}")
        await toggle_cmd.finish("✅ 本群 AI 违规检测已**启用**")
    elif text in ("关", "off", "停用", "关闭"):
        gcfg.set(gid, "guard_enabled", False)
        logger.info(f"[管理] /群管开关 关 群:{gid} 操作者:{event.user_id}")
        await toggle_cmd.finish("⏸️ 本群 AI 违规检测已**停用**（不影响其他群）")
    else:
        current = gcfg.get(gid).guard_enabled
        gcfg.set(gid, "guard_enabled", not current)
        state = "✅ 已启用" if not current else "⏸️ 已停用"
        await toggle_cmd.finish(f"{state}\n用法：/群管开关 开|关\n💡 此操作仅影响当前群")


# ============================================================
# /禁言开关
# ============================================================

mute_toggle_cmd = on_command("禁言开关", aliases={"禁言设置", "自动禁言"}, priority=5, rule=is_admin, block=True)


@mute_toggle_cmd.handle()
async def handle_mute_toggle(bot: Bot, event: GroupMessageEvent):
    text = _get_cmd_text(event)
    gid = str(event.group_id)
    gcfg = get_group_config()

    if text in ("开", "on", "启用", "打开"):
        gcfg.set(gid, "mute_enabled", True)
        logger.info(f"[管理] /禁言开关 开 群:{gid} 操作者:{event.user_id}")
        await mute_toggle_cmd.finish(
            "🔇 本群自动禁言已**开启**\n"
            "违规 ≥3 次将按阶梯规则禁言：第3次1h → 第4次2h → 第N次(N-2)h"
        )
    elif text in ("关", "off", "停用", "关闭"):
        gcfg.set(gid, "mute_enabled", False)
        logger.info(f"[管理] /禁言开关 关 群:{gid} 操作者:{event.user_id}")
        await mute_toggle_cmd.finish("🔇 本群自动禁言已**关闭**，违规仅作警告处理")
    else:
        current = gcfg.get(gid).mute_enabled
        gcfg.set(gid, "mute_enabled", not current)
        state = "✅ 已开启" if not current else "⏸️ 已关闭"
        await mute_toggle_cmd.finish(
            f"🔇 本群自动禁言：{state}\n"
            f"用法：/禁言开关 开|关\n"
            f"💡 此操作仅影响当前群"
        )


# ============================================================
# /群管状态
# ============================================================

status_cmd = on_command("群管状态", aliases={"状态", "status"}, priority=5, rule=is_admin, block=True)


@status_cmd.handle()
async def handle_status(bot: Bot, event: GroupMessageEvent):
    storage = get_storage()
    group_id = str(event.group_id)
    stats = storage.get_group_stats(group_id)
    wl = storage.get_whitelist(group_id)

    total_violations = sum(stats.values())
    total_users = len(stats)

    gcfg = get_group_config()
    config = gcfg.get(group_id)
    all_groups = gcfg.list_groups()

    guard_state = "✅ 运行中" if config.guard_enabled else "⏸️ 已停用"
    mute_state = "✅ 已开启" if config.mute_enabled else "⏸️ 已关闭（仅警告）"

    # 功能开关状态简表
    feature_status = "\n".join([
        f"  入群欢迎：{'✅' if config.welcome_enabled else '❌'} | "
        f"早安短报：{'✅' if config.morning_brief_enabled else '❌'}",
        f"  企鹅聊天：{'✅' if config.penguin_chat_enabled else '❌'} | "
        f"情绪安慰：{'✅' if config.comfort_enabled else '❌'}",
        f"  洗脑游戏：{'✅' if config.brainwash_enabled else '❌'} | "
        f"刷屏检测：{'✅' if config.spam_enabled else '❌'}",
        f"  广告拦截：{'✅' if config.ad_enabled else '❌'}",
    ])

    msg = (
        f"🤖 狗三运行状态\n"
        f"━━━━━━━━━━━━━━\n"
        f"检测引擎：DeepSeek AI\n"
        f"自动检测：{guard_state}\n"
        f"自动禁言：{mute_state}\n"
        f"白名单人数：{len(wl)}\n"
        f"本群累计违规：{total_violations} 次（{total_users} 人）\n"
        f"已管理群数：{len(all_groups)} 个群\n"
        f"\n📋 功能开关状态：\n"
        f"{feature_status}\n"
        f"\n💡 使用 /功能开关 <功能名> 开|关 切换"
    )

    await status_cmd.finish(msg)


# ============================================================
# /功能开关 — 查看/切换各功能模块（仅影响当前群）
# ============================================================

FEATURE_MAP = {
    "入群欢迎": "welcome_enabled",
    "早安短报": "morning_brief_enabled",
    "洗脑": "brainwash_enabled",
    "情绪安慰": "comfort_enabled",
    "企鹅聊天": "penguin_chat_enabled",
    "刷屏检测": "spam_enabled",
    "广告拦截": "ad_enabled",
}

FEATURE_LABELS = {
    "welcome_enabled": "入群欢迎",
    "morning_brief_enabled": "早安短报",
    "brainwash_enabled": "洗脑",
    "comfort_enabled": "情绪安慰",
    "penguin_chat_enabled": "企鹅聊天",
    "spam_enabled": "刷屏检测",
    "ad_enabled": "广告拦截",
}

feature_toggle = on_command("功能开关", aliases={"功能"}, priority=5, rule=is_admin, block=True)


@feature_toggle.handle()
async def handle_feature_toggle(bot: Bot, event: GroupMessageEvent):
    text = _get_cmd_text(event)
    gid = str(event.group_id)
    gcfg = get_group_config()
    config = gcfg.get(gid)

    # 无参数 → 显示所有功能开关状态
    if not text:
        lines = ["📋 当前群功能开关状态", "━━━━━━━━━━━━━━"]
        for key, label in FEATURE_LABELS.items():
            state = "✅" if getattr(config, key) else "❌"
            lines.append(f"  {state} {label}")
        lines.append("\n💡 用法：/功能开关 <功能名> 开|关")
        lines.append("  如：/功能开关 洗脑 关")
        await feature_toggle.finish("\n".join(lines))

    # 解析参数
    parts = text.split()
    if len(parts) < 2:
        await feature_toggle.finish(
            "❌ 用法：/功能开关 <功能名> 开|关\n"
            "如：/功能开关 洗脑 关\n"
            "直接发 /功能开关 查看所有开关"
        )

    # 匹配功能名（支持模糊匹配）
    feat_name = parts[0]
    action = parts[1]

    matched_key = None
    for name, key in FEATURE_MAP.items():
        if feat_name in name or name in feat_name:
            matched_key = key
            break

    if not matched_key:
        available = "、".join(FEATURE_MAP.keys())
        await feature_toggle.finish(
            f"❌ 未知功能「{feat_name}」\n可用功能：{available}"
        )

    if action in ("开", "on", "启用", "打开"):
        gcfg.set(gid, matched_key, True)
        await feature_toggle.finish(f"✅ 已在本群开启「{FEATURE_LABELS[matched_key]}」")
    elif action in ("关", "off", "停用", "关闭"):
        gcfg.set(gid, matched_key, False)
        await feature_toggle.finish(f"❌ 已在本群关闭「{FEATURE_LABELS[matched_key]}」")
    else:
        current = getattr(config, matched_key)
        state = "✅ 开启" if current else "❌ 关闭"
        await feature_toggle.finish(
            f"「{FEATURE_LABELS[matched_key]}」当前：{state}\n"
            f"用法：/功能开关 {feat_name} 开|关"
        )


# ============================================================
# /群列表 — 查看 bot 所在所有群（超级用户专用）
# ============================================================

group_list_cmd = on_command("群列表", aliases={"所有群"}, priority=5, rule=is_superuser, block=True)


@group_list_cmd.handle()
async def handle_group_list(bot: Bot, event: GroupMessageEvent):
    gcfg = get_group_config()
    all_groups = gcfg.list_groups()

    if not all_groups:
        await group_list_cmd.finish("📋 暂无已配置的群")

    lines = [f"📋 狗三所在群列表（共 {len(all_groups)} 个）", "━━━━━━━━━━━━━━"]
    for i, gid in enumerate(all_groups, 1):
        config = gcfg.get(gid)
        guard = "🟢" if config.guard_enabled else "🔴"
        mute = "🔇" if config.mute_enabled else "⚠️"
        lines.append(
            f"  {i}. 群 {gid} | {guard}检测 {mute}禁言 | "
            f"功能:{sum([config.welcome_enabled, config.morning_brief_enabled, config.brainwash_enabled, config.comfort_enabled, config.penguin_chat_enabled, config.spam_enabled, config.ad_enabled])}/7"
        )

    await group_list_cmd.finish("\n".join(lines))


# ============================================================
# /全局默认 — 管理新群默认配置（超级用户专用）
# ============================================================

DEFAULT_MAP = {
    "禁言开关": "default_mute_enabled",
    "群管开关": "default_guard_enabled",
    "入群欢迎": "default_welcome_enabled",
    "早安短报": "default_morning_brief_enabled",
    "洗脑": "default_brainwash_enabled",
    "情绪安慰": "default_comfort_enabled",
    "企鹅聊天": "default_penguin_chat_enabled",
    "刷屏检测": "default_spam_enabled",
    "广告拦截": "default_ad_enabled",
}

DEFAULT_LABELS = {
    "default_guard_enabled": "AI违规检测",
    "default_mute_enabled": "自动禁言",
    "default_welcome_enabled": "入群欢迎",
    "default_morning_brief_enabled": "早安短报",
    "default_brainwash_enabled": "洗脑",
    "default_comfort_enabled": "情绪安慰",
    "default_penguin_chat_enabled": "企鹅聊天",
    "default_spam_enabled": "刷屏检测",
    "default_ad_enabled": "广告拦截",
}

global_default_cmd = on_command("全局默认", aliases={"默认配置"}, priority=5, rule=is_superuser, block=True)


@global_default_cmd.handle()
async def handle_global_default(bot: Bot, event: GroupMessageEvent):
    text = _get_cmd_text(event)
    gcfg = get_group_config()

    # 无参数 → 显示所有默认值
    if not text:
        defaults = gcfg.get_defaults()
        lines = ["⚙ 全局默认配置（新群从此继承）", "━━━━━━━━━━━━━━"]
        for key, label in DEFAULT_LABELS.items():
            state = "✅" if getattr(defaults, key) else "❌"
            lines.append(f"  {state} {label}")
        lines.append("\n💡 用法：/全局默认 <项目> 开|关")
        lines.append("  如：/全局默认 禁言开关 开")
        await global_default_cmd.finish("\n".join(lines))

    # 解析参数
    parts = text.split()
    if len(parts) < 2:
        await global_default_cmd.finish(
            "❌ 用法：/全局默认 <项目> 开|关\n"
            "如：/全局默认 禁言开关 开\n"
            "直接发 /全局默认 查看所有默认值"
        )

    name = parts[0]
    action = parts[1]

    matched_key = None
    for label, key in DEFAULT_MAP.items():
        if name in label or label in name:
            matched_key = key
            break

    if not matched_key:
        available = "、".join(DEFAULT_MAP.keys())
        await global_default_cmd.finish(
            f"❌ 未知项目「{name}」\n可用：{available}"
        )

    if action in ("开", "on", "启用", "打开"):
        gcfg.set_default(matched_key, True)
        await global_default_cmd.finish(f"✅ 全局默认「{DEFAULT_LABELS[matched_key]}」→ 开启\n之后新加入的群将默认启用此功能")
    elif action in ("关", "off", "停用", "关闭"):
        gcfg.set_default(matched_key, False)
        await global_default_cmd.finish(f"❌ 全局默认「{DEFAULT_LABELS[matched_key]}」→ 关闭\n之后新加入的群将默认停用此功能")
    else:
        defaults = gcfg.get_defaults()
        current = getattr(defaults, matched_key)
        state = "✅ 开启" if current else "❌ 关闭"
        await global_default_cmd.finish(
            f"「{DEFAULT_LABELS[matched_key]}」全局默认：{state}\n"
            f"用法：/全局默认 {name} 开|关"
        )


# ============================================================
# /早报 — 手动获取当天早报（管理员可用）
# ============================================================

brief_cmd = on_command("早报", aliases={"早间新闻", "今日新闻"}, priority=5, rule=is_admin, block=True)


@brief_cmd.handle()
async def handle_brief(bot: Bot, event: GroupMessageEvent):
    """手动触发早报"""
    from . import morning_brief
    brief = await morning_brief.get_brief()
    await brief_cmd.finish(brief)


# ============================================================
# /广播 — 向所有群发送公告（超级用户专用）
# ============================================================

broadcast_cmd = on_command("广播", aliases={"全群通知"}, priority=5, rule=is_superuser, block=True)


@broadcast_cmd.handle()
async def handle_broadcast(bot: Bot, event: GroupMessageEvent):
    text = _get_cmd_text(event)
    if not text:
        await broadcast_cmd.finish("❌ 用法：/广播 <公告内容>\n如：/广播 系统将于今晚维护，请见谅")

    gcfg = get_group_config()
    all_groups = gcfg.list_groups()

    if not all_groups:
        await broadcast_cmd.finish("❌ 没有可广播的群")

    msg = f"📢 **狗三系统公告**\n\n{text}\n\n——来自超级用户"

    success = 0
    fail = 0
    for gid in all_groups:
        try:
            await bot.send_group_msg(group_id=int(gid), message=msg)
            success += 1
        except Exception as e:
            logger.error(f"[广播] 群{gid}发送失败: {e}")
            fail += 1

    await broadcast_cmd.finish(
        f"✅ 广播完成：成功 {success} 个群" + (f"，失败 {fail} 个群" if fail else "")
    )


# ============================================================
# /企鹅冷却 — 查看/修改企鹅聊天冷却时间（超级用户专用）
# ============================================================

cooldown_cmd = on_command("企鹅冷却", aliases={"企鹅限流", "企鹅间隔"}, priority=5, rule=is_superuser, block=True)


@cooldown_cmd.handle()
async def handle_penguin_cooldown(bot: Bot, event: GroupMessageEvent):
    """查看或修改企鹅聊天的每人使用间隔"""
    from . import penguin_chat

    text = _get_cmd_text(event)

    # 无参数 → 查看当前冷却时间
    if not text:
        current = penguin_chat.get_penguin_cooldown()
        if current >= 60:
            display = f"{current // 60} 分钟" + (f" {current % 60} 秒" if current % 60 else "")
        else:
            display = f"{current} 秒"
        await cooldown_cmd.finish(
            f"🐧 企鹅聊天冷却时间：{display}\n"
            f"用法：/企鹅冷却 <秒数>\n"
            f"如：/企鹅冷却 30  → 改为 30 秒\n"
            f"    /企鹅冷却 120 → 改为 2 分钟\n"
            f"💡 最低 5 秒，默认 60 秒"
        )

    # 有参数 → 修改冷却时间
    new_seconds = _extract_number(text)
    if new_seconds is None:
        await cooldown_cmd.finish("❌ 请输入一个数字（秒），如 /企鹅冷却 30")

    penguin_chat.set_penguin_cooldown(new_seconds)
    actual = penguin_chat.get_penguin_cooldown()

    if actual >= 60:
        display = f"{actual // 60} 分钟" + (f" {actual % 60} 秒" if actual % 60 else "")
    else:
        display = f"{actual} 秒"

    logger.info(f"[管理] /企鹅冷却 操作者:{event.user_id} → {actual}秒")
    await cooldown_cmd.finish(f"✅ 企鹅聊天冷却已改为 {display}")


# ============================================================
# /洗脑 @某人 — 手动触发凑企鹅洗脑
# ============================================================

brainwash_cmd = on_command("洗脑", aliases={"凑企鹅洗脑"}, priority=5, rule=is_admin, block=True)


@brainwash_cmd.handle()
async def handle_brainwash(bot: Bot, event: GroupMessageEvent):
    target_id = _extract_at_target(event)
    if not target_id:
        await brainwash_cmd.finish("❌ 用法：/洗脑 @某人")

    from . import brainwash

    try:
        # brainwash_target 内部已发送洗脑消息，无需额外回复
        await brainwash.brainwash_target(bot, event.group_id, target_id)
    except Exception as e:
        await brainwash_cmd.finish(f"❌ 洗脑失败：{e}")
        return

    await brainwash_cmd.finish()


# ============================================================
# /全员警告 文字
# ============================================================

announce_cmd = on_command("全员警告", aliases={"全员通知"}, priority=5, rule=is_admin, block=True)


@announce_cmd.handle()
async def handle_announce(bot: Bot, event: GroupMessageEvent):
    text = _get_cmd_text(event)
    if not text:
        await announce_cmd.finish("❌ 用法：/全员警告 警告内容")

    msg = f"📢 **群管理通知**\n[CQ:at,qq=all]\n\n{text}"
    await bot.send_group_msg(group_id=event.group_id, message=msg)
    await announce_cmd.finish("✅ 已发送")
