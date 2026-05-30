"""
违规检测结果数据结构

注意：MessageChecker（关键词匹配检测器）已废弃。
项目现在统一使用 ai_checker.py 中的 DeepSeek AI 检测。
保留此文件仅用于 CheckResult 数据类。
"""

from dataclasses import dataclass


@dataclass
class CheckResult:
    """检测结果"""
    is_violation: bool          # 是否违规
    category: str | None        # 违规类别 key
    category_name: str | None   # 违规类别名称
    matched_word: str | None    # 匹配到的关键词/模式
    original_text: str          # 原始消息文本
