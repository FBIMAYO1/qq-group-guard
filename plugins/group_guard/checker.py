"""
违规检测器 - 对消息内容进行规则匹配
"""

import re
from dataclasses import dataclass

from .rules import get_all_rules, RuleCategory


@dataclass
class CheckResult:
    """检测结果"""
    is_violation: bool          # 是否违规
    category: str | None        # 违规类别 key
    category_name: str | None   # 违规类别名称
    matched_word: str | None    # 匹配到的关键词/模式
    original_text: str          # 原始消息文本


class MessageChecker:
    """消息违规检测器"""

    def __init__(self):
        self.rules = get_all_rules()
        # 预编译正则表达式以提高性能
        self._compiled_patterns: dict[str, list[re.Pattern]] = {}
        for key, rule in self.rules.items():
            self._compiled_patterns[key] = [
                re.compile(p, re.IGNORECASE) for p in rule.patterns
            ]

    def check(self, text: str) -> CheckResult:
        """
        检测消息是否违规

        Args:
            text: 消息文本内容

        Returns:
            CheckResult 检测结果
        """
        if not text or not text.strip():
            return CheckResult(
                is_violation=False,
                category=None,
                category_name=None,
                matched_word=None,
                original_text=text or "",
            )

        # 预处理：统一小写，去除多余空格
        normalized = text.lower().strip()
        # 去除空格和特殊字符的版本（防止 "色 图" 这种绕过）
        compact = re.sub(r"[\s​　·.。,，!！?？]+", "", normalized)

        for key, rule in self.rules.items():
            # 1. 关键词匹配
            result = self._check_keywords(key, rule, normalized, compact, text)
            if result:
                return result

            # 2. 正则匹配
            result = self._check_patterns(key, rule, normalized, text)
            if result:
                return result

        return CheckResult(
            is_violation=False,
            category=None,
            category_name=None,
            matched_word=None,
            original_text=text,
        )

    def _check_keywords(
        self,
        key: str,
        rule: RuleCategory,
        normalized: str,
        compact: str,
        original: str,
    ) -> CheckResult | None:
        """关键词匹配检测"""
        for keyword in rule.keywords:
            kw_lower = keyword.lower()
            # 在原文和去空格版本中都检查
            if kw_lower in normalized or kw_lower in compact:
                return CheckResult(
                    is_violation=True,
                    category=key,
                    category_name=rule.name,
                    matched_word=keyword,
                    original_text=original,
                )
        return None

    def _check_patterns(
        self,
        key: str,
        rule: RuleCategory,
        normalized: str,
        original: str,
    ) -> CheckResult | None:
        """正则模式匹配检测"""
        for pattern in self._compiled_patterns[key]:
            match = pattern.search(normalized)
            if match:
                return CheckResult(
                    is_violation=True,
                    category=key,
                    category_name=rule.name,
                    matched_word=f"[正则匹配] {match.group()}",
                    original_text=original,
                )
        return None


# 全局单例
_checker: MessageChecker | None = None


def get_checker() -> MessageChecker:
    """获取检测器单例"""
    global _checker
    if _checker is None:
        _checker = MessageChecker()
    return _checker
