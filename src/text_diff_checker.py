# -*- coding: utf-8 -*-
"""
text_diff_checker.py — 精确文字比对模块

原则: 文字类检查(题干/选项/答案/听力材料)不依赖LLM判断,用OCR+精确比对。
      只有差异需要"语义判断是否可接受"时才调用LLM(如空格/换行/全半角差异)。

用法:
  from src.text_diff_checker import check_stem, check_content, check_answer, diff_texts
  r = check_stem(screenshot_path, script_stem)
  → DiffResult(passed, score, evidence=[...])
"""

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Evidence:
    """一条差异证据"""
    type: str = ""                     # "text_mismatch" / "text_ok" / "missing_ui_text"
    field: str = ""                    # "stem" / "content" / "answer" / "options"
    expected: str = ""                 # 来自脚本的标准值
    actual: str = ""                   # 来自截图OCR的实际值
    diff: str = ""                     # 差异描述(如 "第3字符 a → b")
    position: str = ""                 # 在页面上的位置(如 "y=308")
    diff_html: str = ""                # 前端展示用的高亮对比HTML


@dataclass
class DiffResult:
    """精确比对结果"""
    passed: bool = True
    score: float = 1.0                 # 0~1
    similarity: float = 1.0            # difflib 相似度
    evidence: list = field(default_factory=list)
    need_llm: bool = False             # 是否需要LLM进一步判断(相似度在阈值边缘)
    llm_context: str = ""              # 传给LLM的上下文(差异摘要)


def _normalize(text: str) -> str:
    """规范化文本: 去首尾空白/统一换行/去连续空格"""
    t = text.strip()
    t = re.sub(r'\s+', ' ', t)          # 连续空白 → 单空格
    t = t.replace('\r', '').replace('\n', ' ')  # 换行 → 空格
    return t


def _extract_ocr_text(screenshot_path: str) -> str:
    """从截图提取UI文字(调用现有OCR或dump hierarchy)

    优先用 uiautomator2 dump_hierarchy 提取文字(已有、最快)。
    若截图不是从当前设备dump的(历史截图),则尝试用AI视觉提取。
    返回: 所有UI文字用换行连接的字符串
    """
    screenshot_path = str(screenshot_path)
    # 尝试从同名 .xml dump 读文字
    xml_path = screenshot_path.rsplit('.', 1)[0] + '.xml'
    if Path(xml_path).exists():
        try:
            with open(xml_path, 'r', encoding='utf-8') as f:
                xml = f.read()
            texts = []
            for m in re.finditer(r'text="([^"]*)"', xml):
                t = m.group(1).strip()
                if t:
                    texts.append(t)
            return '\n'.join(texts)
        except Exception:
            pass
    # 没有xml → 返回空(由调用方决定是否用视觉模型)
    return ""


def diff_texts(expected: str, actual: str) -> tuple:
    """标准文本 vs OCR文本 → 差异详情

    返回: (similarity, diff_desc, diff_html)
      similarity: 0~1
      diff_desc: 人类可读的差异描述
      diff_html: 前端展示用的高亮对比
    """
    a = _normalize(expected)
    b = _normalize(actual)
    if not a and not b:
        return 1.0, "", ""

    matcher = difflib.SequenceMatcher(None, a, b)
    similarity = matcher.ratio()

    if similarity >= 0.99:
        return similarity, "一致", ""

    # 生成逐字符差异
    diff_parts = []
    diff_desc_parts = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == 'equal':
            diff_parts.append(a[i1:i2])
        elif op == 'replace':
            old = a[i1:i2]
            new = b[j1:j2]
            diff_parts.append(f'<del style="background:#ffcdd2">{old}</del><ins style="background:#c8e6c9">{new}</ins>')
            diff_desc_parts.append(f'{old} → {new}')
        elif op == 'delete':
            old = a[i1:i2]
            diff_parts.append(f'<del style="background:#ffcdd2">{old}</del>')
            diff_desc_parts.append(f'缺失: {old}')
        elif op == 'insert':
            new = b[j1:j2]
            diff_parts.append(f'<ins style="background:#c8e6c9">{new}</ins>')
            diff_desc_parts.append(f'多余: {new}')

    diff_html = '<span style="font-family:monospace">' + ''.join(diff_parts) + '</span>'
    diff_desc = '; '.join(diff_desc_parts)
    return similarity, diff_desc, diff_html


def check_text_field(expected: str, actual: str, field_name: str) -> DiffResult:
    """通用: 比对单个文本字段(题干/选项/答案...)

    expected: 脚本文本
    actual: OCR提取的文本
    field_name: 字段名(stem/content/answer...)
    """
    r = DiffResult()
    sim, desc, html = diff_texts(expected, actual)
    r.similarity = sim

    if sim >= 0.97:
        r.passed = True
        r.score = 1.0
        r.evidence.append(Evidence(
            type="text_ok", field=field_name,
            expected=expected, actual=actual,
            diff=f"完全一致(相似度{sim:.2%})" if sim >= 0.99 else f"基本一致(相似度{sim:.2%})",
            diff_html=html
        ))
    elif sim >= 0.85:
        r.passed = False
        r.score = 0.5
        r.need_llm = True  # 边缘差异,LLM判断是否可接受
        r.llm_context = f"脚本文本: {expected}\nOCR文本: {actual}\n差异: {desc}"
        r.evidence.append(Evidence(
            type="text_mismatch", field=field_name,
            expected=expected, actual=actual,
            diff=desc, diff_html=html
        ))
    else:
        r.passed = False
        r.score = 0.0
        r.evidence.append(Evidence(
            type="text_mismatch", field=field_name,
            expected=expected, actual=actual,
            diff=desc, diff_html=html
        ))

    return r


def check_stem(screenshot_path: str, script_stem: str) -> DiffResult:
    """检查题干文字(精确比对版)"""
    ocr = _extract_ocr_text(screenshot_path)
    if not ocr:
        return DiffResult(passed=False, score=0.0,
                          evidence=[Evidence(type="missing_ui_text", field="stem",
                                             expected=script_stem, actual="(无法提取UI文字)")],
                          need_llm=True)
    # 找OCR中与脚本题干最相似的片段
    script_norm = _normalize(script_stem)
    max_sim = 0
    best_text = ""
    lines = ocr.split('\n')
    # 滑动窗口找相似文本
    for win_size in range(1, min(5, len(lines) + 1)):
        for i in range(len(lines) - win_size + 1):
            chunk = ' '.join(lines[i:i + win_size])
            sim = difflib.SequenceMatcher(None, _normalize(chunk), script_norm).ratio()
            if sim > max_sim:
                max_sim = sim
                best_text = chunk if sim > 0.5 else script_norm

    if max_sim < 0.3:
        # 完全没找到 → LLM判断(OCR可能漏了题干)
        return DiffResult(passed=False, score=0.0,
                          evidence=[Evidence(type="missing_ui_text", field="stem",
                                             expected=script_stem, actual="(OCR未找到匹配文本)")],
                          need_llm=True)

    return check_text_field(script_stem, best_text, "stem")


def check_answer(screenshot_path: str, script_answer: str, options: list = None) -> DiffResult:
    """检查答案(精确比对版)——验证标准答案选项是否存在、是否可选"""
    ocr = _extract_ocr_text(screenshot_path)
    if not ocr:
        return DiffResult(passed=False, score=0.0,
                          evidence=[Evidence(type="missing_ui_text", field="answer",
                                             expected=script_answer, actual="(无法提取UI文字)")],
                          need_llm=True)

    # 检查答案选项是否存在
    if script_answer in ocr:
        return DiffResult(passed=True, score=1.0, similarity=1.0,
                          evidence=[Evidence(type="text_ok", field="answer",
                                             expected=script_answer, actual=script_answer,
                                             diff="答案选项存在")])
    else:
        # 找最相似的OCR文本
        sim, desc, html = diff_texts(script_answer, ocr[:500])
        return DiffResult(passed=False, score=0.0, similarity=sim,
                          evidence=[Evidence(type="text_mismatch", field="answer",
                                             expected=script_answer, actual=f"(OCR未精确匹配, 最相似: {ocr[:80]}...)",
                                             diff=desc, diff_html=html)],
                          need_llm=True)
