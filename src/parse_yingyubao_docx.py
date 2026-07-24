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


def parse(filepath: str) -> list[YingYuBaoQuestion]:
    """解析英语宝听力专项 DOCX"""
    doc = Document(filepath)
    questions = []
    current = YingYuBaoQuestion()
    current_unit = 0
    current_stage = ""
    current_stage_idx = 0
    global_idx = 0
    in_options = False

    for p in doc.paragraphs:
        t = p.text.strip()
        if not t:
            continue

        # Unit 识别
        m = re.match(r'Unit\s*(\d+)', t, re.IGNORECASE)
        if m:
            current_unit = int(m.group(1))

        # Stage 识别
        if t in ['基础巩固', '综合进阶', '难点突破']:
            current_stage = t

        # 录音行 → 保存当前题
        if t.startswith('录音：'):
            rec = t.replace('录音：', '').strip()
            if current.answer:
                # 上一题数据完整 → 入库
                current.unit = current_unit
                current.stage = current_stage
                current.global_idx = global_idx
                questions.append(current)
                # 新建下一题
                current_stage_idx += 1
                global_idx += 1
                current = YingYuBaoQuestion()
                current.stage_idx = current_stage_idx
            else:
                global_idx += 1
                current_stage_idx += 1
                current.global_idx = global_idx
                current.stage_idx = current_stage_idx
            current.recording = rec

        # 答案行
        if t.startswith('答案：'):
            current.answer = t.replace('答案：', '').strip()

        # 题型
        if t.startswith('一级题型：'):
            current.type_1 = t.replace('一级题型：', '').strip()
        if t.startswith('二级题型：'):
            current.type_2 = t.replace('二级题型：', '').strip()

        # 难度
        if t.startswith('难度：'):
            current.difficulty = t.replace('难度：', '').strip()

        # 关键词 → 提取单元信息
        if t.startswith('关键词：'):
            kw = t.replace('关键词：', '').strip()
            current.keywords = [k.strip() for k in kw.split('#') if k.strip()]

        # 知识点
        if t.startswith('知识点：'):
            current.knowledge_points = [t.replace('知识点：', '').strip()]

        # 题干 (以数字开头且不是编号)
        m = re.match(r'^(\d+)\.\s*(.+)', t)
        if m and not t.startswith('一级') and not t.startswith('二级'):
            # 确保前一道题已入库
            if current.answer and current.global_idx == 0:
                # 第一题特殊处理 - 等录音行
                pass
            num = int(m.group(1))
            if 1 <= num <= 30 and current.answer == '':
                # 新题开始
                if current.stem:
                    # 保存上一题(即使没有录音行)
                    current.unit = current_unit
                    current.stage = current_stage
                    questions.append(current)
                    global_idx += 1
                    current_stage_idx += 1
                    current = YingYuBaoQuestion()
                current.stem = m.group(2)
                current.stage_idx = current_stage_idx + 1
                current.global_idx = global_idx + 1

        # 选项行 A. xxx  B. xxx
        if re.match(r'^[A-C]\.\s+', t):
            opts = re.split(r'\s{2,}', t)
            current.options = [o.strip() for o in opts if o.strip()]

    # 最后一道题
    if current.answer:
        current.unit = current_unit
        current.stage = current_stage
        current.global_idx = global_idx
        questions.append(current)

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
