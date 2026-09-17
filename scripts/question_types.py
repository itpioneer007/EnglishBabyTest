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
            "给图片排序", "组成一段通顺的对话", "通顺的对话",
        ],
        "dom_features": None,
        "handler": "_handle_sort_question",
        "note": "图片排序/方框排序/圆圈排序/连词成句（内部区分）★ 30题'给下列句子排序，组成一段通顺的对话'：直接点句子→序号自动排（_handle_sentence_sort）",
    },
    # ── 优先级 2：匹配题（含字母连线）──
    {
        "name": "match_questions",
        "priority": 2,
        "keywords": [
            "匹配", "配对", "为人物选择", "选择正确的描述",
            "字母连线", "大小写字母连线", "连线", "将下列", "与对应的小写",
        ],
        "dom_features": {
            # ★ 字母连线题: 左右两列多行可点节点（左右各 2+ 个 y 聚类、x 明显分两列）
            "two_column_clickable": True,
        },
        "handler": "_handle_match_question",
        "note": "人物-字母匹配 / 字母延迟出现时自动重试 / 字母连线（左右点配对）",
    },
    # ── 优先级 3：字母块补全单词（必须早于 select_fill！）──
    #   ★ 2026-09-15 新增（用户反馈"这道题目为什么app识别不了"）：
    #     物理结构与选词填空**完全同构**（select_tv 空位 + select_btn 词库），
    #     区别只在"词"是**单个字母**：填的不是单词，而是用字母块补齐首字母之后的剩余字母
    #     （如已给 b + 提示"通过，凭借（做某事）" → 点 y 组成 by）。
    #     若不单独识别，会被 select_fill 的结构兜底抢走 → 该 handler 的
    #     `[A-Za-z]{2,}` 词长过滤 + y1500-2250 词库位置过滤双双不命中 → 空转。
    {
        "name": "letter_fill_questions",
        "priority": 3,
        "keywords": None,   # ★ 纯 DOM 判据（不看关键词）：
                            #   题干变体多（"根据中文提示…"/"听录音…"/"看图…"），
                            #   而 select_tv+单字母select_btn 的结构特征已足够唯一；
                            #   关键词一旦漏配就会退回 select_fill 空转（本次 bug 成因）。
        "dom_features": {
            # ★ 只要有 select_tv 空位 + select_btn 全是"单字母"就成立（不看关键词，
            #   因为题干可能是"听录音，选择正确的字母补全单词"等变体）
            "letter_tiles": True,
        },
        "handler": "_handle_letter_fill",
        "note": "字母块补全单词：已给首字母 + select_tv 空位 + 单字母 select_btn；点字母自动填空位",
    },
    # ── 优先级 3：选词填空（+ 看图选词 复用同一处理）──
    {
        "name": "select_fill_questions",
        "priority": 3,
        "keywords": [
            "选词填空", "选词", "听音选词",
            "从方框中选择", "选择正确的单词填空",
            "看图选词", "看图片选词", "选择对应的单词", "看图选择对应的单词",
            "选择正确的图片", "看图选",
        ],
        "dom_features": None,  # 关键词已足够特征
        "handler": "_handle_select_fill",
        "note": "句子中嵌空格框(select_tv) + 底部词库(select_btn)或顶部图片，点空格 → 点词/图填入",
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
    "letter_fill_questions":    "_handle_letter_fill",
    "select_fill_questions":    "_handle_select_fill",
    "fill_blank_questions":     "_handle_fill_blank",
    "reading_multi_questions":  "_handle_reading_multi",
    "single_choice":            "_handle_single_choice",
}


def _has_letter_options(xml: str) -> bool:
    """页面是否有 A-E 或 T/F 字母选项（单选/判断特征）"""
    return any(f'text="{c}"' in xml for c in ("A", "B", "T", "F"))


def _has_two_column_clickable(xml: str) -> bool:
    """★ 字母连线题特征：左右两列各 2+ 个可点节点（x 明显分两列、y 范围接近）

    判定：筛 clickable 节点（x 中心点），按 x 聚成两簇，
    每簇 2+ 个点、x 中心差 > 200、y 中心差 < 300。
    """
    import re as _re
    nodes = []
    for m in _re.finditer(r'<node[^>]*clickable="true"[^>]*>', xml):
        tag = m.group(0)
        bm = _re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not bm:
            continue
        x1, y1, x2, y2 = map(int, bm.groups())
        # 排除顶部/底部导航与全屏容器
        if y1 < 200 or y2 > 2250 or (x2 - x1) > 500 or (y2 - y1) > 500:
            continue
        # 排除极小可点节点（圆圈等噪点）
        if (x2 - x1) < 50 or (y2 - y1) < 50:
            continue
        nodes.append(((x1 + x2) // 2, (y1 + y2) // 2))
    if len(nodes) < 4:
        return False
    # 按 x 聚成两簇
    nodes.sort()
    left, right = [nodes[0]], [nodes[-1]]
    for n in nodes[1:-1]:
        (left if abs(n[0] - sum(p[0] for p in left) / len(left)) <
                  abs(n[0] - sum(p[0] for p in right) / len(right)) else right).append(n)
    if len(left) < 2 or len(right) < 2:
        return False
    lx_avg = sum(p[0] for p in left) / len(left)
    rx_avg = sum(p[0] for p in right) / len(right)
    if abs(rx_avg - lx_avg) < 200:
        return False
    ly_avg = sum(p[1] for p in left) / len(left)
    ry_avg = sum(p[1] for p in right) / len(right)
    if abs(ly_avg - ry_avg) > 300:
        return False
    return True


def _has_letter_tiles(xml: str) -> bool:
    """★ 字母块补全单词题特征（2026-09-15）

    判据 = 有 select_tv 空位 **且** 所有 select_btn 文本都是"单个英文字母"。
      - 选词填空的 select_btn 是单词/短语（≥2 字符）→ 不会误判；
      - 要求至少 2 个字母块（单块不足以证明是字母池）。
    属性顺序按 dump 实际：text 在 resource-id 之前，故一次性只在 tag 内分别取。
    """
    if "select_tv" not in xml:
        return False
    cnt = 0
    for m in re.finditer(r"<node\b[^>]*>", xml):
        tag = m.group(0)
        if "select_btn" not in tag:
            continue
        tm = re.search(r'text="([^"]*)"', tag)
        t = (tm.group(1) if tm else "").strip()
        if not t:
            continue
        if not re.fullmatch(r"[A-Za-z]", t):
            return False        # 有一个不是单字母 → 是真单词库（选词填空）
        cnt += 1
    return cnt >= 2


def parse_letter_fill(xml: str) -> dict:
    """解析「字母块补全单词」页 → dict(prefix, slots, tiles, hint, cap)

    实测结构（湘少六上 U1 单元自检，2026-09-15，真机 dump 见 tmp_gen/letter_fill_q15.xml）：
      tv_caption      : 题干（"根据中文提示，选择正确的字母补全单词。(共1分)"）
      question_flexbox: question_title_tv(已给首字母，如 "b") + select_tv(CheckBox 空位)
                        ★ 中文提示 "[通过，凭借（做某事）]" 会被 flexbox 按字宽拆成
                          多个 question_title_tv 片段 + 独立 "[" / "]" 文本节点
      option_flexbox  : select_btn（TextView，单个字母）+ 外层 clickable LinearLayout

    slots/tiles 元素: {"text": str, "b": (x1, y1, x2, y2)}
    属性顺序在 uiautomator dump 里是 text 在 resource-id 之前，但这里**各自独立搜索**，
    不依赖顺序，避免不同版本 dump 顺序变化导致失效。
    """
    ns = []
    for m in re.finditer(r"<node\b[^>]*>", xml):
        tag = m.group(0)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not bm:
            continue
        rid = re.search(r'resource-id="([^"]*)"', tag)
        tm = re.search(r'text="([^"]*)"', tag)
        ns.append({
            "rid": (rid.group(1).split("/")[-1] if rid else ""),
            "text": (tm.group(1) if tm else ""),
            "b": tuple(int(v) for v in bm.groups()),
        })
    slots = [n for n in ns if n["rid"] == "select_tv"]
    tiles = [n for n in ns if n["rid"] == "select_btn" and n["text"].strip()]
    cap = next((n["text"] for n in ns if n["rid"] == "tv_caption"), "")
    # 已给首字母 = 第一个空位**左侧**的纯字母 question_title_tv（中文提示片段非 ASCII，自动排除）
    prefix = ""
    if slots:
        sx = min(s["b"][0] for s in slots)
        for n in ns:
            if (n["rid"] == "question_title_tv" and n["b"][2] <= sx
                    and re.fullmatch(r"[A-Za-z]+", n["text"].strip())):
                prefix += n["text"].strip()
    # 中文提示 = 页面文本里 [] 之间的内容（拼接后再搜，被拆散的片段能拼回整句）
    alltext = "".join(n["text"] for n in ns)
    hm = re.search(r"\[([^\[\]]{1,40})\]", alltext)
    return {
        "prefix": prefix,
        "slots": slots,
        "tiles": tiles,
        "hint": (hm.group(1).strip() if hm else ""),
        "cap": cap,
    }


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
            if df.get("letter_tiles"):
                # ★ 字母块补全单词：select_tv 空位 + 单字母 select_btn
                if not _has_letter_tiles(xml):
                    continue
            if df.get("two_column_clickable"):
                # ★ 字母连线题特征：左右两列各 2+ 个可点节点（x 明显分两列、y 范围接近）
                if not _has_two_column_clickable(xml):
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
