"""
script_generator.py — A4: 审查脚本自动生成
=============================================

职责:
  当没有公司提供的 DOCX 脚本时，从知识库提取词汇，
  结合 AI 推演正确答案，自动生成审查用的题目脚本。

生成流程:
  1. 从知识库加载指定版本/年级/单元的词汇和句型
  2. 用 AI 根据词汇生成合理的题目（题干、选项、录音、答案）
  3. 输出标准化 JSON，格式与 DOCX 解析结果一致

接口约定 (B 同学调用):
  gen = ScriptGenerator()
  questions = gen.generate(version="新湘鲁六上", unit=6, stage="基础巩固")
  # questions: [{"global_idx": 1, "stem": "...", "recording": "...",
  #               "answer": "B", "options": [...], "type_2": "..."}, ...]

输出格式:
  [
    {
      "global_idx": 1,
      "unit": 6,
      "stage": "基础巩固",
      "stem": "英语课上，老师在播放一段录音，请选出你听到的单词。",
      "recording": "This student is helpful.",
      "answer": "B",
      "options": ["A. help", "B. helpful", "C. happy"],
      "type_1": "听音选择",
      "type_2": "听音选择词汇",
      "keywords": ["听力专项", "新湘鲁六上U6", "word"],
      "knowledge_points": ["helpful 有帮助的"],
      "difficulty": "基础"
    },
    ...
  ]
"""

import sys
import json
import random
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reviewer_common import LLMClient
from src.knowledge_base import KnowledgeBase


# ============================================================
# 题型模板
# ============================================================

# 各阶段的默认题型配置
STAGE_TEMPLATES = {
    "基础巩固": [
        {"type_1": "听音选择", "type_2": "听音选择词汇", "count": 5,
         "description": "听录音，选择你听到的单词或短语"},
        {"type_1": "听音选择", "type_2": "听音选择图片", "count": 5,
         "description": "听录音，选择与录音内容相符的图片"},
    ],
    "综合进阶": [
        {"type_1": "听音判断", "type_2": "听音判断对错", "count": 4,
         "description": "听录音，判断句子是否正确"},
        {"type_1": "听音选择", "type_2": "听音选择答句", "count": 4,
         "description": "听录音，选择合适的答句"},
        {"type_1": "听音填空", "type_2": "听音补全句子", "count": 4,
         "description": "听录音，补全所缺单词"},
    ],
    "难点突破": [
        {"type_1": "听音理解", "type_2": "听音理解短文", "count": 3,
         "description": "听录音，理解短文内容并作答"},
        {"type_1": "听音选择", "type_2": "听音选择答句", "count": 3,
         "description": "听对话，选择正确的答句"},
        {"type_1": "听音填空", "type_2": "听音补全对话", "count": 4,
         "description": "听对话，补全所缺内容"},
    ],
}

# 题干模板
STEM_TEMPLATES = {
    "听音选择词汇": [
        "英语课上，老师在播放一段录音，请选出你听到的单词。",
        "听录音，选出你所听到的词汇。",
        "请仔细听录音，选择正确的单词。",
    ],
    "听音选择图片": [
        "听录音，选择与录音内容相符的图片。",
        "英语课上，老师播放录音，请选出对应的图片。",
    ],
    "听音判断对错": [
        "听录音，判断下列句子是否正确。正确的选✓，错误的选✗。",
        "仔细听录音内容，判断句子是否与录音一致。",
    ],
    "听音选择答句": [
        "听录音，选择正确的答句。",
        "听问句，选出最合适的回答。",
    ],
    "听音补全句子": [
        "听录音，补全句子中所缺的单词。",
        "听录音内容，填写缺失的词汇。",
    ],
    "听音理解短文": [
        "听短文，根据内容选择正确答案。",
        "请认真听短文，回答相关问题。",
    ],
    "听音补全对话": [
        "听对话，补全所缺内容。",
        "根据听到的对话内容，填写缺失部分。",
    ],
}


# ============================================================
# ScriptGenerator — 脚本生成器
# ============================================================

class ScriptGenerator:
    """
    A4 实现: 无脚本时的题目自动生成

    从知识库提取词汇/句型 → AI 推演合理题目 → 输出审查用 JSON

    用法:
        gen = ScriptGenerator()

        # 生成 U6 基础巩固的题目
        questions = gen.generate("新湘鲁六上", 6, "基础巩固")

        # 批量生成多个单元
        for u in [6, 7, 8, 9]:
            qs = gen.generate("新湘鲁六上", u, "基础巩固")
            print(f"Unit {u}: {len(qs)} 题")

        # 导出为 JSON 文件
        gen.export_json(questions, "outputs/generated_script_u6.json")
    """

    def __init__(self, llm: LLMClient = None, kb: KnowledgeBase = None):
        """
        Args:
            llm: LLM 客户端（用于生成录音原文和答案）
            kb: 知识库（用于提取词汇和句型）
        """
        self.llm = llm or LLMClient.from_config()
        self.kb = kb or KnowledgeBase()
        self._question_counter = 0

    # ----------------------------------------------------------
    # 主入口: 生成题目
    # ----------------------------------------------------------

    def generate(self, version: str, unit: int, stage: str,
                 question_count: int = None) -> list[dict]:
        """
        生成指定单元+阶段的题目脚本

        Args:
            version: 教材版本标识，如 "新湘鲁六上"
            unit: 单元号，如 6
            stage: 阶段，如 "基础巩固"
            question_count: 题目数量（不传则按模板默认数量）

        Returns:
            [{"global_idx": 1, "stem": "...", "recording": "...",
              "answer": "B", "options": [...], "type_2": "...", ...}, ...]
        """
        # 1. 解析版本和年级
        grade_label = self._parse_grade(version)

        # 2. 从知识库提取词汇和句型
        vocab = self.kb.get_unit_vocab("湘鲁版", grade_label, unit)
        patterns = self.kb.get_unit_patterns("湘鲁版", grade_label, unit)

        if not vocab:
            print(f"⚠ 知识库中未找到 {version} U{unit} 的词汇，将使用 AI 推测")
            vocab = self._ai_guess_vocab(version, unit, stage)

        if not patterns:
            patterns = self._ai_guess_patterns(version, unit, vocab)

        print(f"📚 知识库: {len(vocab)} 个词汇, {len(patterns)} 个句型")

        # 3. 确定题型和数量
        stage_config = STAGE_TEMPLATES.get(stage, STAGE_TEMPLATES["基础巩固"])
        questions = []

        for tmpl in stage_config:
            count = question_count or tmpl["count"]
            type_2 = tmpl["type_2"]
            type_1 = tmpl["type_1"]

            # 为每个题型选择词汇
            for i in range(count):
                selected = self._pick_vocab_for_question(vocab, type_2, used_words=[])
                if not selected:
                    continue

                self._question_counter += 1
                q = self._generate_one_question(
                    global_idx=self._question_counter,
                    unit=unit,
                    stage=stage,
                    version=version,
                    type_1=type_1,
                    type_2=type_2,
                    vocab_words=selected,
                    all_vocab=vocab,
                    patterns=patterns,
                    grade=grade_label,
                )
                questions.append(q)

        print(f"✅ 生成 {len(questions)} 道题 (U{unit} {stage})")
        return questions

    # ----------------------------------------------------------
    # 生成单道题
    # ----------------------------------------------------------

    def _generate_one_question(self, global_idx: int, unit: int, stage: str,
                                version: str, type_1: str, type_2: str,
                                vocab_words: list, all_vocab: list,
                                patterns: list, grade: str) -> dict:
        """用 AI 生成一道完整的题目"""

        stem = random.choice(STEM_TEMPLATES.get(type_2, ["听录音，选出正确答案。"]))

        # 构建 AI prompt
        prompt = self._build_question_prompt(
            type_2=type_2,
            vocab_words=vocab_words,
            all_vocab=all_vocab,
            patterns=patterns,
            grade=grade,
            unit=unit,
        )

        try:
            ai_response = self.llm.ask(prompt)
            parsed = self._parse_ai_response(ai_response, type_2, vocab_words)
        except Exception as e:
            print(f"  ⚠ AI 生成 Q{global_idx} 失败: {e}，使用模板生成")
            parsed = self._fallback_generate(type_2, vocab_words, all_vocab)

        # 构建标准化输出
        question = {
            "global_idx": global_idx,
            "unit": unit,
            "stage": stage,
            "stage_idx": global_idx,  # 简化为全局序号
            "stem": stem,
            "recording": parsed.get("recording", ""),
            "answer": parsed.get("answer", "B"),
            "options": parsed.get("options", self._make_options(vocab_words)),
            "type_1": type_1,
            "type_2": type_2,
            "difficulty": "基础" if stage == "基础巩固" else (
                "中等" if stage == "综合进阶" else "较难"
            ),
            "keywords": [
                "听力专项",
                f"{version}U{unit}",
                type_2.replace("听音", "").lower() if "听音" in type_2 else "word",
            ],
            "knowledge_points": [
                f"{w} {self._word_meaning(w)}" for w in vocab_words[:3]
            ],
        }
        return question

    def _build_question_prompt(self, type_2: str, vocab_words: list,
                                all_vocab: list, patterns: list,
                                grade: str, unit: int) -> str:
        """构建 AI 生成题目的 prompt"""
        vocab_str = ", ".join(vocab_words)
        all_vocab_str = ", ".join(random.sample(all_vocab, min(15, len(all_vocab))))
        patterns_str = "; ".join(patterns[:5]) if patterns else "（暂无）"

        return f"""你是一位小学英语教材编写专家。请为{grade}年级学生生成一道"{type_2}"题。

【约束条件】
- 核心词汇: {vocab_str}
- 本单元全部词汇（可选做干扰项）: {all_vocab_str}
- 本单元句型: {patterns_str}
- 年级: {grade} | 单元: Unit {unit}

【生成要求】
1. 录音原文(recording): 一个完整的英文句子，自然地道，包含 1-2 个核心词汇
2. 正确答案(answer): 用字母表示，如 A/B/C
3. 选项(options): 3个选项(A/B/C)，正确答案要明显基于录音内容
4. 难度适合{grade}学生，词汇和句型不超纲
5. 录音长度: 8-15个单词

【输出格式】(严格JSON)
{{
  "recording": "英文录音原文",
  "answer": "A/B/C",
  "options": ["A. xxx", "B. xxx", "C. xxx"]
}}

只输出JSON，不要其他内容。"""

    def _parse_ai_response(self, response: str, type_2: str,
                           vocab_words: list) -> dict:
        """解析 AI 返回的 JSON"""
        # 尝试提取 JSON
        import re
        json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 尝试修复常见格式问题
        clean = response.strip()
        if clean.startswith("```"):
            clean = re.sub(r'^```\w*\n?', '', clean)
            clean = re.sub(r'\n?```$', '', clean)
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            pass

        # 回退
        return self._fallback_generate(type_2, vocab_words)

    def _fallback_generate(self, type_2: str, vocab_words: list,
                           all_vocab: list = None) -> dict:
        """无需 AI 的模板生成（回退方案）"""
        correct_word = vocab_words[0] if vocab_words else "apple"
        all_words = (all_vocab or vocab_words)[:6]

        # 找干扰项
        distractors = [w for w in all_words if w != correct_word][:2]
        while len(distractors) < 2:
            distractors.append("book")

        # 生成录音
        if type_2 in ("听音选择词汇", "听音选择图片"):
            recording = f"I can see a {correct_word}. The {correct_word} is nice."
        elif type_2 in ("听音判断对错",):
            recording = f"The {correct_word} is very beautiful."
        elif type_2 in ("听音选择答句",):
            recording = f"What can you see? I can see a {correct_word}."
        elif type_2 in ("听音补全句子", "听音补全对话"):
            recording = f"There is a {correct_word} on the desk. It looks great."
        elif type_2 in ("听音理解短文",):
            recording = (
                f"Today I see a {correct_word}. It is very nice. "
                f"I like the {correct_word} very much."
            )
        else:
            recording = f"This is a {correct_word}."

        # 构建选项
        options = [
            f"A. {distractors[0] if len(distractors) > 0 else 'book'}",
            f"B. {correct_word}",
            f"C. {distractors[1] if len(distractors) > 1 else 'pen'}",
        ]
        # 随机打乱（但答案保持在合理位置）
        random.shuffle(options)
        # 找答案字母
        answer_letter = "B"
        for opt in options:
            if correct_word in opt:
                answer_letter = opt[0]
                break

        return {
            "recording": recording,
            "answer": answer_letter,
            "options": options,
        }

    # ----------------------------------------------------------
    # 词汇选择
    # ----------------------------------------------------------

    def _pick_vocab_for_question(self, vocab: list, type_2: str,
                                  used_words: list = None) -> list:
        """根据题型选择合适的词汇"""
        if not vocab:
            return []

        # 去重已使用的
        available = [v for v in vocab if v not in (used_words or [])]
        if not available:
            available = vocab

        # 根据题型选择词汇数量
        count = 1  # 默认 1 个核心词
        if "短文" in type_2 or "对话" in type_2:
            count = 2

        selected = random.sample(available, min(count, len(available)))
        return selected

    # ----------------------------------------------------------
    # 辅助方法
    # ----------------------------------------------------------

    def _parse_grade(self, version: str) -> str:
        """从版本名解析年级，如 '新湘鲁六上' → '六上'"""
        grade_map = {
            "三上": "三上", "三下": "三下",
            "四上": "四上", "四下": "四下",
            "五上": "五上", "五下": "五下",
            "六上": "六上", "六下": "六下",
        }
        for key, val in grade_map.items():
            if key in version:
                return val
        return "六上"  # 默认

    def _make_options(self, words: list, answer_index: int = 1) -> list:
        """生成标准 A/B/C 选项"""
        options = []
        labels = ["A", "B", "C"]
        for i, w in enumerate(words[:3]):
            options.append(f"{labels[i]}. {w}")
        while len(options) < 3:
            options.append(f"{labels[len(options)]}. ___")
        return options[:3]

    def _word_meaning(self, word: str) -> str:
        """简单词义推断（中英混合词汇处理）"""
        # 如果已经是中文，直接返回
        if any('\u4e00' <= c <= '\u9fff' for c in word):
            return ""
        # 从知识库查
        results = self.kb.search_vocab(word)
        if results:
            return f"(在{results[0]['grade']}-U{results[0]['unit']})"
        return ""

    def _ai_guess_vocab(self, version: str, unit: int, stage: str) -> list:
        """AI 推测单元词汇（知识库缺失时的回退）"""
        prompt = f"""你是小学英语教材专家。
请列出{version} Unit {unit} ({stage}阶段) 可能涉及的 10-15 个英语核心词汇。
只输出词汇，每行一个，不要序号和解释。"""
        try:
            response = self.llm.ask(prompt)
            words = [w.strip() for w in response.split("\n") if w.strip()]
            return [w for w in words if any(c.isalpha() for c in w)]
        except Exception:
            return ["student", "teacher", "classroom", "listen", "speak"]

    def _ai_guess_patterns(self, version: str, unit: int, vocab: list) -> list:
        """AI 推测单元句型"""
        prompt = f"""你是小学英语教材专家。
请为{version} Unit {unit} 列出 3-5 个核心句型。
已知词汇: {', '.join(vocab[:10])}
只输出句型，每行一个。"""
        try:
            response = self.llm.ask(prompt)
            return [s.strip() for s in response.split("\n") if s.strip()]
        except Exception:
            return [f"I can see a {v}." for v in vocab[:3]]

    # ----------------------------------------------------------
    # 导出
    # ----------------------------------------------------------

    def export_json(self, questions: list[dict], path: str = None) -> str:
        """导出题目为 JSON 文件"""
        if path is None:
            path = f"outputs/generated_script_{int(__import__('time').time())}.json"

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "generated_by": "ScriptGenerator (A4)",
                "total": len(questions),
                "questions": questions,
            }, f, ensure_ascii=False, indent=2)

        print(f"📄 脚本已导出: {path}")
        return path


# ============================================================
# 便捷函数
# ============================================================

_generator = None

def get_generator() -> ScriptGenerator:
    """获取全局 ScriptGenerator 实例"""
    global _generator
    if _generator is None:
        _generator = ScriptGenerator()
    return _generator


def generate_script(version: str, unit: int, stage: str) -> list[dict]:
    """便捷函数: 生成题目脚本"""
    gen = get_generator()
    return gen.generate(version, unit, stage)


# ============================================================
# 独立测试
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("A4 脚本生成器 - 独立测试")
    print("=" * 60)

    gen = ScriptGenerator()

    # 测试生成 U6 基础巩固
    questions = gen.generate("新湘鲁六上", 6, "基础巩固")
    print(f"\n生成 {len(questions)} 道题")

    # 预览前 3 题
    for q in questions[:3]:
        print(f"\n  Q{q['global_idx']:02d} [{q['type_2']}] Unit {q['unit']}")
        print(f"    题干: {q['stem'][:50]}")
        print(f"    录音: {q['recording'][:60]}")
        print(f"    答案: {q['answer']}")
        print(f"    选项: {q['options']}")

    # 导出
    gen.export_json(questions, "outputs/generated_test_script.json")
