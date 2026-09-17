# -*- coding: utf-8 -*-
"""mock 端到端测试：解析脚本的 4 处渲染/生成修复（2026-09-15 真机复跑发现）。

背景：口语训练 U1 真机复跑产出 260915湘少六上口语训练U1.docx，暴露 4 个问题：
  ① 第4大题 5 道纯听音跟读题，题干只有页面指令「听音频跟读」，
     LLM 仍生成知识点且 5 条逐字雷同 → 套话，违反"有说服力"要求。
  ② 空选项统一渲染成「（无文字选项·内容见题目图片）」，但口语题根本没有图
     → 审查员以为有图可查（screenshots/script_imgs/ 实际为空）。
  ③ 看图题题干由视觉模型识别（概率性结论），脚本里却没标注需人工复核。
  ④ 知识点 `ans[:120]` 硬截断会切断词语（实测截成「…符合“形容词 + 名」）。

新增修复的验证点，同时回归"文字选项 / image_src 旧标注"不被破坏。
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

from common.gen_script import QuestionCollector, _trim_knowledge  # noqa: E402


# ---------------------------------------------------------------- 假 LLM
_FAKE_LLM_CALLS = {"n": 0}


def _install_fake_llm():
    """把 src.reviewer_common 换成假模块，避免测试打真实 LLM。"""
    fake = types.ModuleType("src.reviewer_common")

    class _FakeLLM:
        def ask(self, prompt, **kw):
            _FAKE_LLM_CALLS["n"] += 1
            return "主语 He 是第三人称单数，一般现在时动词要加 -s，所以用 wears。"

    class LLMClient:
        @staticmethod
        def from_config():
            return _FakeLLM()

    fake.LLMClient = LLMClient
    fake.is_fatal_llm_error = lambda s: False
    sys.modules["src.reviewer_common"] = fake


def _render(questions, tmpdir, module="口语训练"):
    """把题目直接注入收集器并渲染 docx（knowledge 已预置 → 不走图片识别）。"""
    c = QuestionCollector(module=module, version="湘少版(2024审定)",
                          grade="六年级上册", save_root=tmpdir)
    c.questions = questions
    with contextlib.redirect_stdout(io.StringIO()):
        path = c.finish_unit(unit=1)
    from docx import Document
    return [p.text.strip() for p in Document(path).paragraphs if p.text and p.text.strip()]


def _q(**kw):
    base = {"qno": 1, "stem": "", "options": [], "answer": "", "qtype": "口语题",
            "unit": 1, "level": None, "recording": "", "speaker_word": "",
            "knowledge": "（预置）", "big": 1, "image_path": "", "time": "00:00:00"}
    base.update(kw)
    return base


class TestKnowledgeTrim(unittest.TestCase):
    """④ 知识点截断不再切断词语"""

    def test_short_untouched(self):
        self.assertEqual(_trim_knowledge("短解析。", 120), "短解析。")

    def test_cut_at_sentence_end(self):
        # 句号落在 limit 的 60% 之后 → 应在句末断开（不是省略号）
        s = "填" * 110 + "。" + "补" * 60
        out = _trim_knowledge(s, 120)
        self.assertTrue(out.endswith("。"), f"应在句末断开: ...{out[-12:]}")

    def test_cut_at_comma_not_midword(self):
        s = "这是很长的解析内容，" + "填充内容" * 40
        out = _trim_knowledge(s, 120)
        self.assertFalse(out.endswith("填"), f"截断切断了词语: ...{out[-8:]}")
        self.assertTrue(out.endswith("…"))

    def test_no_punct_uses_ellipsis(self):
        out = _trim_knowledge("A" * 300, 120)
        self.assertTrue(out.endswith("…"))

    def test_real_regression_case(self):
        """真机第2题原文：硬截断会停在「符合“形容词 + 名」"""
        s = ("It is a beautiful village. 中主语 It 是第三人称单数，一般现在时里 be 动词用 is，"
             "不用 are/am。beautiful 是形容词，修饰后面的名词 village，说明“美丽的村庄”，"
             "符合“形容词 + 名词”的结构。")
        out = _trim_knowledge(s, 120)
        self.assertLessEqual(len(out), 121)
        self.assertFalse(out.rstrip("…").endswith("名"),
                         f"仍被切断: ...{out[-10:]}")


class TestAudioOnlyKnowledge(unittest.TestCase):
    """① 纯听音跟读题不再调用 LLM 生成套话"""

    def setUp(self):
        _install_fake_llm()
        _FAKE_LLM_CALLS["n"] = 0

    def test_audio_stem_gets_fixed_note_without_llm(self):
        c = QuestionCollector(module="口语训练", save_root=tempfile.gettempdir())
        out = c._llm_knowledge(_q(stem="听音频跟读", qtype="口语题"))
        self.assertIn("需对照录音", out)
        self.assertEqual(_FAKE_LLM_CALLS["n"], 0, "纯听音题不应调用 LLM")
        self.assertIsNone(c._llm, "不应构造 LLM 客户端")

    def test_english_stem_still_uses_llm(self):
        c = QuestionCollector(module="口语训练", save_root=tempfile.gettempdir())
        out = c._llm_knowledge(_q(stem="He wears a pair of gloves.", qtype="口语题"))
        self.assertNotIn("需对照录音", out)
        self.assertEqual(_FAKE_LLM_CALLS["n"], 1, "有英文内容的题仍应走 LLM")
        self.assertIsNotNone(c._llm)

    def test_chinese_non_listen_stem_not_blocked(self):
        """中文但不含听/跟读/口语（如单元自检题干）不应被守卫误伤"""
        c = QuestionCollector(module="单元自检", save_root=tempfile.gettempdir())
        out = c._llm_knowledge(_q(stem="选出不同类的一项", qtype="单元自检"))
        self.assertNotIn("需对照录音", out)
        self.assertEqual(_FAKE_LLM_CALLS["n"], 1)

    def test_chinese_listen_image_stem_with_options_uses_llm(self):
        """回归：中文指令型图片题（题干含"听"、选项由视觉补全）不应被守卫拦掉。

        这是首次实现的真实误伤——"题干无英文"判据太宽，会把
        「听录音，选择与录音内容相符的图片」这类题的知识点吃成固定提示。
        """
        c = QuestionCollector(module="听力专项", save_root=tempfile.gettempdir())
        out = c._llm_knowledge(_q(stem="听录音，选择与录音内容相符的图片",
                                  options=["A. 图片：苹果", "B. 图片：香蕉"],
                                  answer="A", qtype="图片题"))
        self.assertNotIn("需对照录音", out)
        self.assertEqual(_FAKE_LLM_CALLS["n"], 1, "选项由视觉补全的题目仍应走 LLM")


class TestRenderFixes(unittest.TestCase):
    """②③ 渲染：空选项文案按题型区分 + 看图题标注视觉来源"""

    def setUp(self):
        _install_fake_llm()
        self.tmp = tempfile.mkdtemp(prefix="mock_render_")

    def _lines(self, qs):
        return _render(qs, self.tmp)

    def test_oral_no_options_placeholder(self):
        lines = self._lines([_q(stem="This is a beautiful farm.", qtype="口语题")])
        self.assertIn("选项：（口语题·无选项）", lines)
        self.assertNotIn("选项：（无文字选项·内容见题目图片）", lines)

    def test_oral_vision_flag(self):
        lines = self._lines([_q(stem="A woman is leaving the store.",
                                qtype="口语题·看图")])
        stem_line = [l for l in lines if l.startswith("题干：")][0]
        self.assertIn("［内容由视觉识别·需人工复核］", stem_line)

    def test_normal_oral_not_flagged(self):
        lines = self._lines([_q(stem="This is a beautiful farm.", qtype="口语题")])
        stem_line = [l for l in lines if l.startswith("题干：")][0]
        self.assertNotIn("需人工复核", stem_line)

    def test_text_options_still_rendered(self):
        """回归：有文字选项时正常拼接，占位文案不出现"""
        lines = self._lines([_q(stem="He ___ to school.", options=["A. went", "B. visits"],
                                answer="B", qtype="单选")])
        opt = [l for l in lines if l.startswith("选项：")][0]
        self.assertIn("A. went", opt)
        self.assertIn("B. visits", opt)
        self.assertNotIn("无文字选项", opt)

    def test_image_src_legacy_mark_kept(self):
        """回归：image_src 的图片题仍带原标注 + 图片占位文案"""
        lines = self._lines([_q(stem="", qtype="图片题", image_src=True,
                                image_desc="两个孩子在放风筝")])
        stem_line = [l for l in lines if l.startswith("题干：")][0]
        self.assertIn("［内容由视觉识别·需人工复核］", stem_line)
        self.assertIn("选项：（无文字选项·内容见题目图片）", lines)
        self.assertTrue(any(l.startswith("图片内容：") for l in lines))


class TestStemSource(unittest.TestCase):
    """③ 的前半段：口语训练里「题干来源」标记是否被正确识别。

    这条链路只在真机上有意义（模块内 _find_active_sub_question 的返回），
    脚本侧只消费 qtype；这里用合成 XML 验证三种来源：
      vision=有配图（走视觉）/ text=页面文字 / audio=无图无字（听音频跟读）
    """

    @classmethod
    def setUpClass(cls):
        import importlib
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        cls.oral = importlib.import_module("modules.口语训练")

    def _xml(self, inner):
        return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
                + inner + "</hierarchy>")

    def _container(self, body, bounds="[0,100][1080,600]"):
        return (f'<node index="0" resource-id="com.dinoenglish.yyb:id/ll_container"'
                f' bounds="{bounds}">{body}</node>')

    def test_text_source(self):
        xml = self._xml(self._container(
            '<node text="1/5" bounds="[20,120][200,160]"/>'
            '<node text="单词：apple" bounds="[20,200][900,240]"/>'))
        _, _, stem, _ = self.oral._find_active_sub_question(None, xml)
        self.assertIn("apple", stem)
        self.assertEqual(self.oral._LAST_STEM_SRC, "text")

    def test_audio_source(self):
        xml = self._xml(self._container(
            '<node text="1/5" bounds="[20,120][200,160]"/>'))
        _, _, stem, _ = self.oral._find_active_sub_question(None, xml)
        self.assertEqual(stem, "听音频跟读")
        self.assertEqual(self.oral._LAST_STEM_SRC, "audio")

    def test_vision_source(self):
        xml = self._xml(self._container(
            '<node text="1/5" bounds="[20,120][200,160]"/>'
            '<node resource-id="com.dinoenglish.yyb:id/pic_iv"'
            ' bounds="[100,300][900,560]"/>'))
        _orig = self.oral._oral_vision_stem
        self.oral._oral_vision_stem = lambda *a, **k: "A woman is leaving the store."
        try:
            _, _, stem, _ = self.oral._find_active_sub_question(None, xml)
        finally:
            self.oral._oral_vision_stem = _orig
        self.assertEqual(stem, "A woman is leaving the store.")
        self.assertEqual(self.oral._LAST_STEM_SRC, "vision")

    def test_vision_then_text_resets_flag(self):
        """来源标记不能残留：上一题是看图，下一题是文字题时应回到 text"""
        vision_xml = self._xml(self._container(
            '<node text="1/5" bounds="[20,120][200,160]"/>'
            '<node resource-id="com.dinoenglish.yyb:id/pic_iv"'
            ' bounds="[100,300][900,560]"/>'))
        text_xml = self._xml(self._container(
            '<node text="2/5" bounds="[20,120][200,160]"/>'
            '<node text="单词：banana" bounds="[20,200][900,240]"/>'))
        _orig = self.oral._oral_vision_stem
        self.oral._oral_vision_stem = lambda *a, **k: "An old couple is walking."
        try:
            self.oral._find_active_sub_question(None, vision_xml)
            self.assertEqual(self.oral._LAST_STEM_SRC, "vision")
            self.oral._find_active_sub_question(None, text_xml)
        finally:
            self.oral._oral_vision_stem = _orig
        self.assertEqual(self.oral._LAST_STEM_SRC, "text")


if __name__ == "__main__":
    unittest.main(verbosity=2)
