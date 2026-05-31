"""
图片违禁检测模块 — 通过千问 VL 模型审核群图片消息

当纯图片消息（无文本）到达时，提取图片 URL 交给视觉模型判断是否违规。
复用现有的 CheckResult + Punisher 处罚流程。

依赖：~/.agents/skills/claude-vision/scripts/vision.js（千问 qwen3.5-omni-plus）
"""

import asyncio
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path

import httpx
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot import logger

from .checker import CheckResult

# ============================================================
# vision.js 路径
# ============================================================
_VISION_JS = str(
    Path.home() / ".agents" / "skills" / "claude-vision" / "scripts" / "vision.js"
)

# ============================================================
# 审核 Prompt — 精简，聚焦违禁类别判定
# ============================================================
MODERATION_PROMPT = (
    "你是QQ群图片内容审核员。检查这张图片是否有以下违规内容：\n"
    "1. 色情/裸体/性暗示/低俗擦边\n"
    "2. 血腥暴力/虐待动物或人/自残\n"
    "3. 违法内容（毒品/枪支武器/管制物品）\n"
    "4. 赌博/诈骗/刷单广告/诱导转账二维码\n"
    "5. 政治敏感（分裂/邪教/极端言论符号）\n"
    "6. 恶心猎奇/重口味（呕吐物/排泄物/密集恐惧/肢解/畸形/恐怖惊悚等令人强烈不适的内容）\n\n"
    "只回复一行JSON，不要任何其他文字：\n"
    '{"violation":true或false, "category":"违规类别简称", "reason":"一句话说明"}\n'
    "如果图片正常无违规，category和reason留空字符串。"
)

# ============================================================
# 临时文件目录
# ============================================================
_TMP_DIR = Path(tempfile.gettempdir()) / "dog3_image_check"
_TMP_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# 缓存 & 限流
# ============================================================
# 图片 URL → (is_violation, CheckResult | None)
# 缓存 1000 条，避免同一张图反复调用 API
_cache: dict[str, CheckResult | None] = {}
_MAX_CACHE = 1000

# 全局限流：每秒最多 1 次 API 调用
_last_call: float = 0.0
_MIN_INTERVAL = 1.0  # 秒


async def check_images(event: GroupMessageEvent) -> CheckResult | None:
    """
    检查消息中的图片是否违规。

    Args:
        event: 群消息事件

    Returns:
        CheckResult 如果违规，None 如果合规或无图片
    """
    # 1. 提取所有图片 URL
    image_urls = _extract_image_urls(event)
    if not image_urls:
        return None

    # 2. 逐张检查（取第一张有问题的就返回）
    for url in image_urls:
        # 检查缓存
        if url in _cache:
            cached = _cache[url]
            if cached is not None:
                logger.info(f"[图片检测] 缓存命中 | URL:{url[:50]}... → 违规")
            return cached

        result = await _check_single_image(url, event)
        if result is not None:
            return result

    # 全部合规
    return None


def _extract_image_urls(event: GroupMessageEvent) -> list[str]:
    """从消息段中提取所有图片 URL"""
    urls = []
    for seg in event.message:
        if seg.type == "image":
            url = seg.data.get("url", "")
            if url:
                urls.append(url)
    return urls


async def _check_single_image(url: str, event: GroupMessageEvent) -> CheckResult | None:
    """
    下载 QQ 图片 → 写临时文件 → 调 vision.js 本地模式审核。

    不走 --url 直传，因为千问 API 服务器可能无法下载 QQ CDN 图片。
    Python 侧下载（bot 在 QQ 网络内）→ base64 编码传给 VL 模型。

    Returns:
        CheckResult 如果违规，None 如果合规
    """
    # ---- 限流 ----
    global _last_call
    now = time.time()
    wait = _MIN_INTERVAL - (now - _last_call)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_call = time.time()

    # ---- 下载图片 ----
    logger.info(
        f"[图片检测] 下载图片 | 群:{event.group_id} 用户:{event.user_id} | URL:{url[:60]}..."
    )
    tmp_path = None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            image_bytes = resp.content
    except httpx.HTTPStatusError as e:
        logger.warning(f"[图片检测] 下载失败 HTTP{e.response.status_code} | URL:{url[:60]}...")
        _cache[url] = None
        return None
    except Exception as e:
        logger.warning(f"[图片检测] 下载异常: {e} | URL:{url[:60]}...")
        _cache[url] = None
        return None

    if not image_bytes or len(image_bytes) < 100:
        logger.warning(f"[图片检测] 图片太小({len(image_bytes)}字节) | URL:{url[:60]}...")
        _cache[url] = None
        return None

    # ---- 写临时文件 ----
    try:
        suffix = _guess_ext(image_bytes[:16]) or ".jpg"
        tmp_path = _TMP_DIR / f"{hashlib.md5(image_bytes).hexdigest()[:16]}{suffix}"
        if not tmp_path.exists():
            tmp_path.write_bytes(image_bytes)
    except Exception as e:
        logger.error(f"[图片检测] 写临时文件失败: {e}")
        _cache[url] = None
        return None

    # ---- 调 vision.js（本地文件模式） ----
    logger.info(
        f"[图片检测] 开始审核 | 群:{event.group_id} 用户:{event.user_id} | "
        f"文件:{tmp_path.name} 大小:{len(image_bytes)}字节"
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            "node", _VISION_JS,
            str(tmp_path),          # 本地文件路径，vision.js 会 base64 编码
            MODERATION_PROMPT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=30
        )
    except asyncio.TimeoutError:
        logger.warning(f"[图片检测] 超时 | 文件:{tmp_path.name}")
        _cache[url] = None
        return None
    except FileNotFoundError:
        logger.error(f"[图片检测] vision.js 不存在: {_VISION_JS}")
        _cache[url] = None
        return None
    except Exception as e:
        logger.error(f"[图片检测] 进程启动失败: {e}")
        _cache[url] = None
        return None
    finally:
        # 清理临时文件
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace")[:200] if stderr else ""
        logger.warning(f"[图片检测] vision.js 返回 {proc.returncode} | {err_text}")
        _cache[url] = None
        return None

    output = stdout.decode("utf-8", errors="replace").strip()
    logger.info(f"[图片检测] RAW输出(前200字): {output[:200]}")

    # ---- 解析结果 ----
    result = _parse_moderation_output(output, url, event)
    _cache[url] = result

    # 淘汰旧缓存
    if len(_cache) > _MAX_CACHE:
        keys = list(_cache.keys())
        for k in keys[:_MAX_CACHE // 2]:
            del _cache[k]

    return result


def _guess_ext(head16: bytes) -> str | None:
    """根据文件头魔数猜图片扩展名"""
    if head16[:4] == b"\x89PNG":
        return ".png"
    if head16[:2] == b"\xff\xd8":
        return ".jpg"
    if head16[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if head16[:4] == b"RIFF" and head16[8:12] == b"WEBP":
        return ".webp"
    if head16[:2] == b"BM":
        return ".bmp"
    return None


async def call_vision(image_url: str, prompt: str, timeout: float = 30.0) -> str | None:
    """
    下载图片 → 调 vision.js → 返回文本描述。

    通用图片理解管线，供审核以外的场景（如企鹅识图）复用。
    共享全局 _MIN_INTERVAL 限流，不走 _cache。

    Args:
        image_url:  图片 URL（QQ CDN 等）
        prompt:     给 VL 模型的指令
        timeout:    vision.js 子进程超时秒数

    Returns:
        vl 返回的纯文本；下载/调用失败返回 None
    """
    # ---- 限流（与 check_images 共享 API Key） ----
    global _last_call
    now = time.time()
    wait = _MIN_INTERVAL - (now - _last_call)
    if wait > 0:
        await asyncio.sleep(wait)
    _last_call = time.time()

    # ---- 下载图片 ----
    logger.info(f"[call_vision] 下载图片 | URL:{image_url[:60]}...")
    tmp_path = None
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            image_bytes = resp.content
    except httpx.HTTPStatusError as e:
        logger.warning(f"[call_vision] 下载失败 HTTP{e.response.status_code}")
        return None
    except Exception as e:
        logger.warning(f"[call_vision] 下载异常: {e}")
        return None

    if not image_bytes or len(image_bytes) < 100:
        logger.warning(f"[call_vision] 图片太小({len(image_bytes)}字节)")
        return None

    # ---- 写临时文件 ----
    try:
        suffix = _guess_ext(image_bytes[:16]) or ".jpg"
        tmp_path = _TMP_DIR / f"{hashlib.md5(image_bytes).hexdigest()[:16]}{suffix}"
        tmp_path.write_bytes(image_bytes)
    except Exception as e:
        logger.error(f"[call_vision] 写临时文件失败: {e}")
        return None

    # ---- 调 vision.js ----
    logger.info(f"[call_vision] vision.js | 文件:{tmp_path.name} 大小:{len(image_bytes)}B")
    try:
        proc = await asyncio.create_subprocess_exec(
            "node", _VISION_JS,
            str(tmp_path),
            prompt,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.warning(f"[call_vision] 超时 | 文件:{tmp_path.name}")
        return None
    except FileNotFoundError:
        logger.error(f"[call_vision] vision.js 不存在: {_VISION_JS}")
        return None
    except Exception as e:
        logger.error(f"[call_vision] 进程启动失败: {e}")
        return None
    finally:
        if tmp_path and tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass

    if proc.returncode != 0:
        err_text = stderr.decode("utf-8", errors="replace")[:200] if stderr else ""
        logger.warning(f"[call_vision] vision.js 返回 {proc.returncode} | {err_text}")
        return None

    output = stdout.decode("utf-8", errors="replace").strip()
    logger.info(f"[call_vision] 完成 | 输出前100字: {output[:100]}")
    return output


def _parse_moderation_output(
    output: str, url: str, event: GroupMessageEvent
) -> CheckResult | None:
    """解析 vision.js 返回的 JSON 审核结果"""
    try:
        # 清理可能的 markdown 包裹 & dotenv 诊断信息
        cleaned = output.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:]) if len(lines) > 1 else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
        # 从混合输出中提取 JSON 对象（兜底 dotenv 等库向 stdout 输出诊断信息）
        match = re.search(r'\{[^{}]*"violation"[^{}]*\}', cleaned)
        if match:
            cleaned = match.group()

        data = json.loads(cleaned)

        is_violation = data.get("violation", False)
        if isinstance(is_violation, str):
            is_violation = is_violation.lower() == "true"

        if is_violation:
            category = data.get("category", "违规图片")
            reason = data.get("reason", "")
            matched = f"[图片AI] {category}"
            if reason:
                matched += f" — {reason}"

            logger.info(
                f"[图片检测] ⚠️ 违规 | 群:{event.group_id} 用户:{event.user_id} | "
                f"类别:{category} | 原因:{reason}"
            )

            return CheckResult(
                is_violation=True,
                category=category,
                category_name=category,
                matched_word=matched,
                original_text=f"[图片消息] {url[:80]}",
            )
        else:
            logger.info(
                f"[图片检测] ✅ 合规 | 群:{event.group_id} 用户:{event.user_id}"
            )
            return None

    except json.JSONDecodeError:
        logger.warning(f"[图片检测] JSON解析失败: {output[:100]}")
        return None
