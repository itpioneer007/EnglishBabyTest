"""
parse_yingyubao_docx.py — 英语宝听力专项 DOCX 专用解析器

解析格式（段落模式，无表格）:
  Unit 6  XXX
  基础巩固
  一、听录音，选择你所听到的单词。
  1. 情景描述...
  A. xxx    B. xxx    C. xxx
  录音：xxx
  答案：B
  一级题型：听音选择
  二级题型：听音选择词汇
  难度：基础
  关键词：听力专项#新湘鲁六上U6#word
  知识点：xxx
"""

from dataclasses import dataclass, field
from docx import Document
import re


@dataclass
class YingYuBaoQuestion:
    """英语宝题目完整数据结构"""
    global_idx: int = 0              # 全局题号 (1-160)
    unit: int = 0                    # 单元 (6/7/8/9)
    stage: str = ""                  # 阶段: 基础巩固/综合进阶/难点突破
    stage_idx: int = 0               # 阶段内题号
    stem: str = ""                   # 题干
    options: list = field(default_factory=list)  # 选项 [A.xxx, B.xxx, C.xxx]
    recording: str = ""              # 录音原文
    answer: str = ""                 # 正确答案
    type_1: str = ""                 # 一级题型
    type_2: str = ""                 # 二级题型
    difficulty: str = ""             # 难度
    keywords: list = field(default_factory=list)
    knowledge_points: list = field(default_factory=list)
    skill: str = ""
    cognitive_target: str = ""


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


def parse(filepath: str) -> list[YingYuBaoQuestion]:
    """解析英语宝听力专项 DOCX（段落模式）

    结构（每道题）:
      1. 题干文字...
      A. xxx B. xxx C. xxx
      录音：xxx
      答案：B
      一级题型：xxx / 二级题型：xxx / 难度：xxx / 关键词：xxx / 知识点：xxx ...
    ★ 支持题干缺失（数字后直接跟选项）：'3. A. little B. letter C. light'
    ★ 支持选项单空格/多空格/制表符分隔
    """
    doc = Document(filepath)
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

    for p in doc.paragraphs:
        t = p.text.strip()
        if not t:
            continue

        # 大题标题：一、听录音... / 二、...
        if re.match(r'^[一二三四五六七八九十]、', t):
            continue

        # Unit 识别
        m = re.match(r'Unit\s*(\d+)', t, re.IGNORECASE)
        if m:
            current_unit = int(m.group(1))
            continue
        # ★ 兼容口语训练脚本标题格式："口语训练新湘少版五上U7" / "五上U10" / "U6"
        #   （脚本标题常写"五上U7"，无 "Unit " 前缀 → 旧正则识别不到 → 全部题 unit=0
        #   → 按单元过滤失效 → 脚本审查结果为空，用户实测"脚本审查没生效"）
        m = re.search(r'(?:上|下|册|书)?[Uu]\s*(\d{1,2})\b', t)
        if m and ('U' in t or 'u' in t):
            _cand = int(m.group(1))
            if 1 <= _cand <= 20 and '关键词' not in t[:6]:
                current_unit = _cand
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
