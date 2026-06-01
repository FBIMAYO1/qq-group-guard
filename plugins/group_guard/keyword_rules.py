"""
关键词预检词库 — AI 调用前的快速命中表。

把直接命中的违规模式从主入口 __init__.py 抽出来单独管理。
主入口只负责装配，违规词库不该住在装配文件里。

新增模式：往 KEYWORD_VIOLATIONS 里加一条 (正则, 类别, 原因说明) 即可。
所有正则在模块加载时编译一次。
"""

import re

# (正则, 类别, 原因说明)
KEYWORD_VIOLATIONS: list[tuple[re.Pattern, str, str]] = [
    # === R18 色情 ===
    (re.compile(r'自慰|zw\b'), "R18", "直接提及自慰"),
    (re.compile(r'扫福瑞|sofree|骚福瑞|sao.*福瑞'), "R18", "涉黄内容"),
    (re.compile(r'口交|口\s*交|kj\b'), "R18", "直接提及口交"),
    (re.compile(r'抠你的|扣你的'), "R18", "涉黄暗示"),
    (re.compile(r'颜射|颜\s*射'), "R18", "直接提及颜射"),
    (re.compile(r'高潮|高\s*潮|gc\b'), "R18", "直接提及高潮"),
    (re.compile(r'坐上来自己动|坐上来.*动'), "R18", "涉黄内容"),
    # === 辱骂 ===
    (re.compile(r'操你|草你|艹你|曹你|肏你'), "辱骂", "直接辱骂"),
    (re.compile(r'傻逼|sb\b|5b\b|傻福|煞笔|沙比|纱碧|傻杯'), "辱骂", "直接辱骂"),
    (re.compile(r'cnm|cnmb|操你妈|草你妈|艹你妈'), "辱骂", "直接辱骂"),
    (re.compile(r'nmsl|你妈死了|你冯死了|你🐴死了'), "辱骂", "直接辱骂"),
]


# 已知无害的拼音缩写/网络用语（跳过 AI，避免误判）
# "zdjd"=真的假的 "yysy"=有一说一 "nsdd"=你说得对 "xswl"=笑死我了 等
SAFE_ABBREVS: set[str] = {
    "zdjd", "yysy", "nsdd", "xswl", "awsl", "yyds", "dbq",
    "srds", "u1s1", "tql", "pyq", "bhys", "nbsl", "zqsg",
    "pljj", "plmm", "xjj", "xgg", "gkd", "bdjw", "lgld",
    "y1s1", "jjww", "ybb", "wl", "ky", "bp", "blx",
}
