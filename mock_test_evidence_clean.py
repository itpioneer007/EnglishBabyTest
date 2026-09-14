# -*- coding: utf-8 -*-
"""Mock 验证：题干污染清洗（审查结果里用户实际看到的三类污染）

背景（真机 dump 实测，六上巧记单词 boss 关）：
  1. HTML 实体未解码 → 题干 '请眺望一下远方，活动活动身体,&#10;休息好了再回来！'
  2. 关卡进度残留   → 题干 '听录音，选择与录音内容相符的释义。 / 第6关  5/25'
  3. 休息提示页被当成一道"题" → 虚增题数、产生假错题

验证：
  A. clean_stem_text 的清洗规则（实体解码 / 关卡进度剥离 / 幂等）
  B. collect_ui_evidence 真实提取 → 题干字段不含进度噪音
  C. 休息提示页 → 题干维度为空（不被当题目内容）
不需要连真机。
"""
import sys
import os

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "scripts"))

from common.evidence import clean_stem_text, collect_ui_evidence  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  ({detail})" if detail else ""))


def _stems(ev):
    return [e.get("actual", "") for e in ev if e.get("field") == "题干"]


print("=" * 70)
print("测试组 A · clean_stem_text 清洗规则")
print("=" * 70)

check("HTML 实体 &#10; 被解码（不再是字面量）",
      "&#10;" not in clean_stem_text("第一行,&#10;第二行"),
      repr(clean_stem_text("第一行,&#10;第二行")))
check("尾缀『第6关 5/25』被剥离",
      clean_stem_text("听录音，选择与录音内容相符的释义。 / 第6关  5/25")
      == "听录音，选择与录音内容相符的释义。")
check("尾缀『5/25』被剥离",
      clean_stem_text("根据中文提示补全单词。 12/25") == "根据中文提示补全单词。")
check("前缀『5/25 』被剥离",
      clean_stem_text("5/25 听录音，跟读单词。") == "听录音，跟读单词。")
check("前缀『第6关 』被剥离",
      clean_stem_text("第6关 听录音，跟读单词。") == "听录音，跟读单词。")
check("全角斜杠 ／ 同样生效",
      clean_stem_text("听录音。／第6关 5／25") == "听录音。")
check("★ 干净题干不被误改（幂等）",
      clean_stem_text("听录音，跟读词组。") == "听录音，跟读词组。")
check("★ 清洗幂等（重复清洗结果不变）",
      clean_stem_text(clean_stem_text("听录音。 / 第6关  5/25")) == "听录音。")
check("方向控制符 U+200E 被去掉",
      clean_stem_text("Unit 1\u200e") == "Unit 1")
check("空输入安全", clean_stem_text("") == "" and clean_stem_text(None) == "")
check("含数字的正常题干不被误剥（例：Unit 1）",
      clean_stem_text("Unit 1 What does she look like?") == "Unit 1 What does she look like?")


print()
print("=" * 70)
print("测试组 B · collect_ui_evidence 真实提取（题干不得含进度噪音）")
print("=" * 70)

# 复刻真机 boss 关答题页：题干与"第6关 5/25"在同一 TextView
_ANSWER_XML = (
    '<hierarchy>'
    '<node text="第6关  5/25"/>'
    '<node text="听录音，选择与录音内容相符的释义。 / 第6关  5/25"/>'
    '<node text="A. 新的"/><node text="B. 旧的"/>'
    '<node text="检查"/>'
    '</hierarchy>'
)
_ev = collect_ui_evidence(_ANSWER_XML, qtype="巧记单词")
_st = _stems(_ev)
print(f"   提取到的题干: {_st}")
check("提取到题干", bool(_st))
check("★题干已剥离『第6关  5/25』进度段",
      all("第6关" not in s for s in _st), str(_st))
check("题干保留正文内容",
      any("听录音" in s for s in _st), str(_st))


print()
print("=" * 70)
print("测试组 C · 休息提示页不得被当成题目内容")
print("=" * 70)

# 真机 boss 关中途弹出的护眼提示页（原样，含 &#10; 实体）
_BREAK_XML = (
    '<hierarchy>'
    '<node text="请眺望一下远方，活动活动身体,&#10;休息好了再回来！"/>'
    '<node text="我知道了"/>'
    '</hierarchy>'
)
_ev2 = collect_ui_evidence(_BREAK_XML, qtype="巧记单词")
_st2 = _stems(_ev2)
print(f"   提取到的题干: {_st2}")
# 无题干时函数会给出 '(无题干文字)' 占位符 —— 关键是**不得出现休息页正文**
_real2 = [s for s in _st2 if s and s != "(无题干文字)"]
check("★休息提示页不被当作题干（噪音词已过滤）", not _real2, str(_real2))
check("休息页正文关键词未进题干",
      all("眺望" not in s and "活动活动身体" not in s for s in _st2), str(_st2))

print()
print("=" * 70)
print("测试组 D · 反馈页解析文本不得混进题干（已有『扬声器』维度承载）")
print("=" * 70)

# 真机现象：答错后反馈页的 "听力内容：always" 与题干一起被提取 →
#   '听录音，选择与录音内容相符的释义。 / 听力内容：always'
_FB_XML = (
    '<hierarchy>'
    '<node text="第6关  5/25"/>'
    '<node text="听录音，选择与录音内容相符的释义。"/>'
    '<node text="听力内容：always"/>'
    '<node text="重新答题"/>'
    '</hierarchy>'
)
_ev3 = collect_ui_evidence(_FB_XML, qtype="巧记单词")
_st3 = _stems(_ev3)
print(f"   提取到的题干: {_st3}")
check("★题干不含『听力内容：xxx』杂质",
      all("听力内容" not in s for s in _st3), str(_st3))
check("题干仍保留题目指令正文", any("听录音" in s for s in _st3), str(_st3))
check("★题干不含关卡进度（与上面同时生效）",
      all("第6关" not in s for s in _st3), str(_st3))

# 模块侧的关键词需与 evidence 侧一致（两处都要拦，才算真正跳过计题）
import re as _re  # noqa: E402
_qiaoji_src = open(os.path.join(_here, "scripts", "modules", "巧记单词.py"),
                   encoding="utf-8").read()
check("★巧记单词模块也做休息页识别（不虚增题数）",
      "_is_break_page" in _qiaoji_src and "休息好了再回来" in _qiaoji_src)
check("休息页判定覆盖关键词组",
      all(k in _qiaoji_src for k in ("眺望", "活动活动身体", "做眼保健操", "保护视力")))


print()
print("=" * 70)
print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败用例:")
    for f in FAIL:
        print("   -", f)
print("=" * 70)
sys.exit(1 if FAIL else 0)
