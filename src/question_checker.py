"""
英语宝模块检测 - 题目内容校验引擎

实现两种核心校验：
  1. 题干文字校验 (check_stem)
     - OCR 提取题干文字 → 与预期脚本逐字对比 → 报告差异
  2. 题目内容文字校验 (check_content)
     - 四维检查：脚本相符、显示完整、知识性错误、逻辑性错误

使用方式:
    checker = QuestionChecker(adb_controller, expected_data)
    
    # 先截图
    screenshot = adb.screenshot("question_001.png")
    
    # 校验题干
    stem_result = checker.check_stem(screenshot)

    # 校验内容
    content_result = checker.check_content(screenshot)
"""

import os
import re
import json
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from ocr_engine import OCREngine, OCRResult, TextBlock, extract_text_from_ui_elements


# ============================================================
# 数据类：校验结果
# ============================================================

@dataclass
class DiffItem:
    """单个差异项"""
    position: int = 0               # 差异位置
    expected: str = ""              # 预期文字
    actual: str = ""                # 实际文字
    diff_type: str = "replace"      # replace | insert | delete


@dataclass
class StemResult:
    """题干校验结果"""
    passed: bool = False
    expected: str = ""              # 预期题干文字
    actual: str = ""                # 实际 OCR 文字
    similarity: float = 0.0         # 相似度 0~1
    diffs: list[DiffItem] = field(default_factory=list)
    screenshot: str = ""            # 截图路径
    error: str = ""                 # 异常信息


@dataclass
class ContentResult:
    """题目内容校验结果"""
    # 四个检查维度
    script_match: bool = False          # 是否与脚本相符
    display_complete: bool = False      # 是否显示完整
    knowledge_errors: list[str] = field(default_factory=list)   # 知识性错误
    logic_errors: list[str] = field(default_factory=list)       # 逻辑性错误

    # 文本对比详情
    expected: str = ""
    actual: str = ""
    similarity: float = 0.0
    diffs: list[DiffItem] = field(default_factory=list)

    # 截断检测详情
    trunction_evidence: list[str] = field(default_factory=list)

    # 元信息
    screenshot: str = ""
    error: str = ""

    @property
    def all_passed(self) -> bool:
        """全部检查通过"""
        return (
            self.script_match
            and self.display_complete
            and len(self.knowledge_errors) == 0
            and len(self.logic_errors) == 0
        )

    def summary(self) -> str:
        """生成简要摘要"""
        lines = []
        icon = "✅" if self.script_match else "❌"
        lines.append(f"{icon} 是否与脚本相符")
        icon = "✅" if self.display_complete else "❌"
        lines.append(f"{icon} 是否显示完整")
        icon = "✅" if len(self.knowledge_errors) == 0 else "❌"
        lines.append(f"{icon} 知识性错误({len(self.knowledge_errors)}个)")
        icon = "✅" if len(self.logic_errors) == 0 else "❌"
        lines.append(f"{icon} 逻辑性错误({len(self.logic_errors)}个)")
        return "\n".join(lines)


# ============================================================
# 题目校验引擎
# ============================================================

class QuestionChecker:
    """题目内容校验引擎"""

    def __init__(self, adb_controller=None, expected_data: dict = None,
                 ocr_backend: str = "auto", llm_client=None):
        """
        Args:
            adb_controller: ADBController 实例（用于 uiautomator dump 模式）
            expected_data: 题目预期数据字典（符合脚本数据格式）
            ocr_backend: "auto" | "paddleocr" | "easyocr" | "uiautomator"
            llm_client: LLM 客户端（用于知识性/逻辑性校验，可选）
        """
        self.adb = adb_controller
        self.expected = expected_data or {}
        self.llm = llm_client

        # 初始化 OCR 引擎（延迟加载，不在此处初始化模型）
        self.ocr = OCREngine(backend=ocr_backend)

        # 校验统计
        self.stats = {
            "total_questions": 0,
            "stem_passed": 0,
            "content_passed": 0,
            "knowledge_errors_found": 0,
            "logic_errors_found": 0,
        }

    # ============================================================
    # 功能1: 题干文字校验
    # ============================================================

    def check_stem(self, screenshot_path: str) -> StemResult:
        """
        校验题干文字是否正确。

        流程：
          1. OCR 提取截图中的全部文字
          2. 定位题干区域（屏幕上半部分）
          3. 与预期 stem_text 做模糊匹配
          4. 不匹配时，逐字对比找出差异

        Args:
            screenshot_path: 截图文件路径

        Returns:
            StemResult
        """
        self.stats["total_questions"] += 1

        expected_stem = self.expected.get("stem_text", "")
        if not expected_stem:
            return StemResult(error="缺少预期数据: stem_text 为空")

        # Step 1: OCR 提取文字
        ocr_result = self._do_ocr(screenshot_path)
        if ocr_result.error:
            return StemResult(error=f"OCR 失败: {ocr_result.error}",
                              expected=expected_stem, screenshot=screenshot_path)

        # Step 2: 定位题干区域并提取文字
        stem_text, _ = OCREngine.split_stem_and_content(
            ocr_result.blocks, stem_bottom_ratio=0.45
        )

        if not stem_text.strip():
            # 回退：如果无法自动分割，就取全部 OCR 文字
            stem_text = ocr_result.full_text

        # Step 3: 模糊匹配
        similarity = self._similarity(expected_stem, stem_text)

        if similarity >= 0.95:
            self.stats["stem_passed"] += 1
            return StemResult(
                passed=True,
                expected=expected_stem,
                actual=stem_text,
                similarity=similarity,
                screenshot=screenshot_path,
            )

        # Step 4: 逐字对比找差异
        diffs = self._diff_text(expected_stem, stem_text)

        return StemResult(
            passed=False,
            expected=expected_stem,
            actual=stem_text,
            similarity=similarity,
            diffs=diffs,
            screenshot=screenshot_path,
        )

    # ============================================================
    # 功能2: 题目内容文字校验（四维检查）
    # ============================================================

    def check_content(self, screenshot_path: str) -> ContentResult:
        """
        校验题目内容文字（四维检查）。

        检查维度:
          1. 是否与脚本相符 → OCR 文字 vs 预期 content_text
          2. 是否显示完整 → 截断检测
          3. 知识性错误 → LLM 判断
          4. 逻辑性错误 → LLM 判断

        Args:
            screenshot_path: 截图文件路径

        Returns:
            ContentResult
        """
        expected_content = self.expected.get("content_text", "")
        result = ContentResult(expected=expected_content, screenshot=screenshot_path)

        if not expected_content:
            return ContentResult(error="缺少预期数据: content_text 为空")

        # Step 1: OCR 提取文字
        ocr_result = self._do_ocr(screenshot_path)
        if ocr_result.error:
            return ContentResult(error=f"OCR 失败: {ocr_result.error}",
                                 expected=expected_content, screenshot=screenshot_path)

        # Step 2: 定位内容区域
        _, content_text = OCREngine.split_stem_and_content(
            ocr_result.blocks, stem_bottom_ratio=0.45
        )

        if not content_text.strip():
            content_text = ocr_result.full_text

        # ---- 检查1：是否与脚本相符 ----
        similarity = self._similarity(expected_content, content_text)
        result.similarity = similarity
        result.actual = content_text

        if similarity >= 0.95:
            result.script_match = True
        else:
            result.script_match = False
            result.diffs = self._diff_text(expected_content, content_text)

        # ---- 检查2：是否显示完整（截断检测） ----
        result.display_complete, result.trunction_evidence = \
            self._check_truncation(ocr_result.blocks)

        # ---- 检查3 & 4：知识性与逻辑性错误（LLM 校验） ----
        if self.llm:
            result.knowledge_errors = self._llm_check_knowledge(content_text)
            result.logic_errors = self._llm_check_logic(content_text)

        # 更新统计
        if result.all_passed:
            self.stats["content_passed"] += 1
        self.stats["knowledge_errors_found"] += len(result.knowledge_errors)
        self.stats["logic_errors_found"] += len(result.logic_errors)

        # 存储 LLM 的校验详情到截图同目录的 JSON 文件中
        self._save_result(result, screenshot_path)

        return result

    # ============================================================
    # 一站式校验（同时校验题干和内容）
    # ============================================================

    def check_all(self, screenshot_path: str) -> dict:
        """
        一站式校验：同时执行题干校验和内容校验。

        Returns:
            {
                "question_id": "...",
                "stem": StemResult,
                "content": ContentResult,
                "screenshot": "...",
                "timestamp": "..."
            }
        """
        stem = self.check_stem(screenshot_path)
        content = self.check_content(screenshot_path)

        return {
            "question_id": self.expected.get("question_id", ""),
            "module": self.expected.get("module", ""),
            "grade": self.expected.get("grade", ""),
            "unit": self.expected.get("unit", ""),
            "stem": {
                "passed": stem.passed,
                "expected": stem.expected,
                "actual": stem.actual,
                "similarity": stem.similarity,
                "diffs": [
                    {"pos": d.position, "expected": d.expected, "actual": d.actual,
                     "type": d.diff_type}
                    for d in stem.diffs
                ],
                "error": stem.error,
            },
            "content": {
                "script_match": content.script_match,
                "display_complete": content.display_complete,
                "knowledge_errors": content.knowledge_errors,
                "logic_errors": content.logic_errors,
                "similarity": content.similarity,
                "diffs": [
                    {"pos": d.position, "expected": d.expected, "actual": d.actual,
                     "type": d.diff_type}
                    for d in content.diffs
                ],
                "trunction_evidence": content.trunction_evidence,
                "error": content.error,
            },
            "screenshot": screenshot_path,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ============================================================
    # 内部方法：OCR
    # ============================================================

    def _do_ocr(self, screenshot_path: str) -> OCRResult:
        """执行 OCR，支持 uiautomator 回退"""
        # 先尝试 uiautomator dump（更快更准）
        if self.adb and self.ocr._active_backend in (None, "uiautomator"):
            try:
                elements = self.adb.dump_ui()
                if elements:
                    return self.ocr.extract_from_elements(elements)
            except Exception:
                pass

        # 回退到图像 OCR
        return self.ocr.extract(screenshot_path)

    # ============================================================
    # 内部方法：文字对比
    # ============================================================

    @staticmethod
    def _normalize(text: str) -> str:
        """统一文字格式，忽略渲染差异"""
        if not text:
            return ""
        # 统一换行
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        text = text.replace('\n', ' ')
        # 合并多余空格
        text = re.sub(r'\s+', ' ', text)
        # 统一中文标点
        text = text.replace('（', '(').replace('）', ')')
        text = text.replace('，', ',').replace('。', '.')
        text = text.replace('：', ':').replace('；', ';')
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace(''', "'").replace(''', "'")
        text = text.replace('！', '!').replace('？', '?')
        # 统一英文标点
        text = text.replace('\u2018', "'").replace('\u2019', "'")
        text = text.replace('\u201c', '"').replace('\u201d', '"')
        # 去除首尾空白
        text = text.strip()
        return text

    def _similarity(self, expected: str, actual: str) -> float:
        """计算两段文字的相似度（0~1）"""
        expected = self._normalize(expected)
        actual = self._normalize(actual)

        if not expected and not actual:
            return 1.0
        if not expected or not actual:
            return 0.0

        return SequenceMatcher(None, expected, actual).ratio()

    def _diff_text(self, expected: str, actual: str) -> list[DiffItem]:
        """逐字对比找出所有差异"""
        expected = self._normalize(expected)
        actual = self._normalize(actual)

        sm = SequenceMatcher(None, expected, actual)
        diffs = []

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == 'equal':
                continue
            elif tag == 'replace':
                diffs.append(DiffItem(
                    position=i1,
                    expected=expected[i1:i2],
                    actual=actual[j1:j2],
                    diff_type='replace',
                ))
            elif tag == 'delete':
                diffs.append(DiffItem(
                    position=i1,
                    expected=expected[i1:i2],
                    actual='',
                    diff_type='delete',
                ))
            elif tag == 'insert':
                diffs.append(DiffItem(
                    position=i1,
                    expected='',
                    actual=actual[j1:j2],
                    diff_type='insert',
                ))

        return diffs

    # ============================================================
    # 内部方法：截断检测
    # ============================================================

    def _check_truncation(self, blocks: list[TextBlock]) -> tuple[bool, list[str]]:
        """
        检测文字是否被截断。

        判断依据：
          1. 文字块靠近屏幕底部/右侧边缘且没有句末标点
          2. OCR 置信度 < 0.6 的边缘文字块
          3. 句子以连字符(-)结尾（英文换行截断的标志）
        """
        if not blocks:
            return True, []

        evidence = []

        # 找到屏幕最大边界
        max_x = max(b.bbox[2] for b in blocks)
        max_y = max(b.bbox[3] for b in blocks)

        for block in blocks:
            text = block.text.strip()
            if not text:
                continue

            # 检测1: 靠近边缘且无句末标点
            near_bottom = block.bbox[3] >= max_y - 20
            near_right = block.bbox[2] >= max_x - 20

            if near_bottom or near_right:
                last_char = text[-1] if text else ""
                has_ending = last_char in '.。?!！…~)）]】""\''

                if not has_ending and len(text) > 2:
                    evidence.append(
                        f"文字块靠近{'底部' if near_bottom else '右侧'}边缘且无句末标点: "
                        f"\"{text[-20:]}\" (位置: {block.bbox})"
                    )

            # 检测2: 低置信度边缘文字
            if block.confidence < 0.6:
                evidence.append(
                    f"低置信度文字块 (confidence={block.confidence:.2f}): "
                    f"\"{text[:30]}\""
                )

            # 检测3: 英文断词（以连字符结尾）
            if text.rstrip().endswith('-') and len(text) > 1:
                evidence.append(f"疑似英文断词: \"{text[-15:]}\"")

        is_complete = len(evidence) == 0
        return is_complete, evidence

    # ============================================================
    # 内部方法：LLM 校验
    # ============================================================

    def _llm_check_knowledge(self, content_text: str) -> list[str]:
        """调用 LLM 检查知识性错误"""
        prompt = self._build_knowledge_prompt(content_text)
        try:
            response = self.llm(prompt)
            return self._parse_llm_errors(response)
        except Exception as e:
            return [f"LLM 校验异常: {e}"]

    def _llm_check_logic(self, content_text: str) -> list[str]:
        """调用 LLM 检查逻辑性错误"""
        prompt = self._build_logic_prompt(content_text)
        try:
            response = self.llm(prompt)
            return self._parse_llm_errors(response)
        except Exception as e:
            return [f"LLM 校验异常: {e}"]

    def _build_knowledge_prompt(self, content_text: str) -> str:
        """构建知识性校验的 prompt"""
        qtype = self.expected.get("question_type", "未知")
        grade = self.expected.get("grade", "未知")
        module = self.expected.get("module", "未知")
        correct = self.expected.get("correct_answer", "未知")
        knowledge = self.expected.get("knowledge_points", [])

        return f"""你是英语教学内容的质检专家。请检查以下题目内容是否有知识性错误。

【题目信息】
- 年级: {grade}
- 模块: {module}
- 题型: {qtype}
- 正确答案: {correct}
- 知识点: {", ".join(knowledge) if knowledge else "未指定"}

【题目内容】
{content_text}

请从以下维度逐项检查，每个维度给出"通过"或具体问题：

1. 单词拼写：所有英文单词拼写是否正确？
2. 语法正确性：句子语法是否正确？
3. 知识点匹配：题目内容是否符合{grade}的教学大纲？知识点是否与{module}匹配？
4. 答案正确性：正确答案"{correct}"在题目语境下是否正确？

如果全部通过，请回复"知识性检查：全部通过"。
如有任何问题，请逐条列出，格式为"- [具体问题描述]"
只回复检查结果，不要其他内容。"""

    def _build_logic_prompt(self, content_text: str) -> str:
        """构建逻辑性校验的 prompt"""
        qtype = self.expected.get("question_type", "未知")
        correct = self.expected.get("correct_answer", "未知")

        return f"""你是逻辑审查专家。请检查以下题目的逻辑一致性。

【题目信息】
- 题型: {qtype}
- 正确答案: {correct}

【题目内容】
{content_text}

请从以下维度检查：

1. 题干与选项之间是否存在逻辑矛盾？
2. 正确答案是否唯一（不存在多个正确答案或没有正确答案的情况）？
3. 干扰项是否有明显不合理之处（如与正确答案完全矛盾但常识上可能成立）？
4. 题目表述是否有歧义，导致可能产生多种理解？

如果全部通过，请回复"逻辑性检查：全部通过"。
如有任何问题，请逐条列出，格式为"- [具体问题描述]"
只回复检查结果，不要其他内容。"""

    @staticmethod
    def _parse_llm_errors(response: str) -> list[str]:
        """解析 LLM 返回，提取错误列表"""
        if not response:
            return []

        response_lower = response.lower()
        if "全部通过" in response_lower or "all passed" in response_lower:
            return []

        errors = []
        for line in response.strip().split('\n'):
            line = line.strip()
            if line.startswith('-') and len(line) > 2:
                error = line[1:].strip()
                if error and len(error) > 5:
                    errors.append(error)

        return errors

    # ============================================================
    # 结果持久化
    # ============================================================

    def _save_result(self, result: ContentResult, screenshot_path: str):
        """将校验结果保存为 JSON 文件，与截图放在同目录"""
        try:
            screenshot_dir = os.path.dirname(screenshot_path)
            basename = os.path.splitext(os.path.basename(screenshot_path))[0]
            json_path = os.path.join(screenshot_dir, f"{basename}_check.json")

            data = {
                "question_id": self.expected.get("question_id", ""),
                "expected": self.expected,
                "content_result": {
                    "script_match": result.script_match,
                    "display_complete": result.display_complete,
                    "knowledge_errors": result.knowledge_errors,
                    "logic_errors": result.logic_errors,
                    "similarity": result.similarity,
                    "diffs": [
                        {"pos": d.position, "expected": d.expected, "actual": d.actual,
                         "type": d.diff_type}
                        for d in result.diffs
                    ],
                    "trunction_evidence": result.trunction_evidence,
                },
                "screenshot": screenshot_path,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"[QuestionChecker] 保存结果失败: {e}")

    # ============================================================
    # 获取统计
    # ============================================================

    def get_stats(self) -> dict:
        """获取校验统计"""
        total = max(self.stats["total_questions"], 1)
        return {
            **self.stats,
            "stem_pass_rate": f"{self.stats['stem_passed']}/{total} "
                              f"({100*self.stats['stem_passed']/total:.1f}%)",
            "content_pass_rate": f"{self.stats['content_passed']}/{total} "
                                 f"({100*self.stats['content_passed']/total:.1f}%)",
        }

    def reset_stats(self):
        """重置统计"""
        for key in self.stats:
            self.stats[key] = 0


# ============================================================
# 工厂函数：从 JSON 文件批量加载题目数据并创建校验器
# ============================================================

def load_questions_from_json(json_path: str) -> list[dict]:
    """从 JSON 文件加载题目数据列表"""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and "questions" in data:
        return data["questions"]
    else:
        return [data]


def create_checker_for_question(adb_controller, question_data: dict,
                                 ocr_backend: str = "auto",
                                 llm_client=None) -> QuestionChecker:
    """为单道题创建校验器"""
    return QuestionChecker(
        adb_controller=adb_controller,
        expected_data=question_data,
        ocr_backend=ocr_backend,
        llm_client=llm_client,
    )
