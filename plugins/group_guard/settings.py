"""
集中式运行时配置 — 所有"和这台机器有关"的设置都从这里读。

设计原则：配置应当被「发现」，而不是散落在各模块里硬编码。
  - 路径优先从环境变量读，没有再用合理默认值
  - NapCat 目录、版本号自动探测，换机器/升级版本不再静默失败
  - DeepSeek/视觉 API、检测阈值集中一处，调一个旋钮不用翻源码

环境变量（可写在 .env 里，本模块会自动加载）：
  DEEPSEEK_API_KEY     DeepSeek API Key（违规检测/企鹅/安慰）
  DASHSCOPE_API_KEY    视觉模型 API Key（图片审核）
  NAPCAT_DIR           NapCat 安装目录（掉线自动重启用）
  GUARD_CONFIDENCE     违规判定置信度阈值，默认 0.85
  MOYUREN_API_URL      摸鱼人日历 API 地址（每日播报取图），默认作者公开 API
"""

import os
from pathlib import Path

from nonebot import logger


# ============================================================
# .env 加载 — 全项目唯一入口（替代各模块各自手写的 _load_env_file）
# ============================================================
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"


def _load_env_file():
    """把 .env 里的键值灌进 os.environ（不覆盖已存在的真实环境变量）。"""
    if not _ENV_PATH.exists():
        return
    try:
        with open(_ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and not os.environ.get(key):
                    os.environ[key] = value
    except OSError as e:
        logger.warning(f"[配置] 读取 .env 失败: {e}")


_load_env_file()


# ============================================================
# DeepSeek（文本 LLM）
# ============================================================
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# 违规判定置信度阈值 — 核心旋钮（误杀 vs 漏判）。低于此值一律判安全。
GUARD_CONFIDENCE_THRESHOLD = float(os.getenv("GUARD_CONFIDENCE", "0.85"))


# ============================================================
# 摸鱼人日历（每日播报取图）
# ============================================================
# moyuren_server 公开 API；想自建服务时改 .env 里的 MOYUREN_API_URL 即可
MOYUREN_API_URL = os.getenv(
    "MOYUREN_API_URL", "https://api.monkeyray.net/api/v1/moyuren"
)


# ============================================================
# NapCat（掉线自动清理 / 重启用）
# ============================================================
def _discover_napcat_dir() -> Path:
    """探测 NapCat 安装目录：环境变量优先，否则用历史默认路径。"""
    env_dir = os.getenv("NAPCAT_DIR", "").strip()
    if env_dir:
        return Path(env_dir)
    return Path("D:/桌面/NapCat/NapCat.44498.Shell")


NAPCAT_DIR = _discover_napcat_dir()


def napcat_app_dir() -> Path | None:
    """定位 NapCat 的 resources/app/napcat 目录，自动适配版本号。

    优先扫描 versions/ 下的实际版本目录，避免把版本号写死，
    NapCat 升级后路径仍然有效。找不到返回 None。
    """
    versions_root = NAPCAT_DIR / "versions"
    if not versions_root.is_dir():
        return None
    # 取存在 resources/app/napcat 的版本目录（通常只有一个）
    candidates = sorted(
        (d for d in versions_root.iterdir() if d.is_dir()),
        reverse=True,  # 版本号倒序，优先最新
    )
    for ver in candidates:
        app_dir = ver / "resources" / "app" / "napcat"
        if app_dir.is_dir():
            return app_dir
    return None


# QQ 会话数据目录（登录态存储位置）
QQ_DATA_DIR = Path(os.environ.get("APPDATA", "")) / "QQ"


# ============================================================
# 数据目录（与 store.py 共用同一根）
# ============================================================
DATA_DIR = Path(__file__).parent / "data"
