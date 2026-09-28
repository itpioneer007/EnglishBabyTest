# -*- coding: utf-8 -*-
"""口语训练「20题只留下4题」持久化链路 mock 复现 / 回归测试。

不连设备、不调 LLM，只验证「一道题能不能进审查结果」这条链：

  口语训练.step_log(msg, evidence)          ← 模块侧发出每题证据
      ↓  common/logger.step_log             ← 旧 bug：`if evidence:` 把 [] 当"没传"
      ↓  web_server.log_msg(msg, ev)        ← 旧 bug①：`if evidence and ...` 同样吞掉 []
                                            ← 旧 bug②：正则写死"题干=单个全角括号组"，
                                              "第11题（仿照例句，说一说。）" 嵌套括号 → 失配
      ↓  _record_module_evidence(qidx,...)  ← 建 questions["auto-Q{big:02d}-{sub:02d}"]
      ↓  _save_inspection_state_merge()

覆盖 4 个用例组：
  A 真实发报契约（第1小题=全证据、第2~5小题=仅小题题干）→ 20 题必须全在
  B 显式空列表 evidence=[]（题干未识别）→ 题目仍要登记（不能被吞）
  C 嵌套全角括号题干 → 题号仍要正确提取
  D 复用缓存回灌 → 不能覆盖本轮 fresh 的基础层字段

跑法：cd <proj> && python tools/test_evidence_persist.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("ANDROID_SERIAL", "")

import web_server as W                      # noqa: E402
from common import logger as L              # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  —— {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


BIGS = {
    1: ["mum moon", "meet meat", "nose note", "nut net", "pig pet"],
    2: ["A typhoon is coming.", "What will you do?", "I'll turn off the lights.",
        "You'll need to close the windows.", "If you happen to be outside, stay away from trees."],
    3: ["第11题（仿照例句，说一说。）", "第12题（仿照例句，说一说。）",
        "第13题（仿照例句，说一说。）", "第14题（仿照例句，说一说。）",
        "第15题（仿照例句，说一说。）"],
    4: ["What will come tomorrow?", "When will the heavy rain come?",
        "What should the students do before they go to school?",
        "What should they do on the way home?", "What should they do at home?"],
}


def full_ev(stem):
    """第 1 小题的全量证据（题型/分值/小题题干/题干/音频/作答）"""
    return [
        {"field": "题型", "diff": "[口语跟读] 朗读训练", "type": "info"},
        {"field": "分值", "actual": "2分", "type": "info"},
        {"field": "小题题干", "actual": stem, "src": "dom", "type": "info"},
        {"field": "题干", "actual": stem, "diff": "题干与脚本一致", "type": "text_ok"},
        {"field": "音频", "actual": "小喇叭可点", "diff": "无需检查小喇叭", "type": "text_ok"},
        {"field": "作答", "actual": "麦克风可点", "diff": "作答元素存在", "type": "text_ok"},
    ]


def sub_ev(stem):
    """第 2~5 小题：模块过滤掉"每题相同的通用通过项"后剩下的（修复后保留小题题干）"""
    return [{"field": "小题题干", "type": "info", "expected": "当前作答小题的题干",
             "actual": stem, "src": "dom", "diff": f"小题题干：{stem}"}]


def reset():
    W._inspection_state.clear()
    W._inspection_state.update({
        "current_question_idx": 0, "questions": {}, "workflow_steps": [],
        "docx": "", "version": "教科版（2024审定）", "unit": 4, "stage": "全部",
        "live_report_path": "", "_reuse_info": "", "grade": "五年级上册",
        "_modules_total": {}, "_qid_owner": {}, "_qid_map": {}, "_seen_qids": {},
        "_script_issues": {},
    })
    L.set_log_callback(None)


def _autos():
    return sorted(k for k in W._inspection_state["questions"] if k.startswith("auto-"))


def phase_a_real_contract():
    """A：完全按修复后 口语训练.py 的发报方式走 logger → web_server 全链路"""
    L.set_log_callback(W.log_msg)
    L.set_current_module("口语训练", "")
    for big, subs in BIGS.items():
        for i, stem in enumerate(subs, 1):
            ev = full_ev(stem) if i == 1 else sub_ev(stem)
            L.step_log(f"  第{big}大题·第{i}小题（{stem}）完整性检查", "info", ev)
    got = _autos()
    want = [f"auto-Q{b:02d}-{i:02d}" for b, ss in BIGS.items() for i in range(1, len(ss) + 1)]
    check("A 全链路 20 题全部登记", got == want, f"got {len(got)}: {got}")
    # 第 2~5 小题也必须有小题题干（否则脚本一致性比对没对象）
    no_sub = [k for k in got if not (W._inspection_state["questions"][k].get("app_stem")
                                    or W._inspection_state["questions"][k].get("stem"))]
    check("A 每题都带上了题目内容", not no_sub, f"无题干: {no_sub[:5]}")


def phase_b_empty_evidence():
    """B：显式空列表 = "这是一道题，但本轮没有可展示的证据" → 仍要登记"""
    L.set_log_callback(W.log_msg)
    L.set_current_module("口语训练", "")
    L.step_log("  第9大题·第1小题（）完整性检查", "info", [])
    check("B 空证据列表仍登记题目", "auto-Q09-01" in W._inspection_state["questions"],
          f"keys={_autos()}")
    # None（未传）仍然不能登记 —— 普通流程日志不能被当成一道题
    n0 = len(W._inspection_state["questions"])
    L.step_log("  第9大题·第2小题 普通流程日志", "info")
    check("B 不传证据的普通日志不登记", len(W._inspection_state["questions"]) == n0)


def phase_c_nested_paren():
    """C：题干含嵌套全角括号 → 题号必须仍能提取（旧正则此处整题丢弃）"""
    import re
    pat = re.compile(r"\s*(?:第(\d+)大题·)?第(\d+)(?:题|小题)")

    def parse(msg):
        m = pat.match(msg)
        if m and "检查" in msg:
            return (int(m.group(1)) if m.group(1) else None, int(m.group(2)))
        return (None, None)

    check("C 嵌套括号题干 → 题号 (3,1)",
          parse("  第3大题·第1小题（第11题（仿照例句，说一说。））完整性检查") == (3, 1),
          repr(parse("  第3大题·第1小题（第11题（仿照例句，说一说。））完整性检查")))
    check("C 答错截图不被误判为完整性检查",
          parse("  第2题 答错截图") == (None, None))


def phase_d_cache_reuse():
    """D：复用缓存回灌不得覆盖本轮 fresh 的基础层业务字段"""
    qs = W._inspection_state["questions"]
    autos = [k for k in qs if k.startswith("auto-")]
    cached = {k: {"script": {"dims": {"stem": True}}, "note": "脚本核验·X.docx"}
              for k in autos}
    before = {k: dict(qs[k]) for k in autos}
    merged = 0
    for _k, _v in cached.items():      # 与 web_server L5514-5524 同构
        _cur = qs.get(_k)
        if _cur is not None and isinstance(_v.get("script"), dict) and _k.startswith("auto-"):
            _cur["script"] = _v["script"]
            _cur["layer"] = "basic+script"
            _cur["note"] = _v.get("note") or _cur.get("note")
            merged += 1
        else:
            qs[_k] = _v
    lost = [(k, f) for k, v in before.items() for f in ("module", "idx", "overall_passed")
            if f in v and qs.get(k, {}).get(f) != v.get(f)]
    check("D 缓存回灌后 auto-* 数量不变", len(_autos()) == len(autos),
          f"{len(autos)} → {len(_autos())}")
    check("D 基础层字段未被缓存快照覆盖", not lost, f"被覆盖: {lost[:5]}")
    check("D 脚本层已合并", merged == len(autos), f"merged={merged}")


def phase_e_persist():
    """E：落盘（_save_inspection_state_merge）后题目仍在"""
    W._save_inspection_state_merge()
    import json
    d = json.loads((ROOT / "data" / "inspection_state.json").read_text(encoding="utf-8"))
    qs = d.get("questions") or {}
    a = [k for k in qs if k.startswith("auto-")]
    check("E 落盘后 auto-* 仍在", len(a) == len(_autos()), f"disk {len(a)} / mem {len(_autos())}")
    return d


def phase_f_script_issues_persist():
    """F：脚本自检发现的问题、复用信息必须能落盘。

    旧 `_save_inspection_state_merge` 写的是 `_merged = dict(old)`（以旧文件为准），
    只覆盖 questions 和 version/grade/... 几个键 → 本次运行新写入内存的
    `_script_issues` 全被丢掉：前端日志明明打了"脚本自检发现 3 处问题"，
    但状态文件/报告里一个都没有。
    """
    W._inspection_state.setdefault("_script_issues", {})["口语训练"] = [
        {"type": "答案与关键词不一致", "severity": "高",
         "location": "U4 第4大题 第3小题",
         "detail": "关键词 bring ↔ 参考答案 take", "suggestion": "核对用词"}]
    W._inspection_state["_reuse_info"] = "复用测试"
    W._inspection_state["_modules_total"] = {"口语训练": 20}
    W._save_inspection_state_merge()
    import json
    d = json.loads((ROOT / "data" / "inspection_state.json").read_text(encoding="utf-8"))
    si = (d.get("_script_issues") or {}).get("口语训练") or []
    check("F 脚本自检问题已落盘", len(si) == 1 and si[0].get("severity") == "高",
          f"got {si}")
    check("F _reuse_info 已落盘", d.get("_reuse_info") == "复用测试",
          repr(d.get("_reuse_info")))
    check("F _modules_total 已落盘",
          (d.get("_modules_total") or {}).get("口语训练") == 20,
          repr(d.get("_modules_total")))
    check("F 题目未被辅助键的修正影响",
          len([k for k in (d.get("questions") or {}) if k.startswith("auto-")]) == len(_autos()))


if __name__ == "__main__":
    p = ROOT / "data" / "inspection_state.json"
    bak = p.read_text(encoding="utf-8") if p.exists() else None
    reset()
    print("[A] 真实发报契约（logger → web_server 全链路）")
    phase_a_real_contract()
    print("[B] 显式空列表 evidence=[]")
    phase_b_empty_evidence()
    print("[C] 嵌套全角括号题干 / 消息契约")
    phase_c_nested_paren()
    print("[D] 复用缓存回灌")
    phase_d_cache_reuse()
    print("[E] 落盘")
    phase_e_persist()
    print("[F] 脚本自检结果落盘")
    phase_f_script_issues_persist()
    print("=" * 56)
    if FAIL:
        print(f"结果: {len(FAIL)} 项失败 ❌  {FAIL}")
        sys.exit(1)
    print("结果: 全部通过 ✅")
    if bak is not None:
        p.write_text(bak, encoding="utf-8")
        print("（已还原测试前的 inspection_state.json）")
