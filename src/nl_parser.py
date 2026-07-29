"""
英语宝自动化 — 自然语言解析器 (NL Parser)
===========================================

"听懂人话"：接收一段中文指令，分析含义，输出结构化自动化计划。

用户示例：
  "切换至新湘少五年级上册的第六单元听力专项模块"
  "帮我检测新湘鲁六年级上册U6-U9听力专项"
  "人教版三年级下册第一单元基础巩固"

输出格式：
  {
    "raw": "<原始文本>",
    "version": "湘少版(2024审定)",     # APP 中实际版本名
    "grade": "五年级上册",               # 年级
    "units": [6, 7, 8, 9],              # 要跑的单元列表
    "module": "听力专项",                # 模块名（在专项突破/教材精学下）
    "stage": "",                        # 关卡/阶段（如基础巩固，可选）
    "confidence": 0.95                  # 解析置信度
  }

规则：
  - 所有版本默认 2024审定版（新版本书籍）
  - 找不到的字段返回空，不硬猜
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AutomationPlan:
    """一次自动化任务的完整计划"""
    raw: str = ""
    version: str = ""          # APP 中实际版本名，如 "湘少版(2024审定)"
    grade: str = ""            # 年级，如 "五年级上册"
    units: list[int] = field(default_factory=list)  # 单元号列表
    module: str = ""           # 模块名
    stage: str = ""            # 关卡阶段（可选）
    confidence: float = 0.0

    def summary(self) -> str:
        parts = []
        if self.version:
            parts.append(self.version)
        if self.grade:
            parts.append(self.grade)
        if self.units:
            u = self.units
            if len(u) == 1:
                parts.append(f"U{u[0]}")
            else:
                parts.append(f"U{u[0]}-U{u[-1]}")
        if self.module:
            parts.append(self.module)
        if self.stage:
            parts.append(f"[{self.stage}]")
        return " → ".join(parts) if parts else "(空计划)"


# ============================================================
# 映射表
# ============================================================

# 人说 → APP 中显示
VERSION_MAP = {
    "新湘少": "湘少版(2024审定)",
    "湘少版": "湘少版(2024审定)",
    "湘少":   "湘少版(2024审定)",
    "新湘鲁": "湘鲁版(2024审定)",
    "湘鲁版": "湘鲁版(2024审定)",
    "湘鲁":   "湘鲁版(2024审定)",
    "人教版": "人教版(PEP)(2024审定)",
    "PEP":   "人教版(PEP)(2024审定)",
    "人教":   "人教版(PEP)(2024审定)",
    "教科版": "教科版(2024审定)",
    "教科":   "教科版(2024审定)",
}

# 年级简写 → 全称（注意：可能出现"一下"副词误匹配）
GRADE_ABBREV = {
    "一上": "一年级上册", "一下": "一年级下册",
    "二上": "二年级上册", "二下": "二年级下册",
    "三上": "三年级上册", "三下": "三年级下册",
    "四上": "四年级上册", "四下": "四年级下册",
    "五上": "五年级上册", "五下": "五年级下册",
    "六上": "六年级上册", "六下": "六年级下册",
}

# 简写模式：跟在版本名之后的 "X上"/"X下" 才是年级，不是副词"一下"
# 例: "新湘鲁六上" → "六上"是年级; "跑一下" → "一下"不是年级
GRADE_ABBREV_SAFE = re.compile(
    r"(?<![的一])"                     # 前面不是"的"或"一"（排除"一下"副词）
    r"([二三四五六])\s*(上|下)"         # 二上~六上，排除"一"（太容易撞"一下"副词）
    r"(?!册)"                         # 后面不跟"册"（留给全称匹配）
)

GRADE_PATTERN = re.compile(
    r"(一|二|三|四|五|六|1|2|3|4|5|6)\s*年级\s*(上册|下册|下|上)?",
)

UNIT_RANGE_PATTERN = re.compile(r"U\s*(\d+)\s*[-~至到]\s*U?\s*(\d+)", re.I)
UNIT_SINGLE_PATTERN = re.compile(r"(?:第\s*)?U\s*(\d+)\s*(?:单元)?", re.I)
UNIT_CHINESE_PATTERN = re.compile(r"第\s*([一二三四五六七八九十]+)\s*单元")

MODULE_PATTERNS = [
    ("听力专项", "听力专项"),
    ("基础巩固", "基础巩固"),
    ("课本点读", "课本点读"),
    ("巧记单词", "巧记单词"),
    ("语音评测", "语音评测"),
    ("一课一练", "一课一练"),
    ("基础训练", "基础训练"),
    ("听课文", "听课文"),
    ("课文动画", "课文动画"),
    ("课文配音", "课文配音"),
    ("口语训练", "口语训练"),
    ("复习回顾", "复习回顾"),
    ("全脑记词", "全脑记词"),
    ("单词听写", "单词听写"),
    ("诵读讲解", "诵读讲解"),
    ("知识过关", "知识过关"),
    ("趣味练习", "趣味练习"),
    ("限免专区", "限免专区"),
]

CHINESE_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "十一": 11, "十二": 12,
}


# ============================================================
# 解析器
# ============================================================

def parse(text: str) -> AutomationPlan:
    """
    解析自然语言指令 → AutomationPlan。
    返回的 version 字段已经是 APP 中实际显示的版本名。
    """
    plan = AutomationPlan(raw=text)
    score = 0.0

    # ---- 1. 版本 ----
    for key, val in VERSION_MAP.items():
        if key in text:
            plan.version = val
            score += 0.3
            break

    # ---- 2. 年级 ----
    # 先试完整写法: "五年级上册"
    full_match = re.search(
        r"(一|二|三|四|五|六|1|2|3|4|5|6)\s*年级\s*(上册|下册)",
        text,
    )
    if full_match:
        num = full_match.group(1)
        sem = full_match.group(2)
        num_cn = {"1": "一", "2": "二", "3": "三", "4": "四", "5": "五", "6": "六"}.get(num, num)
        plan.grade = f"{num_cn}年级{sem}"
        score += 0.2
    else:
        # 简写: 从安全模式匹配，排除"一下"副词
        safe_matches = GRADE_ABBREV_SAFE.findall(text)
        if safe_matches:
            num, sem = safe_matches[0]
            abbr = f"{num}{sem}"
            plan.grade = GRADE_ABBREV.get(abbr, "")
            if plan.grade:
                score += 0.2

    # ---- 3. 单元 ----
    # U6-U9 范围
    range_match = UNIT_RANGE_PATTERN.search(text)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        plan.units = list(range(start, end + 1))
        score += 0.2
    else:
        # 单个 "U6"
        single = UNIT_SINGLE_PATTERN.findall(text)
        if single:
            plan.units = [int(u) for u in single]
            score += 0.2

    # 中文 "第六单元"
    cn = UNIT_CHINESE_PATTERN.findall(text)
    for cn_num in cn:
        n = CHINESE_NUM.get(cn_num, 0)
        if n and n not in plan.units:
            plan.units.append(n)
    if cn:
        score += max(0.2, score)

    # ---- 4. 模块 ----
    for pattern, module_name in MODULE_PATTERNS:
        if pattern in text:
            plan.module = module_name
            score += 0.15
            break

    # ---- 5. 阶段(关卡) ----
    for stage_name in ["基础巩固", "进阶训练", "综合练习", "测试"]:
        if stage_name in text:
            plan.stage = stage_name
            score += 0.1
            break

    plan.confidence = min(score, 1.0)
    return plan


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    tests = [
        "切换至新湘少五年级上册的第六单元听力专项模块",
        "帮我检测新湘鲁六年级上册U6-U9听力专项",
        "人教版三年级下册第一单元基础巩固",
        "湘少版四下课本点读U3-U5",
        "切换至人教版五年级上册听力专项第一单元",
        "请帮我跑一下新湘鲁六上U6到U9的听力专项",
        "教科版四年级下册巧记单词第六单元",
    ]
    for t in tests:
        p = parse(t)
        print(f"\n📝 输入: {t}")
        print(f"   → 版本={p.version!r}  年级={p.grade!r}  单元={p.units}  模块={p.module!r}  阶段={p.stage!r}")
        print(f"     置信度={p.confidence:.0%}  摘要: {p.summary()}")
