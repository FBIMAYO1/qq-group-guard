"""
群生命周期管理模块

处理：
- 狗三被拉入新群 → 自动初始化群配置
- 狗三被踢出/退出群 → 清理群配置（可选）
- 启动时同步群列表 → 为已在群但无配置的群补建配置

使用 on_notice 事件监听群成员增减。
"""

import asyncio

from nonebot import on_notice, get_driver, get_bots, logger
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupIncreaseNoticeEvent,
    GroupDecreaseNoticeEvent,
)

from .group_config import get_group_config


# ============================================================
# 入群检测 — bot 被拉入新群时自动初始化
# ============================================================
group_increase = on_notice(priority=3, block=False)


@group_increase.handle()
async def _handle_group_increase(bot: Bot, event: GroupIncreaseNoticeEvent):
    """处理群成员增加事件"""
    # 检查是不是 bot 自己被拉入了新群
    if event.user_id != event.self_id:
        return

    gid = str(event.group_id)
    gcfg = get_group_config()

    # init_group 对已存在的群不会覆盖，所以可以安全调用
    existing_groups = gcfg.list_groups()
    if gid in existing_groups:
        logger.info(f"[群生命周期] 狗三重新入群 {gid}（配置已存在）")
    else:
        gcfg.init_group(gid)
        logger.info(f"[群生命周期] 🎉 狗三被拉入新群 {gid}，配置已自动初始化")


# ============================================================
# 退群检测 — bot 被踢/退群时清理配置
# ============================================================
group_decrease = on_notice(priority=3, block=False)


@group_decrease.handle()
async def _handle_group_decrease(bot: Bot, event: GroupDecreaseNoticeEvent):
    """处理群成员减少事件"""
    # 检查是不是 bot 自己被移出了群
    if event.user_id != event.self_id:
        return

    gid = str(event.group_id)
    gcfg = get_group_config()
    gcfg.remove_group(gid)

    sub_type = event.sub_type  # "leave" | "kick" | "kick_me"
    reason = "主动退出" if sub_type == "leave" else "被踢出"
    logger.info(f"[群生命周期] 👋 狗三{reason}群 {gid}，配置已清理")


# ============================================================
# 启动时群列表同步
# ============================================================
_driver = get_driver()


@_driver.on_startup
async def _sync_groups_on_startup():
    """启动时从 OneBot 获取当前群列表，为未配置的群补建配置。

    带重试机制：OneBot 连接建立需要时间，最坏情况等 30 秒。
    """
    MAX_RETRIES = 6
    RETRY_INTERVAL = 5  # 秒

    for attempt in range(1, MAX_RETRIES + 1):
        await asyncio.sleep(RETRY_INTERVAL)

        try:
            bots = get_bots()
            if not bots:
                logger.info(
                    f"[群生命周期] 等待 OneBot 连接... (第{attempt}/{MAX_RETRIES}次)"
                )
                continue

            bot = list(bots.values())[0]
            group_list = await bot.get_group_list()

            gcfg = get_group_config()
            current_gids = {str(g["group_id"]) for g in group_list}
            existing_gids = set(gcfg.list_groups())

            # 为新群补建配置
            new_groups = current_gids - existing_gids
            for gid in new_groups:
                gcfg.init_group(gid)

            # 标记已退出的群为不活跃（不删除，保留历史数据）
            left_groups = existing_gids - current_gids
            for gid in left_groups:
                logger.info(f"[群生命周期] 群 {gid} 已不在群列表中（可能已退出）")

            logger.info(
                f"[群生命周期] ✅ 启动同步完成 | "
                f"当前所在群: {len(current_gids)} | "
                f"新初始化: {len(new_groups)} | "
                f"已退出: {len(left_groups)}"
            )
            return  # 成功后直接返回

        except Exception as e:
            logger.warning(
                f"[群生命周期] 第{attempt}次尝试失败: {e}"
            )
            # 继续重试

    # 所有重试都用完了还是失败
    logger.warning(
        "[群生命周期] 启动同步失败（已重试%d次），"
        "不影响使用：新群将通过入群事件自动初始化",
        MAX_RETRIES,
    )
