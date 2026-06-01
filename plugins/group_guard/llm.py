"""
DeepSeek LLM 调用封装 — 收口所有"建客户端 → 调用 → 清洗 → 兜底"的样板。

各模块原本各自写一遍：取 client、try/except、剥 markdown 围栏、json.loads、
失败静默降级。这里抽成两个异步函数，调用方只关心 prompt 和返回值。

  chat_text(system, user)  → 纯文本回复，失败返回 None
  chat_json(system, user)  → 解析后的 dict，失败返回 None

全部基于 AsyncOpenAI，不阻塞事件循环。客户端复用 ai_checker 的单例。
"""

import json

from nonebot import logger

from .ai_checker import get_openai_client
from .settings import DEEPSEEK_MODEL


def _strip_markdown_fence(raw: str) -> str:
    """去掉 AI 回复里可能包裹的 ```json ... ``` 围栏，返回纯内容。"""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("\n", 1)
        cleaned = parts[1] if len(parts) > 1 else cleaned
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()
    return cleaned


async def chat_text(
    system: str,
    user: str,
    *,
    temperature: float = 0.7,
    max_tokens: int = 200,
) -> str | None:
    """调用 DeepSeek 返回纯文本。无 client 或异常时返回 None（静默降级）。"""
    client = get_openai_client()
    if client is None:
        return None
    try:
        response = await client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = response.choices[0].message.content
        return content.strip() if content else None
    except Exception as e:
        logger.warning(f"[LLM] 文本调用失败: {type(e).__name__}: {e}")
        return None


async def chat_json(
    system: str,
    user: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 200,
) -> dict | None:
    """调用 DeepSeek 并解析为 JSON dict。任意环节失败返回 None。"""
    raw = await chat_text(
        system, user, temperature=temperature, max_tokens=max_tokens
    )
    if not raw:
        return None
    try:
        result = json.loads(_strip_markdown_fence(raw))
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        logger.warning(f"[LLM] JSON 解析失败，原始回复: {raw[:120]}")
        return None
