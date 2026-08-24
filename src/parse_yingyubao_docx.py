"""
parse_yingyubao_docx.py — 英语宝 DOCX 脚本解析器（公共骨架 + 模块格式策略）

设计（2026-08-24 重构，由"听力专项专用解析器"演进为"公共骨架 + 模块策略"）：
  ------------------------------------------------------------------
  公共骨架（本文件）：
    - docx 读取 → 段落流（parse()）
    - 单元识别 _detect_unit()：兼容 "Unit 6" / "五上U6" / "U6" 写法
    - 全局题号分配 _assign_global_idx()（跨单元/跨阶段连续，qid 依赖它）
    - 策略分派：按 STRATEGIES 顺序尝试 detect()，首个命中即用该策略解析
  ------------------------------------------------------------------
  模块策略（每模块一个策略类，新增模块只加一个类并注册到 STRATEGIES）：
    - ListeningStrategy  听力专项（原 parse 逻辑）：
        阶段(基础巩固/综合进阶/难点突破) + 每题 选项/录音/答案 + 独立元数据块
    - OralStrategy       口语训练（原 parse_oral_paragraphs 逻辑）：
        大题(一、二、三、四)·小题列表 + 句型提示/听力材料/参考答案/关键词
        + 元数据块挂到大题所有小题
  ------------------------------------------------------------------
  脚本格式示例：
    听力专项：Unit 6 / 基础巩固 / 一、听录音... / 1. 情景... / A. xxx B. xxx /
             录音：xxx / 答案：B / 一级题型：... / 二级题型：... / 难度：... / 关键词：...
    口语训练：口语训练新湘少版五上U6 / 一、朗读单词。（15分） / 1. try 2. scarf ...
             一级题型：朗读 / ... / 参考答案：xxx / 关键词：xxx
"""

from dataclasses import dataclass, field
from docx import Document
import re


@dataclass
class YingYuBaoQuestion:
    """英语宝题目完整数据结构"""
    global_idx: int = 0              # 全局题号 (1-160)
    unit: int = 0                    # 单元 (6/7/8/9)
    stage: str = ""                  # 阶段: 基础巩固/综合进阶/难点突破（听力专项）
    stage_idx: int = 0               # 阶段内/大题内题号
    stem: str = ""                   # 题干
    options: list = field(default_factory=list)  # 选项 [A.xxx, B.xxx, C.xxx]
    recording: str = ""              # 录音原文
    answer: str = ""                 # 正确答案/参考答案
    type_1: str = ""                 # 一级题型
    type_2: str = ""                 # 二级题型
    difficulty: str = ""             # 难度
    keywords: list = field(default_factory=list)
    knowledge_points: list = field(default_factory=list)
    skill: str = ""
    cognitive_target: str = ""
    # ★ 口语训练专用字段（2026-08-24 新增，其他模块不受影响）
    big: int = 0                     # 大题序号（1/2/3/4）
    big_title: str = ""              # 大题标题（如 "一、朗读单词。（15分）"）
    caption: str = ""                # 大题说明（"请大声朗读你看到的单词..."）
    passage: str = ""                # 阅读题短文材料


# ============================================================
# 公共骨架：单元识别 / 全局编号 / 工具
# ============================================================
_UNIT_RE = re.compile(r'[Uu]\s*(\d{1,2})\b')


def _detect_unit(t: str) -> int:
    """通用单元识别：优先 "Unit 6"，兼容 "五上U6" / "U6" / "六上U10"。
    返回单元号（1-20）或 0（不是单元行）。
    """
    m = re.match(r'Unit\s*(\d+)', t, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = _UNIT_RE.search(t)
    if m and ('U' in t or 'u' in t):
        _cand = int(m.group(1))
        if 1 <= _cand <= 20 and '关键词' not in t[:6]:
            return _cand
    return 0


def _assign_global_idx(questions: list) -> None:
    """全局题号：跨单元/跨阶段/跨大题连续分配（qid 依赖 global_idx 全局唯一）。"""
    for i, q in enumerate(questions, 1):
        q.global_idx = i


def _split_opts(t: str) -> list:
    """拆分选项行：'A. farm B. food C. fish' / 'A. little\t\tB. letter\t\tC. light'
    / 'A.  B.  C.  D.  E.'（匹配题图片占位） → ['A. farm','B. food',...]"""
    if not t:
        return []
    parts = re.split(r'\s+(?=[A-F]\.)', t.strip())   # ★ 支持 A-E（匹配题 5 图占位），最多 A-F
    return [p.strip() for p in parts if p.strip()]


def _is_knowledge_line(content: str) -> bool:
    """判断"知识点："后的数字行是否为知识点内容（而非题干）。
    - 知识点特征：含音标（/ /）、含中英括号注释（(...)（...））、含特殊符号（·、—、~、+）、
      或含 be 动词/助动词等语法结构（am/is/are、do/does、don't、can't）
    - 题干特征：以"选择/判断/填空/朗读/听/排序/匹配/回答/看图"等开头 → 不是知识点
    """
    _s = content.strip()
    if not _s:
        return False
    # 题干特征词开头 → 不是知识点
    if re.match(r'^(选择|判断|填空|朗读|跟读|听|排序|排列|匹配|连线|回答|看图|补全|连词|根据|用|写出|抄写|翻译|What|Where|When|Who|How|Can|Do|Does|Is|Are)', _s, re.IGNORECASE):
        return False
    # 知识点特征：音标 / 括号注释（含中英文方括号）/ 特殊符号
    if re.search(r'/[^/]+/|（[^）]+）|\([^)]+\)|\[[^\]]+\]|[·—~+×＝=]', _s):
        return True
    # 语法结构（am/is/are doing、don't 等）
    if re.search(r"\b(am|is|are|don't|can't|doesn't|do|does)\b", _s, re.IGNORECASE):
        return True
    return False


# ============================================================
# 策略基类
# ============================================================
class DocxStrategy:
    """模块脚本解析策略基类：detect() 判断是否适用，parse() 解析段落流。"""

    name: str = ""

    def detect(self, paragraphs: list) -> bool:
        raise NotImplementedError

    def parse(self, paragraphs: list, unit_hint: int = 0) -> list:
        raise NotImplementedError


# ============================================================
# 策略一：口语训练（2026-08-24）
# ============================================================
# 格式（实测 260513口语训练湘少五上（U6-U10已一测）.docx）：
#   - 朗读单词："1. try  2. scarf  3. pair  4. idea  5. little"（单行 5 小题，tab 分隔）
#   - 朗读句子：逐行 "1. I have a red car."
#   - 看图说句："1. 句型提示：Which one do you want, ...?" + 参考答案：/关键词：
#   - 情景问答："1. 听力材料：What chores does she do in her room?" + 参考答案：/关键词：
#   - 阅读短文：短文段落 + "听力材料：1. Whose coat is too big?" + 参考答案：/关键词：
#   - 元数据块（一级题型/二级题型/难度/关键词/知识点/技能/认知目标...）挂到大题所有小题
#   结构：单元标题（口语训练新湘少版五上U6）→ 4 个大题（一、~ 四、），每大题 5 小题
_ORAL_BIG_HDR = re.compile(r'^[一二三四五六七八九十]+[、\.]')
_ORAL_META_PREFIX = ("一级题型", "二级题型", "难度", "难度系数", "关键词",
                     "知识点", "技能", "认知目标", "适用年级", "编写年份", "主题")


class OralStrategy(DocxStrategy):
    name = "口语训练"

    def detect(self, paragraphs: list) -> bool:
        _head = "".join(t for t in paragraphs if t.strip())[:200]
        return "口语训练" in _head

    def _make_sub(self, unit, big, big_title, n, content):
        """构造口语训练小题：剥离"听力材料：/句型提示："前缀，保留题干正文"""
        stem = content
        for _pre in ("听力材料", "句型提示"):
            if stem.startswith(_pre + "：") or stem.startswith(_pre + ":"):
                stem = stem.split("：", 1)[1].strip() if "：" in stem else stem.split(":", 1)[1].strip()
                break
        return YingYuBaoQuestion(unit=unit, big=big, big_title=big_title, stage_idx=n, stem=stem)

    def parse(self, paragraphs: list, unit_hint: int = 0) -> list:
        unit = unit_hint
        big = 0
        big_title = ""
        big_type = ""          # 单词/句子/问答/阅读
        caption = ""
        passage_lines = []
        meta = {}
        kp_mode = False        # 知识点：后的数字行
        subs = []              # 当前大题小题
        questions = []         # 全部小题

        def _attach_meta():
            for q in subs:
                q.type_1 = meta.get("一级题型", "")
                q.type_2 = meta.get("二级题型", "") or "/"
                q.difficulty = meta.get("难度", "") or meta.get("难度系数", "")
                # ★ 小题自己的"关键词："（如 red, blue）优先，元数据关键词(单元标签)仅兜底
                if not q.keywords:
                    q.keywords = list(meta.get("关键词列表", []))
                q.knowledge_points = list(meta.get("知识点", []))
                q.skill = meta.get("技能", "")
                q.cognitive_target = meta.get("认知目标", "")

        def _flush_big():
            nonlocal subs, meta, caption, passage_lines, kp_mode
            _attach_meta()
            for q in subs:
                q.caption = caption
                if passage_lines:
                    q.passage = "\n".join(passage_lines)
                questions.append(q)
            subs, meta, caption, passage_lines, kp_mode = [], {}, "", [], False

        for raw in paragraphs:
            t = raw.strip()
            if not t:
                continue
            # ---- 单元标题行："口语训练新湘少版五上U6" ----
            if len(t) < 40 and not t.startswith("关键词"):
                _u = _detect_unit(t)
                if _u and ("口语训练" in t or t.startswith("Unit")):
                    unit = _u
                    continue
            # ---- 大题标题："一、朗读单词。（15分）" ----
            if _ORAL_BIG_HDR.match(t):
                _flush_big()
                big += 1
                big_title = t
                big_type = ("单词" if "单词" in t else "句子" if "句子" in t
                            else "阅读" if ("阅读" in t or "短文" in t) else "问答")
                continue
            # ---- 元数据行 ----
            if any(t.startswith(k) for k in _ORAL_META_PREFIX):
                if t.startswith("关键词："):
                    meta["关键词列表"] = [k.strip() for k in
                                          t.replace("关键词：", "").split("#") if k.strip()]
                elif t.startswith("知识点："):
                    meta.setdefault("知识点", [])
                    kp_mode = True
                elif t.startswith("技能："):
                    meta["技能"] = t.replace("技能：", "").strip()
                    kp_mode = False
                elif t.startswith("认知目标："):
                    meta["认知目标"] = t.replace("认知目标：", "").strip()
                elif t.startswith("一级题型：") or t.startswith("二级题型：") \
                        or t.startswith("难度：") or t.startswith("难度系数："):
                    key = t.split("：")[0]
                    meta[key] = t.split("：", 1)[1].strip()
                # 适用年级/编写年份/主题：忽略
                continue
            # ---- 知识点区数字行："1. ar 在单词中的发音 /ɑ:(r)/" ----
            if kp_mode and re.match(r"^\d+[\.、]", t):
                meta.setdefault("知识点", []).append(t)
                continue
            # ---- 大题说明（含"录音/作答/准备时间"等）----
            if big and ("录音" in t or "作答" in t or "准备时间" in t or "播放问题" in t):
                caption = t
                continue
            # ---- 参考答案（挂在最后一个小题，可能多组）----
            if t.startswith("参考答案："):
                _ans = re.sub(r"[（(]\s*隐藏\s*[）)]", "", t.replace("参考答案：", "").strip()).strip()
                if subs:
                    subs[-1].answer = (subs[-1].answer + "\n" + _ans).strip() if subs[-1].answer else _ans
                continue
            # ---- 小题级"关键词：red, blue"（挂在最后一个小题）----
            if t.startswith("关键词：") and subs:
                for _k in t.replace("关键词：", "").split(","):
                    _k = _k.strip()
                    if _k and _k not in subs[-1].keywords:
                        subs[-1].keywords.append(_k)
                continue
            # ---- 独立"听力材料：N. xxx"（阅读题）----
            _lm = re.match(r"^听力材料[:：]\s*(\d+)[\.、]\s*(.*)$", t)
            if _lm:
                subs.append(self._make_sub(unit, big, big_title, int(_lm.group(1)), _lm.group(2).strip()))
                continue
            # ---- 宽容：无编号的"句型提示：/听力材料："行 ----
            #   ★ 脚本笔误场景（实测 U9 第三大题第4小题漏写"4. "前缀）：
            #   知识点区有第4条说明，但小题行只有"句型提示：I feel ..."。
            #   此时按"最后小题+1"补序号，保证 App 第4小题能对上脚本；
            #   脚本自身的漏编号问题由"整卷脚本审查"(script_reviewer) 发现。
            if subs and (t.startswith("句型提示") or t.startswith("听力材料")):
                subs.append(self._make_sub(unit, big, big_title, subs[-1].stage_idx + 1, t))
                continue
            # ---- 小题行："1. try 2. scarf 3. pair..."（朗读单词单行多小题）或 "1. 句型提示：..." ----
            _sm = re.match(r"^(\d+)[\.、]\s*(.*)$", t)
            if _sm:
                num = int(_sm.group(1))
                content = _sm.group(2).strip()
                parts = re.split(r'\s+(?=\d+[\.、]\s)', content) if content else []
                if len(parts) >= 2:   # 单行多小题
                    subs.append(self._make_sub(unit, big, big_title, num, parts[0].strip()))
                    for _p in parts[1:]:
                        _pm = re.match(r"^(\d+)[\.、]\s*(.*)$", _p.strip())
                        if _pm:
                            subs.append(self._make_sub(unit, big, big_title,
                                                       int(_pm.group(1)), _pm.group(2).strip()))
                else:
                    subs.append(self._make_sub(unit, big, big_title, num, content))
                continue
            # ---- 阅读短文段落（未归类的长文本，仅阅读题）----
            if big and big_type == "阅读":
                passage_lines.append(t)
        _flush_big()

        # 全局题号：跨单元/跨大题连续
        _assign_global_idx(questions)
        return questions


# ============================================================
# 策略二：听力专项（默认兜底）
# ============================================================
# 格式（段落模式，无表格）:
#   Unit 6  XXX
#   基础巩固
#   一、听录音，选择你所听到的单词。
#   1. 情景描述...
#   A. xxx    B. xxx    C. xxx
#   录音：xxx
#   答案：B
#   一级题型：听音选择 / 二级题型：听音选择词汇 / 难度：基础 / 关键词：xxx / 知识点：xxx
class ListeningStrategy(DocxStrategy):
    name = "听力专项（兜底）"

    def detect(self, paragraphs: list) -> bool:
        # 兜底策略：口语训练等特化策略未命中时使用
        return True

    def parse(self, paragraphs: list, unit_hint: int = 0) -> list:
        questions = []
        pending = None          # 当前正在累积的题
        current_unit = 0
        current_stage = ""
        _in_knowledge = False   # ★ 是否在"知识点："后的列表区（数字行是知识点，不是新题）
        global_counter = 0      # ★ 全局题号：跨阶段连续递增（脚本每个阶段内部题号从1重数，不能直接用）
        # 大题标题（一、二、...）用正则跳过；题号是全局连续数字

        def _finalize(q):
            nonlocal global_counter
            if q is None:
                return
            q.unit = current_unit
            q.stage = current_stage
            # ★ 修复：global_idx 必须全局唯一（qid 用它，重复会导致不同阶段的同号题互相覆盖，
            #   面板只显示最先写入的十几题）；stage_idx 保留脚本原文的阶段内序号
            global_counter += 1
            q.global_idx = global_counter
            questions.append(q)

        for raw in paragraphs:
            t = raw.strip()
            if not t:
                continue

            # 大题标题：一、听录音... / 二、...
            if re.match(r'^[一二三四五六七八九十]、', t):
                continue

            # Unit 识别（公共骨架）
            _u = _detect_unit(t)
            if _u:
                current_unit = _u
                continue

            # Stage 识别
            if t in ('基础巩固', '综合进阶', '难点突破'):
                current_stage = t
                continue

            # 题号行：1. 题干 / 3. A. little B. letter（题干缺失时数字后直接是选项）
            m = re.match(r'^(\d+)\.\s*(.+)$', t)
            if m and not t.startswith('一级') and not t.startswith('二级'):
                content = m.group(2).strip()
                # ★ 匹配题的匹配项行（"1. Mark (     )  2. Jackson (     )"）：数字后是名字+空括号，
                #   不是新题，跳过（避免把匹配题截断成多个假题）
                if re.search(r'[（(]\s*[）)]', content):
                    continue
                # ★ 知识点行后的数字行：若是"知识点内容"（含音标/括号注释/特殊符号/长句）
                #   才并入知识点列表；若像题干（选择/判断/填空/朗读/听…）则正常当题。
                #   ★ 修复：知识过关脚本"知识点："后紧跟题干行（"1. 选择与对话相符的图片"），
                #     不能误吞——只有明显知识点特征（音标/括号/符号）才算。
                if _in_knowledge and _is_knowledge_line(content):
                    pending.knowledge_points.append(t)
                    continue
                _in_knowledge = False  # 新题 → 退出知识点列表区
                # ★ 口语训练脚本：朗读大题是"1. I have a red car / 2. We play..."连续句子列表，
                #   它们是【一道朗读题的多个句子】。特征：句子行无选项（后面不跟 A./B./C.）、
                #   且下一个非空行是元数据块（一级题型/难度/关键词）。
                #   策略：先创建题（题干=当前句），若发现是列表（无选项+后续元数据块），
                #   在元数据块处理时把累积句子合并成一道题的题干。
                if pending is not None and (pending.stem or pending.answer or pending.options):
                    _finalize(pending)
                num = int(m.group(1))
                pending = YingYuBaoQuestion(
                    unit=current_unit, stage=current_stage,
                    stage_idx=num,   # ★ global_idx 由 _finalize 统一分配（全局唯一）
                )
                if re.match(r'^[A-C]\.', content):
                    # 题干缺失：数字后直接是选项
                    pending.options = _split_opts(content)
                else:
                    pending.stem = content
                continue

            if pending is None:
                pending = YingYuBaoQuestion()

            # 选项行（无数字前缀）
            if re.match(r'^[A-C]\.\s*', t):
                pending.options = _split_opts(t)
                continue

            # 录音行
            if t.startswith('录音：'):
                pending.recording = t.replace('录音：', '').strip()
                continue

            # 答案行
            if t.startswith('答案：'):
                pending.answer = t.replace('答案：', '').strip()
                continue

            # 元数据
            if t.startswith('一级题型：'):
                # ★ 口语训练脚本合并：朗读大题的句子列表（1. 2. 3. 连续数字行、无选项无答案）
                #   是【一道题的多个句子】，解析时被拆成多道假题 → 在此合并还原。
                #   特征：pending 无 options/answer，题型为朗读/跟读/口语/复述/背诵，
                #   且 questions 尾部有 stage_idx 连续的纯句子题（无选项无答案）。
                _t1 = t.replace('一级题型：', '').strip()
                if pending is not None and not pending.options and not pending.answer \
                        and _t1 in ('朗读', '跟读', '口语', '复述', '背诵'):
                    _sentences = [pending.stem] if pending.stem else []
                    _base_unit = pending.unit or current_unit
                    _base_idx = pending.stage_idx
                    # 往前合并：questions 尾部 stage_idx 连续递减、无选项无答案的纯句子题
                    while questions and not questions[-1].options and not questions[-1].answer \
                            and questions[-1].stage_idx == _base_idx - 1:
                        _prev = questions.pop()
                        _sentences.insert(0, _prev.stem or "")
                        _base_idx = _prev.stage_idx
                        if _prev.unit:
                            _base_unit = _prev.unit
                    if len(_sentences) > 1:
                        pending.stem = "\n".join(s for s in _sentences if s).strip()
                        pending.stage_idx = _base_idx
                        pending.unit = _base_unit
                pending.type_1 = t.replace('一级题型：', '').strip()
            elif t.startswith('二级题型：'):
                pending.type_2 = t.replace('二级题型：', '').strip()
            elif t.startswith('难度：'):
                pending.difficulty = t.replace('难度：', '').strip()
            elif t.startswith('关键词：'):
                pending.keywords = [k.strip() for k in t.replace('关键词：', '').split('#') if k.strip()]
            elif t.startswith('知识点：'):
                pending.knowledge_points = [t.replace('知识点：', '').strip()]
                _in_knowledge = True  # ★ 后续数字行是知识点列表（"1. ar发音 2. ..."），不当题
            elif t.startswith('技能：'):
                pending.skill = t.replace('技能：', '').strip()
                _in_knowledge = False  # 元数据结束
            elif t.startswith('认知目标：'):
                pending.cognitive_target = t.replace('认知目标：', '').strip()

        # 最后一道题
        _finalize(pending)
        return questions


# ============================================================
# 策略注册 + 入口
# ============================================================
STRATEGIES: list = [OralStrategy(), ListeningStrategy()]


def parse(filepath: str) -> list:
    """读取 DOCX 脚本，按策略分派解析。

    分派规则：依 STRATEGIES 顺序尝试 detect()，首个命中即用该策略；
    无命中（理论上不会）则用兜底 ListeningStrategy。
    """
    doc = Document(filepath)
    paragraphs = [p.text for p in doc.paragraphs]
    for strat in STRATEGIES:
        try:
            if strat.detect(paragraphs):
                return strat.parse(paragraphs)
        except Exception:
            continue
    return ListeningStrategy().parse(paragraphs)


def parse_oral_paragraphs(paragraphs: list, unit_hint: int = 0) -> list:
    """口语训练策略的段落级入口（兼容无 python-docx 环境的测试/模拟）。"""
    return OralStrategy().parse(paragraphs, unit_hint=unit_hint)


def describe(filepath: str) -> str:
    """预览解析结果"""
    qs = parse(filepath)
    lines = [f"文件: {filepath}", f"总题数: {len(qs)}", ""]

    # 按阶段统计
    stages = {}
    units = {}
    types = {}
    for q in qs:
        s = f"{q.stage}"
        stages[s] = stages.get(s, 0) + 1
        units[f"Unit {q.unit}"] = units.get(f"Unit {q.unit}", 0) + 1
        types[q.type_2] = types.get(q.type_2, 0) + 1

    lines.append("=== 阶段分布 ===")
    for s, n in stages.items():
        lines.append(f"  {s}: {n} 题")

    lines.append("\n=== 单元分布 ===")
    for u, n in sorted(units.items()):
        lines.append(f"  {u}: {n} 题")

    lines.append("\n=== 题型分布 ===")
    for tp, n in sorted(types.items(), key=lambda x: -x[1]):
        lines.append(f"  {tp}: {n} 题")

    lines.append(f"\n=== 前 3 题样例 ===")
    for q in qs[:3]:
        lines.append(f"  Q{q.global_idx:03d} U{q.unit} [{q.stage}] {q.type_2}")
        lines.append(f"    题干: {q.stem[:50]}")
        lines.append(f"    录音: {q.recording[:50]}")
        lines.append(f"    答案: {q.answer}")

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "data/sample_script.docx"
    print(describe(path))
