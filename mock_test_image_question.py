"""mock 端到端测试：图片题解析进入脚本生成（2026-09-15）

背景：图片题的题干/选项是图片，XML 提不到文字 → 旧版脚本生成时这类题
      被静默丢弃（或在"无题干无答案"分支被降级处理）。

本测试覆盖本次改动的每一条关键行为：
  1. is_image_question()：图片题判 True，普通文字题判 False
  2. _extract_ui_question() 对图片题**提取不到题干**（说明必须靠截图）
  3. save_image_shot()：统一截图入口，成功返回路径、失败返回 ""
  4. add() 常规分支保留 image_path（旧版只在"无题干无答案"时保留 → 内容丢失）
  5. 题干含"听录音…"（听音判定）但带截图 → 不按纯听音跳过
  6. 纯听音、无截图 → 仍跳过（行为不回归）
  7. finish_unit：视觉识别**先于**知识点生成（旧版顺序反了 → 拿空题目问 LLM）
  8. finish_unit：识别出的选项/画面描述/复核标注都写进脚本 docx
  9. finish_unit 后清空 questions（多单元不重复累积）

运行：python mock_test_image_question.py
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "scripts"))
sys.path.insert(0, _HERE)

from common.gen_script import (          # noqa: E402
    QuestionCollector, is_image_question, save_image_shot, _extract_ui_question)


# ── 测试用 XML：图片题（题干是指令文字，选项是图片，无字母文本）──
IMG_Q_XML = """<hierarchy>
<node class="android.widget.TextView" text="听录音，选择与录音内容相符的图片" bounds="[100,300][980,360]"/>
<node class="android.widget.ImageView" resource-id="com.dinoenglish.yyb:id/pic_iv" bounds="[200,400][880,900]"/>
<node class="android.widget.CheckBox" resource-id="com.dinoenglish.yyb:id/option_cb" bounds="[100,1000][500,1300]"/>
<node class="android.widget.CheckBox" resource-id="com.dinoenglish.yyb:id/option_cb" bounds="[520,1000][920,1300]"/>
<node class="android.widget.CheckBox" resource-id="com.dinoenglish.yyb:id/option_cb" bounds="[100,1350][500,1650]"/>
<node class="android.widget.TextView" text="检查" bounds="[400,2200][700,2280]"/>
</hierarchy>"""

# ── 测试用 XML：普通文字选择题（有字母选项）──
TEXT_Q_XML = """<hierarchy>
<node class="android.widget.TextView" resource-id="com.dinoenglish.yyb:id/question_title_tv" text="选出不同类的一项" bounds="[100,300][980,360]"/>
<node class="android.widget.TextView" text="A. apple" bounds="[100,500][500,560]"/>
<node class="android.widget.TextView" text="B. banana" bounds="[100,600][500,660]"/>
<node class="android.widget.TextView" text="C. dog" bounds="[100,700][500,760]"/>
</hierarchy>"""


# ── 测试用 XML：CheckBox 选项但**自带文字**（单元自检式文字选择题）──
#    ⚠ 这类题必须判为"非图片题"：CheckBox 只是控件样式，选项内容是文字。
CHECKBOX_TEXT_XML = """<hierarchy>
<node class="android.widget.TextView" resource-id="com.dinoenglish.yyb:id/question_title_tv" text="选出不同类的一项" bounds="[100,300][980,360]"/>
<node class="android.widget.CheckBox" resource-id="com.dinoenglish.yyb:id/option_cb" text="parrot" bounds="[100,800][500,1000]"/>
<node class="android.widget.CheckBox" resource-id="com.dinoenglish.yyb:id/option_cb" text="notebook" bounds="[520,800][920,1000]"/>
</hierarchy>"""


class _FakeDevice:
    """最小设备桩：只实现 save_image_shot 需要的 screenshot(path)"""

    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def screenshot(self, path):
        self.calls.append(path)
        if not self.ok:
            raise OSError(22, "Invalid argument")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n fake")
        return path


class TestImageQuestionDetect(unittest.TestCase):
    def test_image_question_true(self):
        self.assertTrue(is_image_question(IMG_Q_XML))

    def test_text_question_false(self):
        self.assertFalse(is_image_question(TEXT_Q_XML))

    def test_checkbox_with_text_false(self):
        """CheckBox 选项自带文字 → 文字选择题，不能误判为图片题"""
        self.assertFalse(is_image_question(CHECKBOX_TEXT_XML))

    def test_empty_false(self):
        self.assertFalse(is_image_question(""))

    def test_extract_ui_question_gets_no_stem(self):
        """图片题在 XML 文字层提不到题干 → 正是必须靠截图识别的根因"""
        self.assertEqual(_extract_ui_question(IMG_Q_XML)["stem"], "")
        self.assertEqual(_extract_ui_question(IMG_Q_XML)["options"], [])


class TestSaveImageShot(unittest.TestCase):
    def test_saves_and_returns_path(self):
        d = _FakeDevice()
        p = save_image_shot(d, "听力专项", 7, tag="q")
        try:
            self.assertTrue(p and os.path.exists(p))
            self.assertEqual(os.path.basename(p), "listen_q07.png")
        finally:
            if p and os.path.exists(p):
                os.remove(p)

    def test_returns_empty_on_failure(self):
        self.assertEqual(save_image_shot(_FakeDevice(ok=False), "听力专项", 1), "")

    def test_none_device(self):
        self.assertEqual(save_image_shot(None, "听力专项", 1), "")


class TestAddKeepsImagePath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.img = os.path.join(self.tmp, "pic.png")
        with open(self.img, "wb") as f:
            f.write(b"fake")

    def _coll(self):
        return QuestionCollector(module="听力专项", version="湘少版",
                                 grade="五年级上册", save_root=self.tmp)

    def test_normal_branch_keeps_image_path(self):
        """题干/答案非空的常规分支也必须保留 image_path（旧版此处丢失）"""
        c = self._coll()
        c.add(qno=1, stem="选出不同类的一项", options=["A. apple", "B. dog"],
              answer="B", qtype="听力专项测试", unit=1, image_path=self.img)
        self.assertEqual(len(c.questions), 1)
        self.assertEqual(c.questions[0]["image_path"], self.img)

    def test_listen_stem_with_image_not_skipped(self):
        """题干含"听录音"（听音判定）但带截图 → 不能按纯听音跳过"""
        c = self._coll()
        c.add(qno=2, stem="听录音，选择与录音内容相符的图片",
              options=[], answer="", qtype="图片题", unit=1, image_path=self.img)
        self.assertEqual(len(c.questions), 1)
        self.assertEqual(c.skipped_no_stem, 0)

    def test_pure_listen_without_image_still_skipped(self):
        """纯听音、无截图 → 仍跳过（原有行为不回归）"""
        c = self._coll()
        c.add(qno=3, stem="听录音，选出你听到的单词", options=[], answer="",
              qtype="听力题", unit=1)
        self.assertEqual(len(c.questions), 0)
        self.assertEqual(c.skipped_no_stem, 1)


class TestFinishUnitVisionOrder(unittest.TestCase):
    """核心：视觉识别必须早于知识点生成，否则等于拿空题目问 LLM"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.img = os.path.join(self.tmp, "pic.png")
        with open(self.img, "wb") as f:
            f.write(b"fake")
        self.calls = []
        self.llm_prompts = []

    def _fake_vision(self, img_path, question_hint="", known_options=None, answer_hint=""):
        self.calls.append("vision")
        return {"ok": True,
                "options": ["A. 图片：苹果", "B. 图片：香蕉", "C. 图片：葡萄"],
                "answer": "A",
                "stem": "听录音，选择与录音内容相符的图片",
                "description": "画面是一只红色的苹果"}

    def _fake_llm_factory(self, *a, **kw):
        outer = self

        class _C:
            def ask(self, prompt, **kw2):
                outer.calls.append("llm")
                outer.llm_prompts.append(prompt)
                return "「apple」意为苹果，属水果类单词；dog 是动物，与其他不同类。"

        return _C()

    def test_vision_before_llm_and_content_filled(self):
        import common.vision_fill as vf
        import src.reviewer_common as rc

        c = QuestionCollector(module="听力专项", version="湘少版",
                              grade="五年级上册", save_root=self.tmp)
        c.add(qno=1, stem="", options=[], answer="", qtype="图片题",
              unit=1, image_path=self.img)

        with mock.patch.object(vf, "recognize_image_question", side_effect=self._fake_vision), \
                mock.patch.object(rc.LLMClient, "from_config", side_effect=self._fake_llm_factory):
            out = c.finish_unit(1)

        self.assertTrue(out and os.path.exists(out))
        # ① 顺序：视觉识别先于 LLM 知识点生成
        self.assertIn("vision", self.calls)
        self.assertIn("llm", self.calls)
        self.assertLess(self.calls.index("vision"), self.calls.index("llm"))
        # ② LLM 拿到的是"补全后的题目"（含视觉识别出的选项内容）
        self.assertTrue(any("图片：苹果" in p for p in self.llm_prompts),
                        f"LLM prompt 未包含视觉补全的选项内容: {self.llm_prompts}")
        # ③ 脚本内容：选项 / 画面描述 / 复核标注
        txt = self._read_docx(out)
        self.assertIn("图片：苹果", txt)
        self.assertIn("画面是一只红色的苹果", txt)
        self.assertIn("内容由视觉识别·需人工复核", txt)

    def test_questions_cleared_after_finish(self):
        import common.vision_fill as vf
        import src.reviewer_common as rc

        c = QuestionCollector(module="听力专项", version="湘少版",
                              grade="五年级上册", save_root=self.tmp)
        c.add(qno=1, stem="", options=[], answer="", qtype="图片题",
              unit=1, image_path=self.img)
        with mock.patch.object(vf, "recognize_image_question", side_effect=self._fake_vision), \
                mock.patch.object(rc.LLMClient, "from_config", side_effect=self._fake_llm_factory):
            self.assertTrue(c.finish_unit(1))
            self.assertEqual(len(c.questions), 0)
            # 第二个单元无题 → 不再生成，也不会重复包含上一单元的题
            self.assertIsNone(c.finish_unit(2))

    def test_vision_failure_does_not_crash(self):
        """视觉识别失败 → 不抛出，脚本仍能生成（标注为未识别）"""
        import common.vision_fill as vf
        import src.reviewer_common as rc

        c = QuestionCollector(module="听力专项", version="湘少版",
                              grade="五年级上册", save_root=self.tmp)
        c.add(qno=1, stem="", options=[], answer="", qtype="图片题",
              unit=1, image_path=self.img)

        def _boom(*a, **kw):
            self.calls.append("vision")
            return {"ok": False, "error": "mock 失败"}

        with mock.patch.object(vf, "recognize_image_question", side_effect=_boom), \
                mock.patch.object(rc.LLMClient, "from_config", side_effect=self._fake_llm_factory):
            out = c.finish_unit(1)
        self.assertTrue(out and os.path.exists(out))
        txt = self._read_docx(out)
        self.assertIn("内容由视觉识别·需人工复核", txt)

    @staticmethod
    def _read_docx(path):
        from docx import Document
        return "\n".join(p.text for p in Document(path).paragraphs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
