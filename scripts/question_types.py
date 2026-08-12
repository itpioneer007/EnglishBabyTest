"""
★ 题型汇总文件 —— 所有模块共用的题型检测与分派

设计原则：
  1. 题型按 priority 从高到低排列，先匹配到的优先（避免关键词重叠误判）
  2. 每个题型含：priority + keywords（页面文本匹配）+ dom_features（DOM特征）
  3. 检测函数 detect_question_type(xml) 遍历题型表，找到第一个匹配的返回题型名
  4. HANDLER_MAP 将题型名映射到实际处理函数（在 engine.py 里定义）

用法：
  - engine._detect_question_type_cached 改为调用 detect_question_type(xml)
  - 新增题型只需在此文件添加定义，所有模块自动生效
"""

import re

# ── 题型定义（优先级越高越先匹配）──
#   name: 题型标识（对应 engine 的处理函数）
#   priority: 优先级（数字越小越先检测，避免关键词重叠误判）
#   keywords: 页面文本匹配词（任一命中即进入 dom_features 验证）
#   dom_features: DOM 特征验证（可选），满足才确认题型；None=仅关键词匹配即可
#     - has_any: 页面含以下任一特征（class/id文本）
#     - has_all: 页面必须含全部特征
#     - count_gt: 某特征的计数，如 {"EditText": 0} = 至少1个EditText
QUESTION_TYPES = [
    # ── 优先级 1：排序题 ──
    {
        "name": "sort_questions",
        "priority": 1,
        "keywords": [
            "排序", "按顺序", "排序题", "给句子排序",
            "将句子排成", "排成正确的顺序", "按正确顺序排列",
            "连词成句",           # 听力专项·点单词组成句子
            "给图片排序",
        ],
        "dom_features": None,
        "handler": "_handle_sort_question",
        "note": "图片排序/方框排序/圆圈排序/连词成句（内部区分）",
    },
    # ── 优先级 2：匹配题 ──
    {
        "name": "match_questions",
        "priority": 2,
        "keywords": [
            "匹配", "配对", "为人物选择", "选择正确的描述",
        ],
        "dom_features": None,
        "handler": "_handle_match_question",
        "note": "人物-字母匹配 / 人物-图片匹配（字母延迟出现时自动重试）",
    },
    # ── 优先级 3：选词填空 ──
    {
        "name": "select_fill_questions",
        "priority": 3,
        "keywords": [
            "选词填空", "选词", "听音选词",
            "从方框中选择", "选择正确的单词填空",
        ],
        "dom_features": None,  # 关键词已足够特征
        "handler": "_handle_select_fill",
        "note": "句子中嵌空格框(select_tv) + 底部词库(select_btn)，点空格 → 点词填入",
    },
    # ── 优先级 4：补全题（键盘注入）──
    {
        "name": "fill_blank_questions",
        "priority": 4,
        "keywords": [
            "补全表格", "选择正确的选项", "补全", "填空",
            "完成小短文", "填写", "按要求完成句子", "完成句子",
            "句型转换", "改为", "将句子", "任务型阅读",
        ],
        "dom_features": None,  # handler 内部用 EditText 兜底
        "handler": "_handle_fill_blank",
        "note": "表格/短文/句子补全，FastInputIME 键盘注入",
    },
    # ── 优先级 5：阅读多小题 ──
    {
        "name": "reading_multi_questions",
        "priority": 5,
        "keywords": [
            # 无专门关键词；由 dom_features 中"多组字母选项"识别
        ],
        "dom_features": {
            "multi_letter_groups": True,  # 2+ 组字母选项（y聚类）
        },
        "handler": "_handle_reading_multi",
        "note": "阅读理解含多道小题（每组字母=一道小题），需全部点完才出检查",
    },
    # ── 优先级 6：单选/判断（兜底：有 A-E 或 T/F 字母）──
    {
        "name": "single_choice",
        "priority": 6,
        "keywords": None,  # 无关键词，纯靠 DOM 特征
        "dom_features": {
            "has_any_letter": True,  # 有 A-E 或 T/F 字母选项
        },
        "handler": "_handle_single_choice",
        "note": "单选/判断题：点选项 → 检查 → 下一题；是所有选项题的兜底",
    },
]

# ── 题型名 → engine 处理函数 映射 ──
#   engine._answer_loop 根据 map 分派到对应处理函数
HANDLER_MAP = {
    "sort_questions":           "_handle_sort_question",
    "match_questions":          "_handle_match_question",
    "select_fill_questions":    "_handle_select_fill",
    "fill_blank_questions":     "_handle_fill_blank",
    "reading_multi_questions":  "_handle_reading_multi",
    "single_choice":            "_handle_single_choice",
}


def _has_letter_options(xml: str) -> bool:
    """页面是否有 A-E 或 T/F 字母选项（单选/判断特征）"""
    return any(f'text="{c}"' in xml for c in ("A", "B", "T", "F"))


def _has_multi_letter_groups(xml: str) -> bool:
    """页面是否有 2+ 组字母选项（阅读多小题特征）：字母按 y 聚类"""
    opts = []
    for m in re.finditer(r'<node[^>]*text="([TFABCDE])"[^>]*>', xml):
        tag = m.group(0)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if bm:
            x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
            opts.append(((x1 + x2) // 2, (y1 + y2) // 2, y1))
    groups = []
    for o in sorted(opts, key=lambda t: t[2]):
        if groups and abs(o[2] - groups[-1][0][2]) < 150:
            groups[-1].append(o)
        else:
            groups.append([o])
    return len([g for g in groups if len(g) >= 2]) >= 2


def detect_question_type(xml: str) -> str:
    """★ 统一题型检测入口：返回题型名，无匹配返回 None

    按 QUESTION_TYPES 的 priority 顺序遍历，
    关键词命中 + DOM特征验证 = 确认题型。
    """
    for qt in sorted(QUESTION_TYPES, key=lambda x: x["priority"]):
        # 1. 关键词检测（如果定义了）
        kws = qt.get("keywords")
        if kws:
            if not any(kw in xml for kw in kws):
                continue  # 关键词未命中，跳过

        # 2. DOM 特征验证（如果定义了）
        df = qt.get("dom_features")
        if df:
            if df.get("has_any_letter"):
                if not _has_letter_options(xml):
                    continue
            if df.get("multi_letter_groups"):
                if not _has_multi_letter_groups(xml):
                    continue
            if df.get("has_all"):
                if not all(ft in xml for ft in df["has_all"]):
                    continue
            if df.get("has_any"):
                if not any(ft in xml for ft in df["has_any"]):
                    continue

        # 全通过 → 返回题型名
        return qt["name"]

    return None
