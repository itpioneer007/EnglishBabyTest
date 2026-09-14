# -*- coding: utf-8 -*-
"""口语训练 · "结合句型"图片题：句型模板提取与传递链路测试。

覆盖：
  A 组  _extract_sentence_pattern 正例（真机 dump 原文）
  B 组  负例（不得误吞普通题干/说明文字）
  C 组  用真机 big3.xml 跑 _find_active_sub_question，断言句型被传进视觉识别
  D 组  缓存键含句型（不同句型不串味）
"""
import io
import os
import sys
import importlib

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

M = importlib.import_module("modules.口语训练")

_ok = 0
_fail = 0


def check(label, got, want):
    global _ok, _fail
    if got == want:
        _ok += 1
        print(f"  ✅ {label}")
    else:
        _fail += 1
        print(f"  ❌ {label}\n       got ={got!r}\n       want={want!r}")


def check_true(label, cond, extra=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✅ {label}")
    else:
        _fail += 1
        print(f"  ❌ {label}  {extra}")


print("=" * 68)
print("A 组：句型模板提取（正例，取自真机 big3.xml）")
print("=" * 68)
_A = [
    ("1.例句：I travelled to ...&#10;(2分)", "I travelled to ..."),
    ("2.例句：I did ...&#10;(2分)", "I did ..."),
    ("3.例句：I visited my ...&#10;(2分)", "I visited my ..."),
    ("句型提示：Which one do you want, ...?", "Which one do you want, ...?"),
    ("参考句型：I went to the park.", "I went to the park."),
    ("1. 例句: I travelled to Beijing. (2分)", "I travelled to Beijing."),
    ("例句：I am going to ...&#10;（2分）", "I am going to ..."),
]
for src, want in _A:
    check(repr(src)[:52], M._extract_sentence_pattern(src), want)

print()
print("=" * 68)
print("B 组：负例（不得误吞）")
print("=" * 68)
_B = [
    ("(2分)", ""),
    ("请结合句型和图片说句子，点击“录音”开始作答。每小题有10秒钟的准备时间，15秒钟的作答时间。", ""),
    ("听词汇，判断图片与词汇是否相符", ""),
    ("1/5", ""),
    ("已作答", ""),
    ("", ""),
    ("单词：apple banana", ""),
]
for src, want in _B:
    check(repr(src)[:50], M._extract_sentence_pattern(src), want)

print()
print("=" * 68)
print("C 组：真机 dump 端到端（stub 视觉，验证句型被传下去）")
print("=" * 68)
_xml_path = os.path.join(_ROOT, "screenshots", "oral_probe", "big3.xml")
if not os.path.exists(_xml_path):
    print(f"  ⚠ 缺少真机 dump（{_xml_path}），跳过 C/D 组")
else:
    xml = open(_xml_path, encoding="utf-8").read()
    calls = []

    def _stub(d, pic_box, sub_no, pattern=""):
        calls.append({"pic_box": pic_box, "sub_no": sub_no, "pattern": pattern})
        return f"[stub图片句 pattern={pattern}]"

    _orig = M._oral_vision_stem
    M._oral_vision_stem = _stub
    try:
        sub_no, total_sub, stem, active = M._find_active_sub_question(None, xml)
    finally:
        M._oral_vision_stem = _orig

    print(f"  解析结果: sub_no={sub_no} stem={stem!r}")
    print(f"  容器bounds={active}")
    check("小题号取自 '1.例句'", sub_no, 1)
    check_true("视觉识别被调用", len(calls) == 1, f"calls={calls}")
    if calls:
        c = calls[0]
        check("传入句型 = I travelled to ...", c["pattern"], "I travelled to ...")
        check("传入图片框（真机 pic_iv）", c["pic_box"], (203, 1152, 877, 1512))
    check_true("题干来自视觉识别（而非例句原文）", "stub图片句" in stem, stem)
    check_true("题干不再含 '(2分)'", "分" not in stem, stem)

    print()
    print("=" * 68)
    print("D 组：无配图时不吞句型（保持原题干逻辑）")
    print("=" * 68)
    # 造一个"只有句型提示文字、无 pic_iv"的容器
    _xml_noimg = xml.replace('resource-id="com.dinoenglish.yyb:id/pic_iv"',
                             'resource-id="com.dinoenglish.yyb:id/not_pic"')
    calls.clear()
    M._oral_vision_stem = _stub
    try:
        sub_no2, _, stem2, _ = M._find_active_sub_question(None, _xml_noimg)
    finally:
        M._oral_vision_stem = _orig
    print(f"  无图解析: sub_no={sub_no2} stem={stem2!r}")
    check_true("无图时不调用视觉", len(calls) == 0, f"calls={calls}")
    check("无图时保留句型作为题干（不被 '(2分)' 吞掉）", stem2, "I travelled to ...")

# E 组：纯图片题（无 speech_content）→ pattern 为空，走原"描述图片"路径
print()
print("=" * 68)
print("E 组：纯图片题（无句型文本）→ pattern 为空字符串")
print("=" * 68)
check("无关键词文本返回空", M._extract_sentence_pattern("1.看图说话&#10;(2分)"), "")

# ------------------------------------------------------------------
print()
print("=" * 68)
print("F 组：缓存键=图片内容指纹（页面滚动改坐标不得重复调用 LLM）")
print("=" * 68)
try:
    from PIL import Image, ImageDraw
    import src.reviewer_common as RC

    # 造“可平移的屏幕”：shot2 = shot1 内容上移 300px
    _G = Image.new("RGB", (1080, 2400), "white")
    _dr = ImageDraw.Draw(_G)
    _dr.rectangle([300, 1100, 700, 1500], fill="green")
    _dr.text((320, 1150), "RICE", fill="black")
    shot1 = _G
    shot2 = Image.new("RGB", (1080, 2400), "white")
    shot2.paste(_G.crop((0, 300, 1080, 2400)), (0, 0))

    class _FakeDev:
        def __init__(self, imgs):
            self._imgs = imgs
            self.n = 0

        def screenshot(self, path=None):
            im = self._imgs[min(self.n, len(self._imgs) - 1)]
            self.n += 1
            return im

        def window_size(self):
            return (1080, 2400)

    _llm_calls = []

    class _FakeLLM:
        @staticmethod
        def from_config():
            return _FakeLLM()

        def ask(self, prompt, image_path=None, image_paths=None, temperature=None):
            _llm_calls.append(prompt)
            assert temperature == 0, f"口语看图补全必须固定温度，实际 {temperature!r}"
            if "I did ..." in prompt:
                return "I did plant rice."
            return "I planted rice."

    _orig_llm = RC.LLMClient
    RC.LLMClient = _FakeLLM
    M._ORAL_VISION_CACHE.clear()
    try:
        dev = _FakeDev([shot1, shot2])
        b1 = (300, 1100, 700, 1500)     # shot1 中图案所在
        b2 = (300, 800, 700, 1200)      # shot2 中同一图案（内容上移 300）
        r1 = M._oral_vision_stem(dev, b1, 2, pattern="I did ...")
        n1 = len(_llm_calls)
        r2 = M._oral_vision_stem(dev, b2, 2, pattern="I did ...")
        n2 = len(_llm_calls)
        print(f"  第1次 box={b1} → {r1!r}  (LLM 调用累计 {n1})")
        print(f"  第2次 box={b2} → {r2!r}  (LLM 调用累计 {n2})")
        check_true("确实拿到句型补全结果（非回退）", r1.startswith("I did "), r1)
        check("两次裁剪内容相同 → 结果一致", r1, r2)
        check("第2次未新增 LLM 调用（指纹缓存命中）", n2, n1)
        check("第1次确实调用了 LLM", n1, 1)
        # 反向：不同图片内容 → 必须重新识别
        dev2 = _FakeDev([shot1])
        _llm_calls.clear()
        M._ORAL_VISION_CACHE.clear()
        M._oral_vision_stem(dev2, (300, 100, 700, 500), 3, pattern="I did ...")   # 空白区
        M._oral_vision_stem(dev2, b1, 3, pattern="I did ...")                    # 图案区
        check("内容不同 → 各调用一次 LLM", len(_llm_calls), 2)
        # 反向：句型不同 → 不得复用
        M._ORAL_VISION_CACHE.clear()
        _llm_calls.clear()
        M._oral_vision_stem(dev2, b1, 4, pattern="I did ...")
        M._oral_vision_stem(dev2, b1, 4, pattern="I visited my ...")
        check("句型不同 → 不复用缓存", len(_llm_calls), 2)
    finally:
        RC.LLMClient = _orig_llm
        M._ORAL_VISION_CACHE.clear()
except ImportError as e:
    print(f"  ⚠ 缺少 PIL/依赖，跳过 F 组：{e}")

print()
print("=" * 68)
print(f"结果：{_ok} 通过 / {_fail} 失败")
print("=" * 68)
sys.exit(1 if _fail else 0)
