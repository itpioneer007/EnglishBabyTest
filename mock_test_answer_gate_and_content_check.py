# -*- coding: utf-8 -*-
"""mock 端到端测试：① 只解析"有明确答案"的题 ② App 题目原文错误检查（2026-09-15）。

用户需求原文：
  「给出脚本解析不是所有题目都需要，是指明确有答案的题目……这些都不算是题目，
    视觉模型对于图片内容进行解析，只需要给学生进行跟读就行了，没有明确答案。
    现在要做的就是对于 app 里面有明确答案的题目进行解析，并且还要检查测试过程中
    app 放的题目内容是否存在错误。举个例子：题目的原文有一句话是
    "Tom see lots of people running in the playground yesterday"，
    那么你应该知道题目的 see 用错了，是 saw 过去式。」

对应两条规则：
  规则A（准入）：口语跟读 / 看图说句这类**没有明确答案**的题不进脚本。
        判据 = 有选项 / 有实义答案 / 有图片题截图（命中其一）。
  规则B（查错）：对进入脚本的题，检查 App 显示的英文原文有无语法用词错误，
        既在**日志**里以 ⚠ 标出，也写进**脚本**，并让知识点解析指出该错误。
"""
import contextlib
import io
import os
import sys
import tempfile
import types
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from common.gen_script import (  # noqa: E402
    QuestionCollector, _parse_content_issues,
)

# ---------------------------------------------------------------- 假 LLM
_FAKE = {"prompts": [], "check_reply": "无错误"}


def _install_fake_llm():
    """把 src.reviewer_common 换成假模块，避免测试打真实 LLM。

    内容检查（prompt 含"审校老师"）返回 _FAKE["check_reply"]，
    其余（知识点）返回一段合格解析；所有 prompt 都记进 _FAKE["prompts"]。
    """
    fake = types.ModuleType("src.reviewer_common")

    class _FakeLLM:
        def ask(self, prompt, **kw):
            _FAKE["prompts"].append(prompt)
            if "审校老师" in prompt:
                return _FAKE["check_reply"]
            return "yesterday 表示过去，动词要用过去式 saw，不能用原形 see。"

    class LLMClient:
        @staticmethod
        def from_config():
            return _FakeLLM()

    fake.LLMClient = LLMClient
    fake.is_fatal_llm_error = lambda s: False
    sys.modules["src.reviewer_common"] = fake


def _mk_img(tmpdir, name="pic.png"):
    p = os.path.join(tmpdir, name)
    with open(p, "wb") as f:
        f.write(b"fake")
    return p


def _q(**kw):
    base = {"qno": 1, "stem": "", "options": [], "answer": "", "qtype": "",
            "unit": 1, "level": None, "recording": "", "speaker_word": "",
            "knowledge": "", "big": None, "image_path": "", "time": "00:00:00"}
    base.update(kw)
    return base


# ================================================================ 规则A
class TestAnswerGate(unittest.TestCase):
    """只收「有明确答案」的题：口语跟读 / 看图说句不入脚本。"""

    def setUp(self):
        _install_fake_llm()
        _FAKE["prompts"].clear()
        self.tmp = tempfile.mkdtemp()

    def _coll(self, module="单元自检"):
        return QuestionCollector(module=module, version="湘少版(2024审定)",
                                 grade="六年级上册", save_root=self.tmp)

    def test_oral_sentence_question_skipped(self):
        """口语跟读题（有题干但无选项/答案/图）→ 跳过，不计入脚本"""
        c = self._coll("口语训练")
        c.add(qno=1, stem="This is a beautiful farm.", options=[], answer="",
              qtype="口语题", unit=1, big=1, allow_listen=True)
        self.assertEqual(len(c.questions), 0)
        self.assertEqual(c.skipped_no_answer, 1)

    def test_audio_readalong_question_skipped(self):
        """「听音频跟读」这类无内容小题 → 跳过"""
        c = self._coll("口语训练")
        c.add(qno=2, stem="听音频跟读", options=[], answer="",
              qtype="口语题", unit=1, big=4, allow_listen=True)
        self.assertEqual(len(c.questions), 0)
        self.assertEqual(c.skipped_no_answer, 1)

    def test_vision_stem_question_skipped(self):
        """看图说句（题干预设为视觉描述）同样无答案 → 跳过"""
        c = self._coll("口语训练")
        c.add(qno=3, stem="I visited my grandparents.", options=[], answer="",
              qtype="口语题·看图", unit=1, big=3, allow_listen=True)
        self.assertEqual(len(c.questions), 0)

    def test_options_kept_even_if_answer_unread(self):
        """有选项（选择题/判断题）→ 必须保留：答案没读到是解析问题，
        不能因此把整道题丢掉（否则大面积丢题）"""
        c = self._coll()
        c.add(qno=1, stem="选出不同类的一项", options=["A. apple", "B. dog"],
              answer="", qtype="单元自检", unit=1)
        self.assertEqual(len(c.questions), 1)
        self.assertEqual(c.skipped_no_answer, 0)

    def test_real_answer_without_options_kept(self):
        """填空题式：只有答案文本、没有选项 → 保留"""
        c = self._coll()
        c.add(qno=2, stem="Tom ___ lots of people yesterday.", options=[],
              answer="saw", qtype="单元自检", unit=1)
        self.assertEqual(len(c.questions), 1)

    def test_placeholder_answer_without_options_skipped(self):
        """占位答案（人工核查）且无选项无图 → 不算"明确答案"→ 跳过"""
        c = self._coll()
        c.add(qno=3, stem="（图片题）", options=[], answer="人工核查（图片题）",
              qtype="单元自检", unit=1)
        self.assertEqual(len(c.questions), 0)
        self.assertEqual(c.skipped_no_answer, 1)

    def test_image_question_kept_without_answer(self):
        """图片题：无题干无选项无答案，但有截图 → 保留（答案由 App 判定）"""
        c = self._coll()
        c.add(qno=4, stem="", options=[], answer="", qtype="图片题", unit=1,
              image_path=_mk_img(self.tmp))
        self.assertEqual(len(c.questions), 1)

    def test_finish_unit_produces_no_docx_when_all_oral(self):
        """整单元全是口语题 → 不产出脚本文件（用户："现在这些题目没必要啊"）"""
        c = self._coll("口语训练")
        for i in range(1, 6):
            c.add(qno=i, stem=f"This is sentence {i}.", options=[], answer="",
                  qtype="口语题", unit=1, big=1, allow_listen=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            path = c.finish_unit(unit=1)
        self.assertIsNone(path)
        self.assertFalse(os.listdir(self.tmp), "不应产出任何 docx")
        self.assertIn("未生成解析脚本", buf.getvalue())
        self.assertIn("无明确答案", buf.getvalue())

    def test_counters_reset_after_empty_finish(self):
        """空单元返回后计数器必须清零（收集器跨单元复用，否则 U2 统计串味）"""
        c = self._coll("口语训练")
        c.add(qno=1, stem="This is a farm.", options=[], answer="",
              qtype="口语题", unit=1, allow_listen=True)
        with contextlib.redirect_stdout(io.StringIO()):
            c.finish_unit(unit=1)
        self.assertEqual(c.skipped_no_answer, 0)
        self.assertEqual(c.skipped_no_stem, 0)


# ================================================================ 规则B
class TestContentIssueParser(unittest.TestCase):
    """内容检查返回值的解析（LLM 输出容错）"""

    def test_no_error(self):
        self.assertEqual(_parse_content_issues("无错误"), [])

    def test_empty(self):
        self.assertEqual(_parse_content_issues(""), [])

    def test_parse_one_issue(self):
        r = _parse_content_issues("see|saw|yesterday 提示用一般过去时")
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["wrong"], "see")
        self.assertEqual(r[0]["correct"], "saw")
        self.assertIn("过去", r[0]["reason"])

    def test_parse_tolerates_bullet_and_fullwidth(self):
        r = _parse_content_issues("- see｜saw｜过去时\n• a apple|an apple|冠词用 an")
        self.assertEqual(len(r), 2)
        self.assertEqual(r[1]["wrong"], "a apple")

    def test_ignores_same_before_after(self):
        """"错误片段 == 应改为" 是模型噪声，丢弃"""
        self.assertEqual(_parse_content_issues("see|see|无变化"), [])

    def test_ignores_no_error_line(self):
        self.assertEqual(_parse_content_issues("无错误|无错误|无错误"), [])


class TestContentCheckCalls(unittest.TestCase):
    """何时调用 LLM、何时跳过（省额度）"""

    def setUp(self):
        _install_fake_llm()
        _FAKE["prompts"].clear()
        _FAKE["check_reply"] = "无错误"
        self.tmp = tempfile.mkdtemp()
        self.c = QuestionCollector(module="单元自检", version="湘少版",
                                   grade="六年级上册", save_root=self.tmp)

    def test_skips_vision_generated_stem(self):
        """视觉模型生成的题干不是 App 原文 → 不查（查自己没有意义）"""
        r = self.c._llm_content_check(_q(
            stem="A woman is leaving the store.", qtype="口语题·看图"))
        self.assertEqual(r, [])
        self.assertEqual(_FAKE["prompts"], [])

    def test_skips_short_english(self):
        """英文词少于 3 个（如单词题 / 中文指令题）→ 没有句子可审，不查"""
        self.assertEqual(self.c._llm_content_check(_q(stem="apple")), [])
        self.assertEqual(self.c._llm_content_check(
            _q(stem="听录音，选出你听到的单词")), [])
        self.assertEqual(_FAKE["prompts"], [])

    def test_calls_llm_for_english_sentence(self):
        _FAKE["check_reply"] = "see|saw|yesterday 提示用一般过去时"
        r = self.c._llm_content_check(_q(
            stem="Tom see lots of people running in the playground yesterday"))
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["correct"], "saw")
        self.assertEqual(len(_FAKE["prompts"]), 1)

    def test_result_cached_same_text(self):
        """同一原文只查一次（跨题/跨单元复用）"""
        _FAKE["check_reply"] = "see|saw|过去时"
        q = _q(stem="Tom see lots of people running in the playground yesterday")
        self.c._llm_content_check(q)
        self.c._llm_content_check(dict(q))
        self.c._llm_content_check(dict(q, qno=99))
        self.assertEqual(len(_FAKE["prompts"]), 1)

    def test_recording_included_in_check(self):
        """听力原文（recording）也要参与检查"""
        _FAKE["check_reply"] = "see|saw|过去时"
        self.c._llm_content_check(_q(stem="听录音，判断对错",
                                     recording="Tom see a film yesterday."))
        self.assertEqual(len(_FAKE["prompts"]), 1)
        self.assertIn("Tom see a film yesterday.", _FAKE["prompts"][0])

    def test_sentence_option_included(self):
        """选项是完整句时纳入检查；单词/短语选项不纳入（防误报）"""
        _FAKE["check_reply"] = "无错误"
        self.c._llm_content_check(_q(
            stem="选择正确的一项",
            options=["A. He go to school by bus everyday.",
                     "B. He goes to school by bus every day."]))
        self.assertEqual(len(_FAKE["prompts"]), 1)
        self.assertIn("He go to school by bus everyday.", _FAKE["prompts"][0])

    def test_short_options_not_included(self):
        """只有单词选项 → 不因选项触发检查（题干若也无可查内容则完全跳过）"""
        _FAKE["check_reply"] = "无错误"
        self.c._llm_content_check(_q(stem="选择正确的单词",
                                     options=["A. see", "B. saw", "C. sees"]))
        self.assertEqual(_FAKE["prompts"], [])


class TestFinishUnitContentCheck(unittest.TestCase):
    """finish_unit 中的查错：日志 ⚠ + 脚本渲染 + 传给知识点 prompt"""

    def setUp(self):
        _install_fake_llm()
        _FAKE["prompts"].clear()
        self.tmp = tempfile.mkdtemp()

    def _run(self, questions):
        c = QuestionCollector(module="单元自检", version="湘少版",
                              grade="六年级上册", save_root=self.tmp)
        c.questions = questions
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            path = c.finish_unit(unit=1)
        from docx import Document
        paras = [p.text.strip() for p in Document(path).paragraphs
                 if p.text and p.text.strip()]
        return path, paras, buf.getvalue()

    def test_error_logged_and_rendered(self):
        """原文有错 → 日志 ⚠ 标出，脚本里出现"题目原文疑似错误"行"""
        _FAKE["check_reply"] = "see|saw|yesterday 提示用一般过去时"
        q = _q(qno=1, stem="Tom see lots of people running in the playground yesterday",
               options=["A. see", "B. saw"], answer="B",
               qtype="单元自检", knowledge="（预置）")
        _path, paras, out = self._run([q])
        self.assertIn("题目原文疑似错误：see → saw", out)
        self.assertTrue(any("⚠ 题目原文疑似错误：see → saw" in p for p in paras),
                        f"脚本应含错误行，实际: {paras}")
        self.assertTrue(any("本次共发现 1 处题目原文疑似错误" in p for p in paras))

    def test_no_error_no_extra_line(self):
        """无错的题 → 脚本不出现错误行，表头不出现错误汇总"""
        _FAKE["check_reply"] = "无错误"
        q = _q(qno=1, stem="He wears a pair of gloves.",
               options=["A. wear", "B. wears"], answer="B",
               qtype="单元自检", knowledge="（预置）")
        _path, paras, out = self._run([q])
        self.assertFalse(any("原文疑似错误" in p for p in paras))
        # 无错时不得出现 ⚠ 告警行（汇总行"发现 0 处疑似错误"是正常的）
        self.assertNotIn("⚠", out)

    def test_knowledge_prompt_gets_error_hint(self):
        """原文有错时，知识点 prompt 必须要求"指出该错误"——否则会把
        错误用法当正确内容讲解，等于用错误解析印证错误题目"""
        _FAKE["check_reply"] = "see|saw|yesterday 提示用一般过去时"
        q = _q(qno=1, stem="Tom see lots of people running in the playground yesterday",
               options=["A. see", "B. saw"], answer="B",
               qtype="单元自检", knowledge="")
        self._run([q])
        k_prompts = [p for p in _FAKE["prompts"] if "审校老师" not in p]
        self.assertEqual(len(k_prompts), 1)
        self.assertIn("see 应为 saw", k_prompts[0])
        self.assertIn("不要把错误用法当作正确内容", k_prompts[0])

    def test_check_runs_before_knowledge(self):
        """查错必须早于知识点（顺序断言：prompt 序列里先出现审校请求）"""
        _FAKE["check_reply"] = "see|saw|过去时"
        q = _q(qno=1, stem="Tom see a film yesterday.",
               options=["A. see", "B. saw"], answer="B",
               qtype="单元自检", knowledge="")
        self._run([q])
        kinds = ["check" if "审校老师" in p else "knowledge" for p in _FAKE["prompts"]]
        self.assertEqual(kinds, ["check", "knowledge"], kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
