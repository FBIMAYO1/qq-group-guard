"""
管理员命令 - 供群主/管理员使用的控制命令

命令列表：
  /帮助            - 查看所有命令
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
  /全员警告 文字   - @全体并发送警告通知
"""

import re
from nonebot import on_command, logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageSegment,
)

from .storage import get_storage
from .config import GroupGuardConfig

# 加载配置
plugin_config = GroupGuardConfig()


# ============================================================
# 权限检查：仅管理员/群主可用
# ============================================================

async def is_admin(event: GroupMessageEvent) -> bool:
    return event.sender.role in ("admin", "owner")


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

help_cmd = on_command("帮助", aliases={"help", "菜单", "命令"}, priority=3, rule=is_admin, block=True)


@help_cmd.handle()
async def handle_help(bot: Bot, event: GroupMessageEvent):
    msg = (
        "📋 **群管命令列表**\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 记录查询\n"
        "  /查询 @某人 — 查看违规记录\n"
        "  /历史 @某人 — 违规发言全文\n"
        "  /排行榜 [N] — 违规排行榜\n"
        "  /群管状态 — 运行状态\n\n"
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
        "⚙ 系统\n"
        "  /群管开关 — 启用/停用自动检测\n"
        "  /全员警告 文字 — @all发通知\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💡 所有命令以 / 开头，支持 ！ 和 ! 前缀"
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
        return

    storage = get_storage()
    group_id = str(event.group_id)
    user_id = str(target_id)

    count = storage.get_violation_count(group_id, user_id)
    records = storage.get_user_records(group_id, user_id)
    is_wl = storage.is_whitelisted(group_id, user_id)

    if count == 0:
        wl_tag = " 🛡白名单" if is_wl else ""
        await query_cmd.finish(f"[CQ:at,qq={target_id}] 暂无违规记录 ✅{wl_tag}")
        return

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
        return

    storage = get_storage()
    group_id = str(event.group_id)
    user_id = str(target_id)

    count = storage.get_violation_count(group_id, user_id)
    records = storage.get_user_records(group_id, user_id)

    if not records:
        await history_cmd.finish(f"[CQ:at,qq={target_id}] 暂无违规发言记录 ✅")
        return

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
        return

    target_count = _extract_number(_get_cmd_text(event)) or 0

    storage = get_storage()
    storage.set_violation_count(str(event.group_id), str(target_id), target_count)
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
        return

    add_count = _extract_number(_get_cmd_text(event)) or 1

    storage = get_storage()
    new_count = storage.add_manual_violation(
        str(event.group_id), str(target_id), add_count
    )
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
        return

    storage = get_storage()
    success = storage.remove_last_violation(str(event.group_id), str(target_id))

    if success:
        new_count = storage.get_violation_count(str(event.group_id), str(target_id))
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
        return

    duration_min = _extract_number(_get_cmd_text(event)) or 10
    duration_sec = duration_min * 60

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
        return

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
        return

    # 提取附言（去除 at 号和数字后的文字）
    text = _get_cmd_text(event)
    reason = re.sub(r'\d+', '', text).strip() or "违反群规"

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
        return

    # 检查是否 @了某人 — 没@也没回复就是用法错误
    target_id = _extract_at_target(event)
    if not target_id:
        await recall_cmd.finish("❌ 请回复要撤回的消息后发送 /撤回\n或使用 /撤回 @某人")
        return

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
        return

    # @了人 → 加入白名单
    storage.add_to_whitelist(group_id, str(target_id))
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
        return

    storage = get_storage()
    success = storage.remove_from_whitelist(str(event.group_id), str(target_id))

    if success:
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
        return

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

    if text in ("开", "on", "启用", "打开"):
        plugin_config.guard_enabled = True
        await toggle_cmd.finish("✅ 群管机器人已**启用**，将自动检测违规消息")
    elif text in ("关", "off", "停用", "关闭"):
        plugin_config.guard_enabled = False
        await toggle_cmd.finish("⏸️ 群管机器人已**停用**，将不再自动检测")
    else:
        plugin_config.guard_enabled = not plugin_config.guard_enabled
        state = "✅ 已启用" if plugin_config.guard_enabled else "⏸️ 已停用"
        await toggle_cmd.finish(f"{state}\n用法：/群管开关 开|关")


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
    guard_state = "✅ 运行中" if plugin_config.guard_enabled else "⏸️ 已停用"

    msg = (
        f"🤖 群管机器人状态\n"
        f"━━━━━━━━━━━━━━\n"
        f"检测引擎：DeepSeek AI\n"
        f"自动检测：{guard_state}\n"
        f"白名单人数：{len(wl)}\n"
        f"本群累计违规：{total_violations} 次\n"
        f"涉事用户数：{total_users} 人"
    )

    await status_cmd.finish(msg)


# ============================================================
# /全员警告 文字
# ============================================================

announce_cmd = on_command("全员警告", aliases={"全员通知", "广播"}, priority=5, rule=is_admin, block=True)


@announce_cmd.handle()
async def handle_announce(bot: Bot, event: GroupMessageEvent):
    text = _get_cmd_text(event)
    if not text:
        await announce_cmd.finish("❌ 用法：/全员警告 警告内容")
        return

    msg = f"📢 **群管理通知**\n[CQ:at,qq=all]\n\n{text}"
    await bot.send_group_msg(group_id=event.group_id, message=msg)
    await announce_cmd.finish("✅ 已发送")
