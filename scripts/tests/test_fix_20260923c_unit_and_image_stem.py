"""★ 2026-09-23 修复回归测试（用户四条反馈中的 ①③④）

① 六维头部统计：前端补「AI未审」，去掉重复的三态行
③ 脚本比对单元错位：连跑 U5-6 时 U6 的题全部拿 U5 脚本比对 → 整片假错
    - logger 当前单元上报 set_current_unit/get_current_unit
    - web_server._realign_script_unit 跨单元纠偏
    - _text_same_strict/_text_diff_minor/_text_like 剥「句型提示：/例句：」标签
④ 图片题题面：脚本有内容就用脚本（句型提示），**绝不使用参考答案**
    - 口语训练._script_ref_stem 只返回 stem/sentence_pattern
    - _find_active_sub_question 图片题优先脚本，不再让视觉模型猜出答案

运行：python scripts/tests/test_fix_20260923c_unit_and_image_stem.py
"""
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

PASS = 0
FAIL = []


def chk(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {extra}")


# ─────────────────────────── ① 前端 ───────────────────────────
print("== ① 六维头部统计（前端） ==")
_html = io.open(os.path.join(ROOT, "templates", "index.html"), encoding="utf-8").read()
chk("统计条有 AI未审 (sUnrev)", 'id="sUnrev"' in _html)
chk("updQ 写入 sUnrev", '$("sUnrev").textContent = nOpt' in _html)
chk("不再重复渲染三态总览行", "review-overview-title" not in _html.split("const overviewHtml")[1][:400])
chk("增量渲染 _qlZone 存在", "function _qlZone(" in _html)
chk("keyed diff _qlRenderCards 存在", "function _qlRenderCards(" in _html)
chk("交互锁 _qlLockUntil 存在", "_qlLockUntil" in _html)
chk("open 走元素属性（非 HTML 串）", "if (it.open !== undefined && el.open !== it.open)" in _html)

# ─────────────────────────── ③ logger 单元上报 ───────────────────────────
print("== ③ logger 当前单元上报 ==")
from common.logger import (          # noqa: E402
    set_current_unit, get_current_unit,
    set_module_scripts, get_module_script,
)
set_current_unit(7)
chk("set_current_unit(7)", get_current_unit() == 7)
set_current_unit("7")
chk('set_current_unit("7")', get_current_unit() == 7)
set_current_unit("5-6")
chk('set_current_unit("5-6") 容错取首段', get_current_unit() == 5)
set_current_unit(None)
chk("set_current_unit(None) → 0", get_current_unit() == 0)
set_module_scripts({"口语训练": "a.docx"})
chk("get_module_script", get_module_script("口语训练") == "a.docx")
chk("get_module_script 未挂载 → ''", get_module_script("听力专项") == "")

# ─────────────────────────── ③ web_server 比对工具 ───────────────────────────
print("== ③ web_server 标签剥离 / 跨单元纠偏 ==")
import web_server as W                  # noqa: E402

chk('剥「句型提示：」', W._strip_prompt_label("句型提示：Hello, this is ...") == "Hello, this is ...")
chk('剥「例句：」', W._strip_prompt_label("例句：I will make ...") == "I will make ...")
chk('多重标签也剥', W._strip_prompt_label("例句：句型提示：X") == "X")
chk('无标签原样', W._strip_prompt_label("The quick queen is quite quiet.") == "The quick queen is quite quiet.")

# 真实假错现场：App 是「句型提示：Hello, this is ...」，脚本 stem 是「Hello, this is ...」
chk("严格比对容忍标签",
    W._text_same_strict("句型提示：Hello, this is ...", "Hello, this is ..."))
chk("宽松比对容忍标签",
    W._text_like("句型提示：Hello, this is ...", "Hello, this is ..."))
chk("格式差异比对容忍标签",
    W._text_diff_minor("句型提示：Hello, this is ...", "Hello, this is ..."))
chk("实质差异仍判不同",
    not W._text_same_strict("句型提示：Hello, this is Lucas.", "Hello, this is ..."))


class _Q:
    def __init__(self, unit, big, idx, stem="", pat="", cap=""):
        self.unit, self.big, self.stage_idx = unit, big, idx
        self.stem, self.sentence_pattern, self.caption = stem, pat, cap


# 现场复刻：state.unit="5-6" → 旧逻辑固定 U5，U6 的题被 U5 同号题命中
u5q3 = _Q(5, 2, 3, stem="Sit in the sun and have fun.")
u6q3 = _Q(6, 2, 3, stem="You'll see the moon and the stars.")
sq_list = [u5q3, u6q3]
got = W._realign_script_unit(sq_list, u5q3, 5, 2, 3, "You'll see the moon and the stars.")
chk("跨单元纠偏 → 命中 U6", got is u6q3, f"got unit={getattr(got, 'unit', None)}")
got2 = W._realign_script_unit(sq_list, u5q3, 5, 2, 3, "Sit in the sun and have fun.")
chk("本来就对 → 原样返回", got2 is u5q3)
got3 = W._realign_script_unit(sq_list, u5q3, 5, 2, 3, "完全不相干的一句")
chk("哪个单元都对不上 → 原样返回（不妄改）", got3 is u5q3)
# 两个单元都有同样的题 → 有歧义不纠正
dup = [_Q(5, 2, 1, stem="Same sentence."), _Q(6, 2, 1, stem="Same sentence.")]
got4 = W._realign_script_unit(dup, _Q(7, 2, 1, stem="x"), 7, 2, 1, "Same sentence.")
chk("多单元同题 → 不纠正", getattr(got4, "unit", None) == 7, f"got {getattr(got4, 'unit', None)}")

# ─────────────────────────── ④ 图片题题面 ───────────────────────────
print("== ④ 图片题脚本优先（不得出现参考答案） ==")
import importlib                       # noqa: E402
oral = importlib.import_module("modules.口语训练")

DOCX = "260727口语训练新教科五上U4-7（已二校）.docx"
_HAS_DOCX = os.path.exists(os.path.join(ROOT, "uploads", DOCX))
if not _HAS_DOCX:
    print("  [SKIP] uploads 里没有该脚本，跳过真实脚本断言")
else:
    oral._ORAL_SCRIPT_CACHE.clear()
    set_module_scripts({"口语训练": DOCX})
    set_current_unit(5)
    r = oral._script_ref_stem(3, 3)     # U5 第3大题第3小题
    chk("U5 第3大题第3小题取到句型", r == "Hello, this is ...", f"got {r!r}")
    chk("★ 绝不返回参考答案 Lucas", "Lucas" not in r, f"got {r!r}")
    r1 = oral._script_ref_stem(3, 1)
    chk("U5 第3大题第1小题", r1 == "It will be ... degree(s) on Friday.", f"got {r1!r}")
    set_current_unit(6)
    r6 = oral._script_ref_stem(3, 1)    # U6 该小题 stem 为空 → 回退 sentence_pattern
    chk("U6 stem 空 → 回退句型提示", r6 == "I will talk to astronauts.", f"got {r6!r}")
    chk("U6 不回退到参考答案", "sunrise" not in r6, f"got {r6!r}")
    set_module_scripts({})
    oral._ORAL_SCRIPT_CACHE.clear()

# 纯 XML 走一遍 _find_active_sub_question：脚本有内容时必须用脚本、不调视觉
XML = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy rotation="0">
 <node resource-id="com.dinoenglish.yyb:id/ll_container" bounds="[0,800][1080,1600]">
  <node resource-id="com.dinoenglish.yyb:id/tv_sort" text="3/5" bounds="[40,820][120,860]" />
  <node text="3. 句型提示：Hello, this is ..." bounds="[40,880][1040,930]" />
  <node resource-id="com.dinoenglish.yyb:id/pic_iv" bounds="[203,950][877,1450]" />
  <node resource-id="com.dinoenglish.yyb:id/record_btn" clickable="true" bounds="[470,1500][610,1600]" />
 </node>
</hierarchy>"""

_orig_ref = oral._script_ref_stem
oral._script_ref_stem = lambda big, sub: "Hello, this is ..."
try:
    sn, tot, stem, _box = oral._find_active_sub_question(None, xml=XML, big=3)
    chk("定位到第3小题", sn == 3, f"got {sn}")
    chk("图片题题面来自脚本句型", "Hello, this is ..." in stem, f"got {stem!r}")
    chk("★ 题面不含参考答案 Lucas（未调视觉）", "Lucas" not in stem, f"got {stem!r}")
    chk("src 标为 text（App 有句型提示→照常判定）", oral._LAST_STEM_SRC == "text",
        f"got {oral._LAST_STEM_SRC}")
finally:
    oral._script_ref_stem = _orig_ref

# 脚本没挂载 → 回退原逻辑（此 XML 有句型提示，应标 text 且不报错）
set_module_scripts({})
oral._ORAL_SCRIPT_CACHE.clear()
XML2 = XML.replace('text="3. 句型提示：Hello, this is ..."', 'text="3. Hello, this is ..."')
sn2, _, stem2, _ = oral._find_active_sub_question(None, xml=XML2, big=3)
chk("无脚本时不崩（回退原路径）", bool(stem2), f"got {stem2!r}")

print(f"\n通过 {PASS} / 失败 {len(FAIL)}")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("✅ 全部通过")
