# -*- coding: utf-8 -*-
"""口语训练检查加强 —— mock 回归测试（2026-09-17）

覆盖本轮 4 个改动，每个都对应一个真机实测出来的缺陷：

  A. 解析器：小题级「关键词」被元数据分支吞掉（死代码 + 后写覆盖）
     → 参考答案用 take、关键词写 bring 的问题在整条流水线里无从核对
  B. 关键词↔参考答案 一致性规则（确定性，不调 LLM）
  C. 红框定位：拿不到真实坐标时不得再画占位框（旧版框到手机状态栏上）
  D. 错题卡结构化：结论 / App↔脚本双栏对照 / 独立"怎么改"，且建议≠原因
"""
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


# ============================================================
# A + B：关键词解析与一致性
# ============================================================
class TestKeywordConsistency(unittest.TestCase):
    def setUp(self):
        from src.review_agent import check_answer_keyword_consistency
        self.check = check_answer_keyword_consistency

    def test_用户实测_take_bring不一致被查出(self):
        """教科五上U4 第4大题第3小题：答案 take / 关键词 bring。"""
        problems, n, _ = self.check(
            "They should turn off the lights and take their raincoats.",
            ["turn off the lights, bring their raincoats"],
            "Before they leave school, they should turn off the lights and take their raincoats.")
        self.assertEqual(n, 2)
        self.assertEqual(len(problems), 1)
        self.assertIn("bring", problems[0])
        self.assertIn("take", problems[0])
        self.assertIn("→", problems[0])          # bring → take 这种直接可改的结论

    def test_一致时不报错(self):
        problems, n, _ = self.check("I will close the windows.", ["close the windows"])
        self.assertEqual((problems, n), ([], 1))

    def test_复数括号视为一致(self):
        problems, n, _ = self.check("I will close the windows.", ["close the window(s)"])
        self.assertEqual((problems, n), ([], 1))

    def test_单元标签不算待核对短语(self):
        """'关键词：口语训练#新教科五上U4' 是元信息，不能当成关键词去比。"""
        problems, n, _ = self.check(
            "They should turn off the lights.", ["口语训练#新教科五上U4"])
        self.assertEqual((problems, n), ([], 0))

    def test_纯短语文案不参与(self):
        cases = [
            ("They should turn off the lights and take their raincoats.",
             ["口语训练#新教科五上U4"]),
            ("参考答案：A typhoon will come tomorrow.", ["typhoon"]),
        ]
        for ans, kw in cases:
            problems, n, _ = self.check(ans, kw)
            self.assertEqual(problems, [], f"{kw} 不应报错")

    def test_占位答案不参与(self):
        problems, n, _ = self.check("人工核查", ["close the windows"])
        self.assertEqual((problems, n), ([], 0))

    def test_空答案不参与(self):
        self.assertEqual(self.check("", ["x"])[1], 0)

    def test_答案与短文都不同_提示疑为写错(self):
        problems, n, _ = self.check("I will wear a rainbow coat.",
                                    ["wear a colourful raincoat"], "")
        self.assertEqual(len(problems), 1)
        self.assertIn("均未出现", problems[0])

    def test_同一短语多来源可定位(self):
        _, _, src = self.check(
            "They should turn off the lights and take their raincoats.",
            ["turn off the lights", "bring their raincoats"],
            "they should turn off the lights and take their raincoats")
        self.assertEqual(src["turn off the lights"], ["参考答案", "短文/听力材料"])
        self.assertEqual(src["bring their raincoats"], [])


class TestParserSubKeyword(unittest.TestCase):
    """A：解析器必须把小题级关键词挂到小题上，且不被元数据关键词覆盖。"""

    @classmethod
    def setUpClass(cls):
        docx = ROOT / "uploads" / "260727口语训练新教科五上U4-7（已二校）.docx"
        if not docx.exists():
            raise unittest.SkipTest("缺少口语训练样本脚本")
        from src.parse_yingyubao_docx import parse
        cls.qs = parse(str(docx))

    def test_小题关键词已挂上(self):
        q = [x for x in self.qs if x.unit == 4 and x.big == 4 and x.stage_idx == 3]
        self.assertTrue(q, "找不到 U4 第4大题第3小题")
        self.assertIn("bring their raincoats", q[0].keywords)
        self.assertIn("turn off the lights", q[0].keywords)

    def test_元数据关键词仅作兜底(self):
        """有小题关键词的题，不应退回 ['口语训练','新教科五上U4']。"""
        q = [x for x in self.qs if x.unit == 4 and x.big == 4 and x.stage_idx == 3][0]
        self.assertNotEqual(q.keywords, ["口语训练", "新教科五上U4"])

    def test_全脚本只有一处关键词不一致(self):
        """样本脚本 78 题：期望恰好命中 1 处（用户实测的那处）。"""
        from src.review_agent import check_answer_keyword_consistency as C
        hits = [q for q in self.qs
                if C(q.answer, q.keywords, q.passage or q.recording)[0]]
        self.assertEqual(len(hits), 1, [f"U{x.unit}-{x.big}-{x.stage_idx}" for x in hits])


# ============================================================
# C：红框定位
# ============================================================
class TestTraceRedBox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from trace_engine import TraceEngine
        cls.T = TraceEngine("screenshots")

    def test_无坐标_不返回占位框(self):
        """旧版返回 (40, 60+idx*120, 420x90) → 正好压在手机状态栏上。"""
        self.assertIsNone(self.T._compute_region({}, "stem"))
        self.assertIsNone(self.T._compute_region({"stem": None}, "stem"))

    def test_有坐标_原样返回(self):
        box = {"x": 100, "y": 800, "w": 900, "h": 160}
        self.assertEqual(self.T._compute_region({"stem": box}, "stem"), box)

    def test_非法坐标_视为无(self):
        for bad in ({"x": 1, "y": 2, "w": 0, "h": 10},
                    {"x": 1, "y": 2, "w": 10, "h": 0},
                    {"x": "a", "y": "b", "w": "c", "h": "d"}):
            self.assertIsNone(self.T._compute_region({"stem": bad}, "stem"))

    def test_generate_建议不与原因重复(self):
        qd = {"ai_stem": False,
              "stem_reason": "❌ 大题说明与脚本不符：App 显示「A」，脚本应为「B」"}
        chk = self.T.generate("q1", qd)["checks"]
        self.assertEqual(len(chk), 1)
        self.assertNotEqual(chk[0]["suggestion"], chk[0]["reason"])
        self.assertTrue(chk[0]["suggestion"])

    def test_generate_采用真实建议(self):
        qd = {"ai_answer": False, "answer_reason": "❌ 关键词与参考答案不一致",
              "answer_suggestion": "把关键词改为 take their raincoats"}
        chk = self.T.generate("q1", qd)["checks"][0]
        self.assertEqual(chk["suggestion"], "把关键词改为 take their raincoats")

    def test_generate_合并脚本层结论(self):
        """基础层无结论、脚本层判 False → 必须记错（否则"关键词不一致"永远不出现在错题卡）。"""
        qd = {"ai_answer": None,
              "script": {"status": "done", "answer": False,
                         "answer_reason": "❌ 关键词「bring」与参考答案不一致",
                         "suggestions": {"答案": "统一用词"}}}
        chk = self.T.generate("q1", qd)["checks"]
        self.assertEqual(len(chk), 1)
        self.assertEqual(chk[0]["dimension"], "答案")
        self.assertEqual(chk[0]["layer"], "脚本层")
        self.assertEqual(chk[0]["suggestion"], "统一用词")

    def test_generate_两层都不通过时信息不丢(self):
        qd = {"ai_stem": False, "stem_reason": "基础层原因",
              "script": {"stem": False, "stem_reason": "脚本层原因"}}
        chk = self.T.generate("q1", qd)["checks"][0]
        self.assertIn("基础层原因", chk["reason"])
        self.assertIn("脚本层原因", chk["reason"])

    def test_crop_无坐标返回空(self):
        self.assertEqual(self.T.crop_evidence("whatever.png", [{}], "out.png"), "")


# ============================================================
# D：错题卡片结构化
# ============================================================
class TestLiveCardRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from src.report_exporter import ReportExporter
        cls.E = ReportExporter()

    def _card(self, q):
        return self.E._render_live_card(q, {"version": "教科版", "unit": 4, "stage": "全部"})

    def test_脚本不符渲染双栏对照(self):
        q = {"idx": 1, "question_type": "口语训练", "stem": "第4大题·第1小题",
             "ai_stem": False,
             "stem_reason": "❌ 大题说明与脚本不符：App 显示「请阅读短文」，脚本应为「请大声朗读」",
             "stem_suggestion": "以脚本为准修正 App 大题说明"}
        htmlout = self._card(q)
        self.assertIn("App 实际", htmlout)
        self.assertIn("脚本应为", htmlout)
        self.assertIn("请阅读短文", htmlout)
        self.assertIn("请大声朗读", htmlout)
        self.assertIn("怎么改", htmlout)
        self.assertIn("以脚本为准修正 App 大题说明", htmlout)
        # 引号内容已在双栏里展示 → 正文折叠为「…」，避免同一句话出现两遍
        self.assertIn("App 显示「…」，脚本应为「…」", htmlout)

    def test_关键词不一致渲染为实际_应改为(self):
        q = {"idx": 3, "question_type": "口语训练",
             "ai_answer": False,
             "answer_reason": "❌ 关键词与参考答案不一致：答案里是「take their raincoats」"
                              "（「bring their raincoats」→ take），学生按关键词作答会被判错",
             "answer_suggestion": "把关键词改为 take their raincoats"}
        htmlout = self._card(q)
        self.assertIn("实际", htmlout)
        self.assertIn("应改为", htmlout)
        self.assertIn("take their raincoats", htmlout)
        self.assertIn("bring their raincoats", htmlout)

    def test_无真实建议时给可执行兜底而非原因原文(self):
        q = {"idx": 1, "question_type": "x", "ai_stem": False,
             "stem_reason": "❌ 题干与脚本不符：App 显示「啊」，脚本应为「哦」"}
        htmlout = self._card(q)
        self.assertIn("对照脚本核对并修正该处", htmlout)

    def test_建议缺失时给出可执行兜底(self):
        q = {"idx": 1, "question_type": "x", "ai_image": False,
             "image_reason": "不通过：配图错误", "image_suggestion": "换成 cat 的图片"}
        htmlout = self._card(q)
        self.assertIn("换成 cat 的图片", htmlout)

    def test_截图区带说明文字(self):
        q = {"idx": 1, "question_type": "x", "screenshot": "auto_口语训练_q001_100000.png",
             "ai_stem": False, "stem_reason": "❌ 题干与脚本不符：App 显示「A」，脚本应为「B」"}
        htmlout = self._card(q)
        self.assertIn("证据截图", htmlout)


# ============================================================
# E：evidence 坐标提取（红框精准定位的数据来源）
# ============================================================
class TestEvidenceBox(unittest.TestCase):
    def test_按文字取区间(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        from common.evidence import _box_of_text, _union_boxes
        xml = ('<node text="请阅读短文，点击“小喇叭”播放问题" '
               'bounds="[60,700][1020,860]" class="android.widget.TextView"/>')
        box = _box_of_text(xml, "请阅读短文，点击“小喇叭”播放问题")
        self.assertEqual(box, {"x": 60, "y": 700, "w": 960, "h": 160})
        self.assertIsNone(_box_of_text(xml, "不存在的文字"))

    def test_合并外接矩形(self):
        from common.evidence import _union_boxes
        self.assertEqual(
            _union_boxes([{"x": 10, "y": 100, "w": 100, "h": 40},
                          {"x": 10, "y": 200, "w": 300, "h": 40}]),
            {"x": 10, "y": 100, "w": 300, "h": 140})
        self.assertIsNone(_union_boxes([]))
        self.assertIsNone(_union_boxes([None]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
