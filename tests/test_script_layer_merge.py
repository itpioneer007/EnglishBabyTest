# -*- coding: utf-8 -*-
"""★ 审查体系改造（边跑边审 → 单记录双层）单元验证（不连手机）

验证链路：
  1. _qreview_to_state 产出 script 子结构 + layer 标记
  2. _match_basic_qid 正确把脚本题定位到对应基础层记录
  3. 合并后基础记录 = 单条记录同时含基础层(UI证据) + 脚本层(对照docx)
  4. 索引复用路径把缓存脚本层合并进 fresh 基础记录
"""
import sys
import types
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/.." + "/src")

import web_server as W  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  —— {detail}" if detail and not cond else ""))


def mk_check(passed, method, details=None, actual=""):
    return types.SimpleNamespace(passed=passed, method=method,
                                 score=1.0 if passed else 0.0,
                                 details=list(details or []), actual=actual)


def mk_review(idx=1, qtype="选择题", stem_pass=True, content_pass=True,
              answer_pass=True, stem_actual="看图选单词"):
    """构造 QuestionReview 的轻量 mock（字段与 review_agent 一致）"""
    r = types.SimpleNamespace()
    r.idx = idx
    r.question_type = qtype
    r.script_answer = "A"
    r.stem_check = mk_check(stem_pass, "text" if stem_pass else "llm",
                            ["题干与脚本一致"], stem_actual)
    r.content_check = mk_check(content_pass, "text" if content_pass else "llm",
                               ["选项齐全"])
    r.image_check = mk_check(False, "skip", ["配图需连手机截图核对"])     # 无截图 → 未检
    r.answer_check = mk_check(answer_pass, "text" if answer_pass else "llm",
                              ["答案在选项范围内"])
    r.audio_check = mk_check(False, "skip", ["音频需连手机截图核对"])
    r.post_error_check = mk_check(False, "skip", ["答错后需连手机截图核对"])
    r.knowledge_check = {"passed": True, "detail": "知识点在教材范围内"}
    r.overall_passed = stem_pass and content_pass and answer_pass
    r.overall_score = 1.0 if r.overall_passed else 0.5
    return r


def fake_q(**kw):
    q = types.SimpleNamespace(unit=kw.get("unit", 3), big=kw.get("big", 0),
                              stage_idx=kw.get("stage_idx", 0),
                              global_idx=kw.get("global_idx", 5),
                              stage=kw.get("stage", ""))
    return q


print("== 1) _qreview_to_state → script 子结构 ==")
r1 = mk_review()
s1 = W._qreview_to_state("口语训练", "x.docx", 3, r1, stage="", q=fake_q(big=2, stage_idx=3))
check("layer=script_only（独立脚本记录）", s1.get("layer") == "script_only", str(s1.get("layer")))
check("script 子结构存在且 status=done", isinstance(s1.get("script"), dict) and s1["script"].get("status") == "done")
check("script 六维中题干通过", s1["script"].get("stem") is True)
check("script 六维中配图未检(None)", s1["script"].get("image") is None)
check("script.knowledge=True", s1["script"].get("knowledge") is True)
check("script.overall_passed=True", s1["script"].get("overall_passed") is True)
check("script.reason 含'通过'", "通过" in (s1["script"].get("reason") or ""), s1["script"].get("reason"))
check("position=U3·第2大题·第3小题", s1.get("position") == "U3·第2大题·第3小题", s1.get("position"))

print("== 2) 有维度不通过 → 脚本层不通过 ==")
r2 = mk_review(answer_pass=False)
s2 = W._qreview_to_state("口语训练", "x.docx", 3, r2, stage="", q=fake_q())
check("script.answer=False", s2["script"].get("answer") is False)
check("script.overall_passed=False", s2["script"].get("overall_passed") is False)
check("script.reason 含'不通过'", "不通过" in (s2["script"].get("reason") or ""), s2["script"].get("reason"))

print("== 3) _match_basic_qid 定位基础层记录 ==")
W._inspection_state = {"questions": {
    "auto-Q01-03": {"module": "口语训练", "stage": "", "idx": 3},
    "auto-Q005": {"module": "听力专项", "stage": "基础巩固", "idx": 5},
    "auto-Q008": {"module": "口语训练", "stage": "", "idx": 8},
}}
# 口语训练结构 (big, stage_idx)
m1 = W._match_basic_qid("口语训练", fake_q(big=1, stage_idx=3), r1, "")
check("口语训练 (big=1,stage_idx=3) → auto-Q01-03", m1 == "auto-Q01-03", m1)
# 非 big 模块（听力专项）：脚本 idx 定位
rr_idx5 = mk_review(idx=5, qtype="听力")
m2 = W._match_basic_qid("听力专项", fake_q(), rr_idx5, "基础巩固")
check("听力专项 idx=5 → auto-Q005", m2 == "auto-Q005", m2)
# stage 不匹配 → 不合并
m3 = W._match_basic_qid("听力专项", fake_q(), rr_idx5, "测试")
check("听力专项 stage 不匹配 → 不合并", m3 == "", m3)
# 模块不匹配 → 不合并
rr_idx8 = mk_review(idx=8)
m4 = W._match_basic_qid("听力专项", fake_q(), rr_idx8, "")
check("模块不匹配 → 不合并", m4 == "", m4)
# 找不到 → ""
m5 = W._match_basic_qid("口语训练", fake_q(big=9, stage_idx=9), r1, "")
check("无匹配基础记录 → ''（保留独立脚本记录）", m5 == "", m5)

print("== 4) 合并逻辑（模拟 _run_llm_script_review 循环） ==")
# 重新构造：基础层记录（由 _record_module_evidence 产生，脚本层 pending）
W._inspection_state = {"questions": {
    "auto-Q02-04": {"idx": 4, "module": "口语训练", "stage": "",
                    "layer": "basic+script",
                    "script": {"matched": True, "status": "pending"},
                    "note": "", "overall_passed": True},
    "auto-Q010": {"idx": 10, "module": "听力专项", "stage": "基础巩固",
                  "layer": "basic_only", "script": None,
                  "note": "", "overall_passed": True},
}}
# 合并口语训练 U3 第2大题第4小题
_qq = fake_q(big=2, stage_idx=4)
_rr = mk_review(idx=4, qtype="朗读")
_st = W._qreview_to_state("口语训练", "yyb.docx", 3, _rr, stage="", q=_qq)
_m = W._match_basic_qid("口语训练", _qq, _rr, "")
assert _m == "auto-Q02-04"
_base = W._inspection_state["questions"][_m]
_base["script"] = _st["script"]
_base["layer"] = "basic+script"
_base["note"] = (_base.get("note") or "") + f"；脚本核验·yyb.docx"
check("合并后 layer=basic+script", _base["layer"] == "basic+script")
check("合并后 script.status=done", _base["script"].get("status") == "done")
check("合并后基础层 overall 保留 True", _base.get("overall_passed") is True)
check("合并后仍是同一记录(无独立脚本key)", "口语训练-脚本-Q04" not in W._inspection_state["questions"])
# 未出现的脚本题 → 独立脚本记录
_unmatched_q = fake_q(big=5, stage_idx=1)
_unmatched_r = mk_review(idx=99, qtype="朗读")
_m2_ = W._match_basic_qid("口语训练", _unmatched_q, _unmatched_r, "")
check("未出现的脚本小题不合并", _m2_ == "", _m2_)

print("== 5) 索引复用：缓存脚本层合并进 fresh 基础记录（模拟） ==")
W._inspection_state = {"questions": {
    "auto-Q02-04": {"idx": 4, "module": "口语训练", "stage": "",
                    "layer": "basic+script",
                    "script": {"matched": True, "status": "pending"},
                    "note": "", "overall_passed": False},   # fresh：本轮新的 UI 证据
}}
_cached_qs = {
    "auto-Q02-04": {"idx": 4, "module": "口语训练", "stage": "",
                    "layer": "basic+script",
                    "script": {"matched": True, "status": "done", "stem": True,
                               "answer": True, "overall_passed": True,
                               "reason": "脚本核验通过（2/2 维）"},
                    "note": "脚本核验·yyb.docx", "overall_passed": True},
    "口语训练-脚本-Q99": {"idx": 99, "layer": "script_only",
                          "script": {"matched": True, "status": "done"}},
}
_merged_cache = 0
for _k, _v in _cached_qs.items():
    _cur = W._inspection_state["questions"].get(_k)
    if _cur is not None and isinstance(_v, dict) \
            and isinstance(_v.get("script"), dict) and _k.startswith("auto-"):
        _cur["script"] = _v["script"]
        _cur["layer"] = "basic+script"
        if _v.get("note"):
            _cur["note"] = _v["note"]
        _merged_cache += 1
    else:
        W._inspection_state["questions"][_k] = _v
_merged_rec = W._inspection_state["questions"]["auto-Q02-04"]
check("复用：fresh 基础记录 UI 证据保留(overall_passed=False 本轮证据)",
      _merged_rec.get("overall_passed") is False)
check("复用：脚本层回填 done", _merged_rec["script"].get("status") == "done")
check("复用：脚本层通过", _merged_rec["script"].get("overall_passed") is True)
check("复用：独立脚本记录恢复", "口语训练-脚本-Q99" in W._inspection_state["questions"])
check("复用计数=1", _merged_cache == 1, str(_merged_cache))

print()
print(f"===== 结果: {len(PASS)} 通过 / {len(FAIL)} 失败 =====")
if FAIL:
    print("失败项:", FAIL)
    sys.exit(1)
print("ALL PASS ✅")
