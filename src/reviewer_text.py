"""
reviewer_text.py — Person A 独占文件
=====================================
检查职责:
  (1) 题干文字是否正确（错别字、语法错误）
  (2) 题目内容文字是否与脚本相符、是否完整、有无知识/逻辑错误

修改规则: 只会被 Person A 修改，Person B 永远不碰这个文件
依赖: reviewer_common.py, question_checker.py, ocr_engine.py
"""

import re
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
                self.script_map[self._get_question_id(q)] = q

    def _get_question_id(self, question) -> int:
        return int(getattr(question, "idx", None) or getattr(question, "global_idx", None) or 0)

    def _get_expected_stem(self, question) -> str:
        return getattr(question, "stem", "") or ""

    def _get_expected_content(self, question) -> str:
        return getattr(question, "content", "") or ""

    def _get_expected_answer(self, question) -> str:
        return getattr(question, "correct_answer", "") or getattr(question, "answer", "") or ""

    def _get_question_type(self, question) -> str:
        return getattr(question, "question_type", "") or getattr(question, "type_2", "") or ""

    # ================================================================
    # (1) 题干文字检查
    # ================================================================

    def check_stem(self, question: Question, screenshot_path: str,
                   ocr_text: str = "") -> CheckItem:
        """检查题干文字是否正确。"""
        item = CheckItem(name="(1)题干文字", screenshot=screenshot_path)

        expected_stem = self._get_expected_stem(question)
        item.expected_text = expected_stem

        actual_stem = ocr_text or self._extract_text(screenshot_path)
        item.actual_text = actual_stem or ""

        if not actual_stem:
            item.error = "无法提取题干文字"
            item.details.append("❌ 无法从截图中提取题干文字")
            return item

        if not expected_stem:
            item.details.append("⚠ 无脚本题干可对比，仅做基本检查")
            if self._has_garbled_text(actual_stem):
                item.details.append("检测到可能的乱码")
            else:
                item.passed = True
                item.details.append("文字显示正常，无脚本数据可对比")
            return item

        sim = text_similarity(expected_stem, actual_stem)
        item.similarity = sim

        if sim >= 0.95:
            item.passed = True
            item.details.append(f"✅ 匹配 (相似度 {sim:.1%})")
        elif sim >= 0.80:
            item.details.append(f"⚠ 部分匹配 (相似度 {sim:.1%})，请人工复核")
            item.details.extend(find_diff_positions(expected_stem, actual_stem)[:5])
        else:
            item.details.append(f"❌ 不匹配 (相似度 {sim:.1%})")
            item.details.extend(find_diff_positions(expected_stem, actual_stem)[:5])

        if self._is_truncated(actual_stem):
            item.details.append("⚠ 题干文字可能被截断")

        return item

    # ================================================================
    # (2) 内容文字检查
    # ================================================================

    def check_content(self, question: Question, screenshot_path: str,
                      all_text: str = "") -> CheckItem:
        """检查内容文字是否与脚本相符、是否完整、是否有知识/逻辑错误。"""
        item = CheckItem(name="(2)内容文字", screenshot=screenshot_path)

        actual_text = all_text or self._extract_all_text(screenshot_path)
        item.actual_text = actual_text or ""

        if not actual_text:
            item.error = "无法提取内容文字"
            item.details.append("❌ 无法从截图中提取内容文字")
            return item

        script_q = self.script_map.get(self._get_question_id(question))
        expected_content = self._get_expected_content(script_q or question)
        item.expected_text = expected_content or ""

        if expected_content:
            sim = text_similarity(expected_content, actual_text)
            item.similarity = sim
            if sim >= 0.90:
                item.details.append(f"✅ 脚本相符 ({sim:.1%})")
            elif sim >= 0.70:
                item.details.append(f"⚠ 部分匹配 ({sim:.1%})")
            else:
                item.details.append(f"❌ 脚本不符 ({sim:.1%})")
        else:
            item.details.append("⚠ 无脚本数据可对比")

        if self._is_truncated(actual_text):
            item.details.append("❌ 文字可能被截断")
        else:
            item.details.append("✅ 文字显示完整")

        if self.llm and script_q:
            result = self.llm.ask(self._knowledge_prompt(question, actual_text, script_q))
            if "发现问题" in result or "错误" in result or "问题" in result:
                item.details.append(f"❌ 知识性检查: {result[:120]}")
            else:
                item.details.append("✅ 知识性检查通过")
        else:
            item.details.append("⚠ 跳过LLM知识性检查")

        if self.llm:
            result = self.llm.ask(self._logic_prompt(question, actual_text))
            if "发现问题" in result or "错误" in result or "矛盾" in result or "问题" in result:
                item.details.append(f"❌ 逻辑检查: {result[:120]}")
            else:
                item.details.append("✅ 逻辑检查通过")
        else:
            item.details.append("⚠ 跳过LLM逻辑检查")

        has_fail = any(detail.startswith("❌") for detail in item.details)
        item.passed = not has_fail
        return item

    # ================================================================
    # 内部方法（Person A 专属区域，Person B 不要动）
    # ================================================================

    def _extract_text(self, screenshot_path: str) -> str:
        """从截图中提取题干文字。优先 OCR，失败则回退到 LLM 视觉分析。"""
        try:
            from src.ocr_engine import OCREngine
            ocr = OCREngine()
            blocks = ocr.extract(screenshot_path)
            upper_blocks = [b for b in blocks if getattr(b, "y", 0) < 500]
            text = " ".join(getattr(b, "text", "") for b in upper_blocks if getattr(b, "text", ""))
            if text:
                return text
        except Exception:
            pass

        if self.llm:
            try:
                prompt = "请从图片中只提取题干文字，不要解释。"
                text = self.llm.ask(prompt, image_path=screenshot_path)
                return self._clean_extracted_text(text)
            except Exception:
                return ""
        return ""

    def _extract_all_text(self, screenshot_path: str) -> str:
        """提取截图中的所有文字。优先 OCR，失败则回退到 LLM 视觉分析。"""
        try:
            from src.ocr_engine import OCREngine
            ocr = OCREngine()
            blocks = ocr.extract(screenshot_path)
            text = " ".join(getattr(b, "text", "") for b in blocks if getattr(b, "text", ""))
            if text:
                return text
        except Exception:
            pass

        if self.llm:
            try:
                prompt = "请从图片中提取所有可见文字，只输出纯文字内容。"
                text = self.llm.ask(prompt, image_path=screenshot_path)
                return self._clean_extracted_text(text)
            except Exception:
                return ""
        return ""

    def _clean_extracted_text(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text.replace("\n", " ").strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned

    def _has_garbled_text(self, text: str) -> bool:
        """检测是否存在乱码。"""
        if not text:
            return False
        abnormal = sum(1 for c in text if ord(c) > 0x4e00 and not ('\u4e00' <= c <= '\u9fff'))
        return abnormal > len(text) * 0.3

    def _is_truncated(self, text: str) -> bool:
        """检测文字是否被截断。"""
        if not text:
            return False
        stripped = text.rstrip()
        if not stripped:
            return False

        if stripped.endswith(("...", "…", "，", "、", ",", "and", "or")):
            return True

        if stripped.endswith(("。", "！", "？", "!", "?", ";", ":", "）", ")")):
            return False

        return False

    def _knowledge_prompt(self, q: Question, actual: str, script_q: Question) -> str:
        return f"""你是英语教学内容的质检专家。请检查以下题目是否存在知识性错误。

题目: {self._get_expected_stem(q)}
内容: {actual}
正确答案: {self._get_expected_answer(script_q)}
知识点: {getattr(script_q, 'knowledge_points', [])}

请判断：
1. 单词拼写是否正确？
2. 语法使用是否正确？
3. 知识点是否符合教学大纲？
4. 正确答案是否确实正确？

只需回答"通过"或"发现问题：[具体描述]"。"""

    def _logic_prompt(self, q: Question, actual: str) -> str:
        return f"""请检查这道英语题是否存在逻辑性错误。

题目: {self._get_expected_stem(q)}
内容: {actual}
题型: {self._get_question_type(q)}

判断标准：
1. 题目条件是否充分（不会让答题者无从下手）
2. 选项之间是否有自相矛盾
3. 题目设定是否合理

只需回答"通过"或"发现问题：[具体描述]"。"""
