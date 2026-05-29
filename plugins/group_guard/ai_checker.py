"""
AI 语义判断模块 - 使用 DeepSeek API 进行深度违规识别

当关键词匹配漏掉时，交给 AI 做语义级判断。AI 能识别：
- 隐喻、黑话、绕弯子
- 上下文中的隐含违规意图
- 新出现的变体表达方式
"""

import json
import os
import time
import re
from pathlib import Path
from dataclasses import dataclass
from openai import OpenAI

from .checker import CheckResult


# 手动加载 .env 文件（兼容 NoneBot 的 env 加载机制）
def _load_env_file():
    """从 .env 文件加载环境变量"""
    # 查找项目根目录的 .env
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key not in os.environ or not os.environ[key]:
                        os.environ[key] = value

_load_env_file()

# DeepSeek API 配置
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 从环境变量读取 API Key
API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# 群规判定提示词
SYSTEM_PROMPT = """你是QQ群内容审核员。判断群聊消息是否违反以下群规。

【群红线 - 严禁以下内容（含所有谐音/变体/拼音缩写）】
1. 辱骂/人身攻击/诅咒：所有骂人的话、诅咒他人或家人死亡、侮辱人格等
2. R18/NSFW：色情、露骨、约炮、性行为描述、擦边球、色情资源分享
3. 暴力血腥：虐待、自残、虐杀、血腥视频
4. 违法内容：毒品、诈骗、违禁品、假证代考
5. 政治敏感：台独港独藏独疆独、邪教、法轮功、颠覆政权
6. 炼铜/未成年：涉及未成年色情或不当内容
7. 赌博：赌博平台、赌球、菠菜、诱导话术
8. 反家庭伦理：乱伦、NTR、换妻

【核心：识别谐音/形近/拼音/拆字变体】

★★★ 辱骂/诅咒类（重点检测！）★★★

"妈"的变体：冯/马/🐴/吗/麻/木/姆/母
"死"的变体：四/斯/丝/私/寺/屎/💩/逝
"逼"的变体：福/笔/比/币/碧/b
"操/草"的变体：曹/槽/艹/肏/草
"傻"的变体：煞/沙/砂/纱
"你"的变体：尼/妮/腻/拟
"全"的变体：劝/权/泉/拳/犬
"家"的变体：佳/嫁/架/加
"没"的变体：美/梅/煤/眉/每
"母"的变体：木/目/姆/牡/墓
"亲"的变体：琴/勤/芹/禽/寝
"了"的变体：乐/勒/叻/啦

拼音缩写：sb(傻逼) | nmsl(你妈死了) | cnm/cnmb(操你妈逼) | rnm(日你妈) | wc(卧槽) | tmd/tm(他妈的) | md(妈的) | zz(智障) | fw(废物) | nt(脑瘫) | ns(你死) | cs(畜生)

经典骂人话及其所有变体（必须全部拦截）：
- "傻逼" → 傻福/煞笔/沙比/sb/s b/5b
- "你妈死了" → 尼冯四了/你🐴私了/尼玛丝了/你冯④了/尼木四了/nmsl/你没🐴了/你冯没了
- "操你妈" → 草拟吗/曹尼玛/艹你冯/cnm/cnmb/草你🐴
- "你全家死了" → 你劝架四了/尼全佳私了/你犬家④了/你家全没了
- "你没母亲" → 你没木琴/尼没🐴/你没木亲/你没姆琴
- "你妈没了" → 尼冯美了/你🐴每了/你冯梅了
- "操你妈逼" → 草拟吗福/艹你冯笔/cnmb
- "日你妈" → 曰你冯/rnm/日尼玛
- "废物" → 飞舞/废狗/fw/f5
- "智障" → 纸张/制杖/zz/睿智（讽刺意味时）
- "畜生" → 畜牲/处生/cs/出生（骂人语境）
- "吃屎" → 痴四/吃💩/赤石

死亡诅咒类（严重违规，必须拦截）：
"xx死了""xx没了""xx私了""xx④了""xx无了""xx不见了"
结合"你/你妈/你爸/你全家/你劝架/尼冯/尼木/尼🐴"等前缀 → 必判违规

【绝不算违规的情况】
- 宠物/动物日常："我家狗""坏狗狗""猫猫""修狗""狗子""小猫" → ❌不算
- 人名/外号/自称："狗三""狗哥""大狗""小猫""老狗" → ❌不算
- 朋友互损："你真狗""你好菜""好狗啊" → ❌不算
- 游戏动漫讨论、学习工作、情感吐槽、日常聊天 → ❌不算
- 单个字碰巧同音但不是骂人意思（"服了"不是"福了"） → ❌不算
- "狗"单独出现、讨论宠物、打游戏说"狗了""苟住" → ❌不算
- "绷不住了""笑死""我死"之类自嘲 → ❌不算
- "坏狗狗""傻狗""笨狗"形容宠物/开玩笑 → ❌不算

【判断核心逻辑】
1. 先看整句话的恶意程度：诅咒他人或家人死亡/侮辱人格 → 违规
2. 多个谐音字组合出现（如"傻福"+"你冯"+"四了"） → 99%是骂人 → 违规
3. 在吵架/对骂上下文中 → 降低阈值，更倾向于判违规
4. 正常聊天、开玩笑、讨论宠物 → 放过
5. 拿不准的时候，问自己：这句话如果当面说，对方会生气吗？会 → 判违规

【输出格式】只输出一个JSON：
{"violation": true/false, "category": "辱骂"或"R18"或"赌博"等, "reason": "识别到的变体→还原"}
{"violation": false, "category": "", "reason": ""}"""


@dataclass
class AiCheckResult:
    """AI 检测完整结果"""
    is_violation: bool
    category: str | None
    reason: str
    latency_seconds: float
    error: str | None


class DeepSeekChecker:
    """DeepSeek AI 违规检测器"""

    def __init__(self):
        if not API_KEY:
            self.client = None
            print("[AI检测] ⚠️ 未配置 DEEPSEEK_API_KEY，AI 检测不可用")
            return
        self.client = OpenAI(
            api_key=API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        print(f"[AI检测] ✅ DeepSeek 已就绪，模型: {DEEPSEEK_MODEL}")

    def is_available(self) -> bool:
        """检查 AI 检测是否可用"""
        return self.client is not None

    def check(self, text: str) -> AiCheckResult:
        """
        使用 AI 判断消息是否违规

        Args:
            text: 要检查的消息文本

        Returns:
            AiCheckResult
        """
        if not self.client:
            return AiCheckResult(
                is_violation=False,
                category=None,
                reason="AI检测不可用(无API Key)",
                latency_seconds=0,
                error="NO_API_KEY",
            )

        start = time.time()

        try:
            response = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                max_tokens=150,
                temperature=0.0,        # 0温度，保证一致性
            )

            latency = time.time() - start
            raw = response.choices[0].message.content.strip()

            # 解析 JSON 响应
            result = self._parse_response(raw)

            # 如果解析失败，不标记违规（宁可漏过不可误杀）
            if result is None:
                print(f"[AI检测] ⚠️ JSON解析失败，原始响应: {raw[:200]}")
                return AiCheckResult(
                    is_violation=False,
                    category=None,
                    reason="AI响应解析失败",
                    latency_seconds=latency,
                    error="PARSE_ERROR",
                )

            # 字段名映射：AI返回 "violation" → dataclass "is_violation"
            if "violation" in result:
                result["is_violation"] = result.pop("violation")

            result["latency_seconds"] = latency
            result["error"] = None

            return AiCheckResult(**result)

        except Exception as e:
            latency = time.time() - start
            error_msg = f"{type(e).__name__}: {e}"
            print(f"[AI检测] ❌ 调用失败: {error_msg}")
            return AiCheckResult(
                is_violation=False,
                category=None,
                reason=f"API调用失败: {error_msg}",
                latency_seconds=latency,
                error=error_msg,
            )

    def _parse_response(self, raw: str) -> dict | None:
        """解析 AI 返回的 JSON"""
        # 清理可能的 markdown 代码块标记
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)
            if len(cleaned) > 1:
                cleaned = "\n".join(cleaned[1:])
            else:
                cleaned = cleaned[0]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 尝试提取第一个 JSON 对象
        import re
        match = re.search(r'\{[^{}]*"violation"[^{}]*\}', raw)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        return None


# 全局单例
_checker: DeepSeekChecker | None = None


def get_ai_checker() -> DeepSeekChecker:
    """获取 AI 检测器单例"""
    global _checker
    if _checker is None:
        _checker = DeepSeekChecker()
    return _checker
