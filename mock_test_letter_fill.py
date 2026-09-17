# -*- coding: utf-8 -*-
"""mock 端到端测试：字母块补全单词题型（2026-09-15）。

用户问题原文：「这道题目为什么app识别不了」
  —— 湘少六上 U1 单元自检 第14题：`根据中文提示，选择正确的字母补全单词。`
     已给首字母 b + 一个空位 + 字母块 b l c n t j y e s z + 提示「通过，凭借（做某事）」
     → 答案 by（点字母 y）。自动化当时把它当"选词填空"处理 → 词长/位置过滤双双不命中
       → 空转到未知题型 → 连续 5 次后退出循环（线上现象：跑到 13 题就"完成"，设备停在 14/40）。

本测试锁死的契约：
  ① 题型检测：select_tv 空位 + **单字母** select_btn = letter_fill_questions
  ② 绝不抢走选词填空：select_btn 是单词（parrot / notebook）时仍必须是 select_fill_questions
  ③ 解析：首字母只取"空位左侧的纯字母 question_title_tv"；被 flexbox 拆散的
     「[通过，凭借（做某事）]」能拼回整句
  ④ 推断：有中文提示走 HINT 模板；无提示（听录音）走 POOL 模板并标低置信度
  ⑤ handler：点字母自动填空位 → 点检查；长度/字母池不符时**不瞎答**（返回 False）
  ⑥ 收集：写进脚本的是 题干(+提示) + 字母块 + 正确答案
"""
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from question_types import (  # noqa: E402
    _has_letter_tiles, detect_question_type, parse_letter_fill,
)
import engine  # noqa: E402


# ══════════════════════════════════════════════════════════════════
# 页面 fixture（结构照抄真机 dump：tmp_gen/letter_fill_q14.xml / _q15.xml）
# ══════════════════════════════════════════════════════════════════
def _node(text, rid, cls="android.widget.TextView", bounds="[0,0][10,10]"):
    return (f'<node index="0" text="{text}" resource-id="com.dinoenglish.yyb:id/{rid}" '
            f'class="{cls}" package="com.dinoenglish.yyb" clickable="false" '
            f'bounds="{bounds}"></node>')


def letter_fill_xml(prefix="b", n_slot=1, tiles="b l c n t j y e s z",
                    hint="通过，凭借（做某事）", cap="根据中文提示，选择正确的字母补全单词。 (共1分)",
                    filled="", check=False, with_select_tv=True):
    """拼一个「字母块补全单词」页 xml（filled 按位铺进各空位）"""
    parts = [_node(cap, "tv_caption", bounds="[60,445][1041,507]")]
    # 首字母（每个字母一个 question_title_tv，位于空位左侧）
    x = 58
    for ch in prefix:
        parts.append(_node(ch, "question_title_tv", bounds=f"[{x},704][{x+22},776]"))
        x += 24
    # 空位
    if with_select_tv:
        sx = x + 12
        for i in range(n_slot):
            t = filled[i] if i < len(filled) else ""
            parts.append(_node(t, "select_tv", cls="android.widget.CheckBox",
                               bounds=f"[{sx},701][{sx+144},791]"))
            sx += 200
    # 中文提示（被 flexbox 按字宽拆成多片段，方括号也会单独成节点——真机 dump 实测）
    if hint:
        hx = 400
        for frag in ["\xa0\xa0["] + [hint[i:i + 3] for i in range(0, len(hint), 3)] + ["]"]:
            parts.append(_node(frag, "question_title_tv", bounds=f"[{hx},704][{hx+80},776]"))
            hx += 84
    # 字母块
    tx = 35
    for i, t in enumerate(tiles.split()):
        parts.append(_node(t, "select_btn",
                           bounds=f"[{tx + 40},{899 if i < 5 else 1056}]"
                                  f"[{tx + 153},{1008 if i < 5 else 1165}]"))
        tx += 204
        if i == 4:
            tx = 35
    if check:
        parts.append(_node("检查", "btn_check", bounds="[800,2100][980,2230]"))
    return "<hierarchy>" + "".join(parts) + "</hierarchy>"


def word_fill_xml():
    """真·选词填空页：空位 + **单词**词库（用于回归：不得被字母题抢走）"""
    parts = [_node("阅读短文，选词填空。", "tv_caption")]
    parts.append(_node("", "select_tv", cls="android.widget.CheckBox", bounds="[92,701][236,791]"))
    for i, t in enumerate(("parrot", "notebook", "hospital")):
        parts.append(_node(t, "select_btn", bounds=f"[{35 + i * 204},1600][{228 + i * 204},1730]"))
    return "<hierarchy>" + "".join(parts) + "</hierarchy>"


# ══════════════════════════════════════════════════════════════════
# 假设备（只实现 handler 用到的接口）
# ══════════════════════════════════════════════════════════════════
class _Elem:
    def __init__(self, d, name):
        self.d, self.name = d, name

    def exists(self, timeout=0):
        if self.name == "检查":
            return len(self.d.filled) >= self.d.n_slot and not self.d.checked
        if self.name == "下一题":
            return self.d.wrong
        return False

    def click(self):
        if self.name == "检查":
            self.d.checked = True
            self.d.clicks.append(("检查", None))
        else:
            self.d.clicks.append((self.name, None))


class FakeD:
    def __init__(self, prefix="b", n_slot=1, tiles="b l c n t j y e s z", hint="通过，凭借（做某事）"):
        self.prefix, self.n_slot, self.tiles, self.hint = prefix, n_slot, tiles, hint
        self.filled = ""
        self.checked = False
        self.wrong = False
        self.clicks = []

    def dump_hierarchy(self):
        self.check_visible = self.checked is False
        return letter_fill_xml(prefix=self.prefix, n_slot=self.n_slot, tiles=self.tiles,
                               hint=self.hint, filled=self.filled,
                               check=len(self.filled) >= self.n_slot and not self.checked)

    def _hit(self, t, x, y):
        m = re.search(r"bounds=\"\[(\d+),(\d+)\]\[(\d+),(\d+)\]\"",
                      letter_fill_xml(prefix=self.prefix, n_slot=self.n_slot, tiles=self.tiles,
                                      hint=self.hint, filled=self.filled))
        return m

    def click(self, x, y):
        """命中哪个字母块就把该字母填进下一个空位（真机实测：直接点字母就自动填）"""
        xml = letter_fill_xml(prefix=self.prefix, n_slot=self.n_slot, tiles=self.tiles,
                              hint=self.hint, filled=self.filled)
        for m in re.finditer(r"<node[^>]*select_btn[^>]*>", xml):
            tag = m.group(0)
            tm = re.search(r'text="([^"]*)"', tag)
            bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
            if not (tm and bm):
                continue
            x1, y1, x2, y2 = map(int, bm.groups())
            if x1 <= x <= x2 and y1 <= y <= y2:
                self.filled += tm.group(1)
                self.clicks.append(("字母" + tm.group(1), (x, y)))
                return True
        self.clicks.append(("其他", (x, y)))
        return True

    def text(self, t):
        return _Elem(self, t)

    def __call__(self, **kw):
        """uiautomator2 的 `d(text="检查")` 选择器调用形式（handler 大量使用）"""
        return _Elem(self, kw.get("text", ""))


# ══════════════════════════════════════════════════════════════════
# ① 题型检测
# ══════════════════════════════════════════════════════════════════
class TestDetect(unittest.TestCase):
    def test_字母池_识别为字母补全(self):
        self.assertTrue(_has_letter_tiles(letter_fill_xml()))
        self.assertEqual(detect_question_type(letter_fill_xml()), "letter_fill_questions")

    def test_听录音变体_也识别(self):
        xml = letter_fill_xml(cap="听录音，选择正确的字母补全单词。 (共1分)")
        self.assertEqual(detect_question_type(xml), "letter_fill_questions")

    def test_题干无关键词_纯DOM也能识别(self):
        """关键词为 None（刻意）：题干变体多，靠 select_tv+单字母结构判定"""
        xml = letter_fill_xml(cap="Read and write.")
        self.assertEqual(detect_question_type(xml), "letter_fill_questions")

    def test_回归_选词填空不得被抢走(self):
        """★ 最关键回归：select_btn 是单词 → 必须仍是 select_fill_questions"""
        self.assertFalse(_has_letter_tiles(word_fill_xml()))
        self.assertEqual(detect_question_type(word_fill_xml()), "select_fill_questions")

    def test_无空位_不算字母题(self):
        xml = letter_fill_xml(with_select_tv=False)
        self.assertFalse(_has_letter_tiles(xml))

    def test_只有一个字母块_不算字母题(self):
        self.assertFalse(_has_letter_tiles(letter_fill_xml(tiles="y")))


# ══════════════════════════════════════════════════════════════════
# ② 解析（首字母 / 空位 / 字母块 / 中文提示）
# ══════════════════════════════════════════════════════════════════
class TestParse(unittest.TestCase):
    def test_基本解析(self):
        info = parse_letter_fill(letter_fill_xml())
        self.assertEqual(info["prefix"], "b")
        self.assertEqual(len(info["slots"]), 1)
        self.assertEqual(len(info["tiles"]), 10)
        self.assertEqual(info["hint"], "通过，凭借（做某事）")
        self.assertIn("补全单词", info["cap"])

    def test_首字母多字母(self):
        info = parse_letter_fill(letter_fill_xml(prefix="nu", n_slot=1))
        self.assertEqual(info["prefix"], "nu")

    def test_中文提示不污染首字母(self):
        """提示片段挂在右侧且非 ASCII → 不得混进 prefix"""
        info = parse_letter_fill(letter_fill_xml(prefix="d", n_slot=2))
        self.assertEqual(info["prefix"], "d")

    def test_无提示_听录音型(self):
        info = parse_letter_fill(letter_fill_xml(hint=""))
        self.assertEqual(info["hint"], "")

    def test_空位状态(self):
        info = parse_letter_fill(letter_fill_xml(n_slot=2, filled="a"))
        self.assertEqual([s["text"] for s in info["slots"]], ["a", ""])


# ══════════════════════════════════════════════════════════════════
# ③ 单词推断（假 LLM）
# ══════════════════════════════════════════════════════════════════
class TestInfer(unittest.TestCase):
    def setUp(self):
        self.calls = []
        engine._letter_fill_ask_llm = self._fake
        self.reply = "by"

    def _fake(self, prompt):
        self.calls.append(prompt)
        return self.reply

    def test_有中文提示_走HINT模板(self):
        word, src = engine._letter_fill_word("b", "通过，凭借（做某事）",
                                             ["b", "l", "c", "y"], n_slot=1)
        self.assertEqual(word, "by")
        self.assertEqual(src, "中文提示")
        self.assertIn("通过，凭借（做某事）", self.calls[-1])
        self.assertIn("2 个字母", self.calls[-1])

    def test_无提示_走POOL模板并标低置信度(self):
        self.reply = "day"
        word, src = engine._letter_fill_word("d", "", ["d", "a", "y", "p"], n_slot=2)
        self.assertEqual(word, "day")
        self.assertIn("低置信度", src)
        self.assertIn("字母块", self.calls[-1])

    def test_LLM多余标点也能提取(self):
        self.reply = "by。"
        self.assertEqual(engine._letter_fill_word("b", "通过", ["y"], 1)[0], "by")

    def test_答非所问_返回空(self):
        self.reply = "无法确定"
        self.assertEqual(engine._letter_fill_word("b", "通过", ["y"], 1), ("", ""))

    def test_首字母不符_返回空(self):
        self._seq(["cat", "cat"])
        self.assertEqual(engine._letter_fill_word("b", "通过", ["y"], 1), ("", ""))

    def _seq(self, replies):
        """按序返回若干个 LLM 答复（每次调用都记进 self.calls）"""
        box = {"r": list(replies)}

        def _f(p):
            self.calls.append(p)
            return box["r"].pop(0) if box["r"] else ""

        engine._letter_fill_ask_llm = _f

    def test_字母池外字母_重问一次后成功(self):
        """★ 真机实测：LLM 会无视"只能用字母块里的字母"（prefix=d / 2 空位 / 池内无 g 却答 dog）
        → 必须带纠错提示重问一次，第二次合规才采用。"""
        self._seq(["dog", "day"])
        word, src = engine._letter_fill_word("d", "", ["n", "u", "o", "y", "a", "x"], n_slot=2)
        self.assertEqual(word, "day")
        self.assertEqual(len(self.calls), 2)
        self.assertIn("字母块里没有的字母", self.calls[1])

    def test_两次都不合规_返回空(self):
        self._seq(["dog", "dog"])       # 池里没有 g
        self.assertEqual(engine._letter_fill_word("d", "", ["a", "y"], n_slot=2), ("", ""))

    def test_长度不符_重问一次(self):
        self._seq(["baby", "by"])
        self.assertEqual(engine._letter_fill_word("b", "通过", ["y"], 1)[0], "by")
        self.assertIn("必须是正好 2 个字母", self.calls[1])


# ══════════════════════════════════════════════════════════════════
# ④ handler 端到端
# ══════════════════════════════════════════════════════════════════
class TestHandler(unittest.TestCase):
    def setUp(self):
        engine._letter_fill_ask_llm = lambda p: "by"
        engine._LAST_LETTER_FILL.clear()

    def _run(self, d, reply):
        engine._letter_fill_ask_llm = lambda p: reply
        return engine._handle_letter_fill(d, {})

    def test_单空位_点y后检查(self):
        d = FakeD()
        ok = self._run(d, "by")
        self.assertTrue(ok)
        self.assertIn("字母y", [c[0] for c in d.clicks])
        self.assertIn("检查", [c[0] for c in d.clicks])
        self.assertEqual(d.filled, "y")
        self.assertEqual(engine._LAST_LETTER_FILL.get("word"), "by")

    def test_多空位_依次点字母(self):
        d = FakeD(prefix="d", n_slot=2, tiles="d a y p o", hint="一天")
        ok = self._run(d, "day")
        self.assertTrue(ok)
        self.assertEqual(d.filled, "ay")
        self.assertEqual([c[0] for c in d.clicks if c[0].startswith("字母")],
                         ["字母a", "字母y"])

    def test_长度不符_不瞎答(self):
        d = FakeD()          # prefix b + 1 空位 = 2 字母
        self.assertFalse(self._run(d, "baby"))
        self.assertEqual(d.clicks, [])

    def test_所需字母不在池中_不瞎答(self):
        d = FakeD(tiles="b l c n t j e s z")   # 没有 y
        self.assertFalse(self._run(d, "by"))
        self.assertNotIn("检查", [c[0] for c in d.clicks])

    def test_听录音型_用池推断(self):
        d = FakeD(prefix="d", n_slot=2, tiles="d a y p o", hint="")
        ok = self._run(d, "day")
        self.assertTrue(ok)
        self.assertIn("低置信度", engine._LAST_LETTER_FILL.get("source", ""))

    def test_结构不完整_直接放弃(self):
        d = FakeD()
        d.dump_hierarchy = lambda: "<hierarchy></hierarchy>"
        self.assertFalse(self._run(d, "by"))


# ══════════════════════════════════════════════════════════════════
# ⑤ 脚本收集
# ══════════════════════════════════════════════════════════════════
class TestCollect(unittest.TestCase):
    class _Coll:
        def __init__(self):
            self.items = []

        def add(self, **kw):
            self.items.append(kw)

    def test_收集题干字母块与答案(self):
        from modules.单元自检 import _collect_letter_fill
        coll = self._Coll()
        engine._LAST_LETTER_FILL.clear()
        engine._LAST_LETTER_FILL.update({"word": "by", "prefix": "b",
                                         "hint": "通过，凭借（做某事）",
                                         "source": "中文提示",
                                         "cap": "根据中文提示，选择正确的字母补全单词。 (共1分)"})
        _collect_letter_fill(letter_fill_xml(), 14, coll, 1)
        self.assertEqual(len(coll.items), 1)
        it = coll.items[0]
        self.assertEqual(it["answer"], "by")
        self.assertEqual(it["qno"], 14)
        self.assertEqual(it["options"], "b l c n t j y e s z".split())
        self.assertIn("通过，凭借", it["stem"])
        self.assertIn("字母块补全单词", it["qtype"])

    def test_无推断结果_不收集(self):
        from modules.单元自检 import _collect_letter_fill
        coll = self._Coll()
        engine._LAST_LETTER_FILL.clear()
        _collect_letter_fill(letter_fill_xml(), 14, coll, 1)
        self.assertEqual(coll.items, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
