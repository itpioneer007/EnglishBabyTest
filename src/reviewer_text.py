"""
reviewer_text.py — Person A 独占文件
=====================================
检查职责:
  (1) 题干文字是否正确（错别字、语法错误）
  (2) 题目内容文字是否与脚本相符、是否完整、有无知识/逻辑错误

修改规则: 只会被 Person A 修改，Person B 永远不碰这个文件
依赖: reviewer_common.py, question_checker.py, ocr_engine.py
"""

from pathlib import Path
from typing import Optional
from src.reviewer_common import CheckItem, Question, LLMClient, text_similarity, find_diff_positions


class TextReviewer:
    """
    Person A 的文字审查器
    
    用法:
        reviewer = TextReviewer(llm_client, script_questions)
        stem_result = reviewer.check_stem(question, screenshot_path)
        content_result = reviewer.check_content(question, screenshot_path)
    """

    def __init__(self, llm: LLMClient, script_questions: list[Question] = None):
        """
        Args:
            llm: LLM 客户端（用于知识/逻辑错误检测）
            script_questions: 公司提供的脚本题目列表（预期数据）
        """
        self.llm = llm
        self.script_map = {}
        if script_questions:
            for q in script_questions:
                self.script_map[q.idx] = q

    # ================================================================
    # (1) 题干文字检查
    # ================================================================

    def check_stem(self, question: Question, screenshot_path: str,
                   ocr_text: str = "") -> CheckItem:
        """
        检查题干文字是否正确

        Args:
            question: 题目数据（包含脚本中的题干）
            screenshot_path: 截图文件路径
            ocr_text: 如果已经 OCR 过了可以直接传入，否则用 UI dump 提取

        Returns:
            CheckItem: 检查结果
        """
        item = CheckItem(name="(1)题干文字", screenshot=screenshot_path)

        # 提取实际题干文字
        actual_stem = ocr_text or self._extract_text(screenshot_path)
        item.actual_text = actual_stem or ""
        item.expected_text = question.stem or ""

        if not actual_stem:
            item.error = "无法提取题干文字"
            return item

        if not question.stem:
            item.details.append("⚠ 无脚本数据可对比，仅做基本检查")
            # 即使没脚本，也可以检查是否有乱码
            if self._has_garbled_text(actual_stem):
                item.details.append("检测到可能的乱码")
            else:
                item.passed = True
                item.details.append("文字显示正常，无脚本数据可对比")
            return item

        # 比对
        sim = text_similarity(question.stem, actual_stem)
        item.similarity = sim

        if sim >= 0.95:
            item.passed = True
            item.details.append(f"✅ 匹配 (相似度 {sim:.1%})")
        elif sim >= 0.80:
            item.details.append(f"⚠ 部分匹配 (相似度 {sim:.1%})，请人工复核")
            item.details.extend(find_diff_positions(question.stem, actual_stem)[:5])
        else:
            item.details.append(f"❌ 不匹配 (相似度 {sim:.1%})")
            item.details.extend(find_diff_positions(question.stem, actual_stem)[:5])

        return item

    # ================================================================
    # (2) 内容文字检查
    # ================================================================

    def check_content(self, question: Question, screenshot_path: str,
                      all_text: str = "") -> CheckItem:
        """
        四项子检查：
          a. 脚本相符 — 选项文字与预期一致
          b. 显示完整 — 无截断/遮挡
          c. 知识性错误 — LLM 判断知识点是否正确
          d. 逻辑性错误 — LLM 判断是否有逻辑矛盾

        Args:
            question: 题目数据
            screenshot_path: 截图路径
            all_text: 已提取的全部文字（可选）

        Returns:
            CheckItem
        """
        item = CheckItem(name="(2)内容文字", screenshot=screenshot_path)

        actual_text = all_text or self._extract_all_text(screenshot_path)
        item.actual_text = actual_text or ""

        if not actual_text:
            item.error = "无法提取内容文字"
            return item

        # a. 脚本相符
        script_q = self.script_map.get(question.idx)
        if script_q and script_q.content:
            expected_content = script_q.content
            item.expected_text = expected_content
            sim = text_similarity(expected_content, actual_text)
            item.similarity = sim
            if sim >= 0.90:
                item.details.append(f"✅ 脚本相符 ({sim:.1%})")
            elif sim >= 0.70:
                item.details.append(f"⚠ 部分匹配 ({sim:.1%})")
        else:
            item.details.append("⚠ 无脚本数据可对比")

        # b. 显示完整
        if self._is_truncated(actual_text):
            item.details.append("❌ 文字可能被截断")
        else:
            item.details.append("✅ 文字显示完整")

        # c. 知识性错误 (LLM)
        if self.llm and script_q:
            result = self.llm.ask(
                self._knowledge_prompt(question, actual_text, script_q)
            )
            if "错误" in result or "问题" in result:
                item.details.append(f"⚠ 知识性检查: {result[:100]}")
            else:
                item.details.append("✅ 知识性检查通过")
        else:
            item.details.append("⚠ 跳过LLM知识性检查")

        # d. 逻辑性错误 (LLM)
        if self.llm:
            result = self.llm.ask(
                self._logic_prompt(question, actual_text)
            )
            if "错误" in result or "矛盾" in result or "问题" in result:
                item.details.append(f"⚠ 逻辑检查: {result[:100]}")
            else:
                item.details.append("✅ 逻辑检查通过")
        else:
            item.details.append("⚠ 跳过LLM逻辑检查")

        # 汇总
        has_fail = any("❌" in d for d in item.details)
        item.passed = not has_fail

        return item

    # ================================================================
    # 内部方法（Person A 专属区域，Person B 不要动）
    # ================================================================

    def _extract_text(self, screenshot_path: str) -> str:
        """从截图中提取题干文字"""
        try:
            from src.ocr_engine import OCREngine
            ocr = OCREngine()
            blocks = ocr.extract(screenshot_path)
            # 题干通常在截图上部
            upper_blocks = [b for b in blocks if b.y < 500]
            return " ".join(b.text for b in upper_blocks)
        except Exception:
            return ""

    def _extract_all_text(self, screenshot_path: str) -> str:
        """提取截图中的所有文字"""
        try:
            from src.ocr_engine import OCREngine
            ocr = OCREngine()
            blocks = ocr.extract(screenshot_path)
            return " ".join(b.text for b in blocks)
        except Exception:
            return ""

    def _has_garbled_text(self, text: str) -> bool:
        """检测是否存在乱码"""
        if not text:
            return False
        # 乱码特征：含有大量非标准字符
        abnormal = sum(1 for c in text if ord(c) > 0x4e00 and not ('\u4e00' <= c <= '\u9fff'))
        return abnormal > len(text) * 0.3

    def _is_truncated(self, text: str) -> bool:
        """检测文字是否被截断"""
        if not text:
            return False
        # 截断特征：末尾有半句话
        return text.rstrip().endswith(("...", "…", "，", "and", "or"))

    def _knowledge_prompt(self, q: Question, actual: str, script_q: Question) -> str:
        return f"""你是英语教学内容的质检专家。请检查以下题目是否存在知识性错误。

题目: {q.stem}
内容: {actual}
正确答案: {script_q.correct_answer}
知识点: {script_q.knowledge_points}

请判断：
1. 单词拼写是否正确？
2. 语法使用是否正确？
3. 知识点是否符合教学大纲？
4. 正确答案是否确实正确？

只需回答"通过"或"发现问题：[具体描述]"。"""

    def _logic_prompt(self, q: Question, actual: str) -> str:
        return f"""请检查这道英语题是否存在逻辑性错误。

题目: {q.stem}
内容: {actual}
题型: {q.question_type}

判断标准：
1. 题目条件是否充分（不会让答题者无从下手）
2. 选项之间是否有自相矛盾
3. 题目设定是否合理

只需回答"通过"或"发现问题：[具体描述]"。"""
