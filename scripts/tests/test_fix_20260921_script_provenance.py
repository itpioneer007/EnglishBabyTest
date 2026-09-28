# -*- coding: utf-8 -*-
"""回归：脚本比对溯源（_script_provenance）—— 报告/前端要能说清"结论拿哪份脚本比出来的"

用户连续两轮反馈"没测过的题也乱报""是不是故意输出这些内容的"，根子之一是
**报告里看不出脚本结论的来源**：跑教科六上 U6 却拿「口语训练新教科五上U4-7」比对，
报出来的一串"与脚本不符"全是假错，但报告上没有任何提示。

本测试锁定三件事：
  ① web_server 在三条比对路径上都会记录溯源（通过/被守卫挡下）；
  ② 溯源一旦记为"匹配"，后续路径不得把它降级；
  ③ 报告（HTML）与前端文案能正确渲染 ok / bad / unk 三态。
"""
import os
import sys

_PR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _PR)

PASS = FAIL = 0


def chk(name, cond, extra=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


print("=" * 70)
print("【1】_set_script_provenance 记录语义")

import web_server as W  # noqa: E402

W._inspection_state = {"questions": {}}
W.log_msg = lambda *a, **k: None

W._set_script_provenance("口语训练", "口语训练教科六上U6.docx", True)
_p = W._inspection_state["_script_provenance"]["口语训练"]
chk("匹配时记录文件名", _p["file"] == "口语训练教科六上U6.docx", str(_p))
chk("匹配时 matched=True 且无原因", _p["matched"] is True and not _p["reason"])

# 后续路径被守卫挡下 → 不得把已确认的 True 降级
W._set_script_provenance("口语训练", "", False, "脚本是「五年级上册」，本次实跑是「六年级上册」")
_p = W._inspection_state["_script_provenance"]["口语训练"]
chk("已匹配的不被后续路径降级", _p["matched"] is True, str(_p))

# 全新状态：只走了被挡下的路径
W._inspection_state = {"questions": {}}
W._set_script_provenance("口语训练", "260727口语训练新教科五上U4-7.docx", False,
                         "脚本是「五年级上册」，本次实跑是「六年级上册」")
_p = W._inspection_state["_script_provenance"]["口语训练"]
chk("被守卫挡下：matched=False", _p["matched"] is False)
chk("被守卫挡下：记录原因", "五年级上册" in _p["reason"], _p["reason"])

# 未挂载脚本
W._inspection_state = {"questions": {}}
W._set_script_provenance("口语训练", "", False, "未挂载脚本（docxMap 无该模块映射）")
chk("未挂载脚本也记录", W._inspection_state["_script_provenance"]["口语训练"]["matched"] is False)

print()
print("【2】_script_matches_run 守卫确实挡得住（uploads 里的真实文件名）")
_r = W._script_matches_run("260727口语训练新教科五上U4-7（已二校）.docx",
                           "教科版(2024审定)", "六年级上册")
chk("五上脚本挡在六上运行之外", "五年级上册" in _r and "六年级上册" in _r, repr(_r))
chk("六上脚本放行", W._script_matches_run("口语训练新教科六上U6.docx",
                                      "教科版(2024审定)", "六年级上册") == "")

print()
print("【3】报告文案三态")
from src.report_exporter import ReportExporter  # noqa: E402

lines = ReportExporter._script_provenance_lines({})
chk("空溯源 → unk 且提示人工复核",
    len(lines) == 1 and lines[0][0] == "unk" and "人工复核" in lines[0][1], str(lines))

lines = ReportExporter._script_provenance_lines(
    {"script_provenance": {"口语训练": {"file": "口语训练教科六上U6.docx", "matched": True}}})
chk("匹配 → ok 且写明文件名",
    lines[0][0] == "ok" and "口语训练教科六上U6.docx" in lines[0][1], str(lines))

lines = ReportExporter._script_provenance_lines(
    {"script_provenance": {"口语训练": {"file": "五上.docx", "matched": False,
                                     "reason": "脚本是「五年级上册」，本次实跑是「六年级上册」"}}})
chk("不匹配 → bad", lines[0][0] == "bad", str(lines))
chk("不匹配文案写明不作为判定依据", "不作为判定依据" in lines[0][1], lines[0][1])
chk("不匹配文案带出具体原因", "五年级上册" in lines[0][1], lines[0][1])

print()
print("【4】HTML 实时报告真的渲染出横幅")


def _render(meta_extra):
    q = {"qid": "auto-Q02-01", "idx": 1, "big": 2, "module": "口语训练",
         "question_type": "口语训练", "overall_passed": False,
         "ai_stem": False, "stem": "X",
         "stem_reason": "❌ 大题说明与脚本不符：App 显示「A」，脚本应为「B」"}
    meta = {"version": "教科版(2024审定)", "unit": "6", "stage": "全部",
            "date": "2026-09-21 20:00", "total": 1}
    meta.update(meta_extra)
    # export_html_live 落盘并返回路径 → 读回内容再断言
    _p = ReportExporter(save_dir=os.path.join(_PR, "outputs", "tmp_prov")).export_html_live([q], meta)
    with open(_p, encoding="utf-8") as fh:
        return fh.read()


h_bad = _render({"script_provenance": {"口语训练": {"file": "五上.docx", "matched": False,
                                                 "reason": "脚本是「五年级上册」"}}})
chk("bad 横幅 class 正确", 'class="prov prov-bad"' in h_bad)
chk("bad 横幅文案出现", "未做脚本层比对" in h_bad)

h_ok = _render({"script_provenance": {"口语训练": {"file": "六上.docx", "matched": True}}})
chk("ok 横幅 class 正确", 'class="prov prov-ok"' in h_ok)
chk("ok 横幅写明匹配", "版本/年级匹配" in h_ok)

h_unk = _render({})
chk("unk 横幅 class 正确", 'class="prov prov-unk"' in h_unk)
chk("unk 横幅提示人工复核", "人工复核" in h_unk)

# 清理测试落盘
try:
    import shutil as _sh
    _sh.rmtree(os.path.join(_PR, "outputs", "tmp_prov"), ignore_errors=True)
except Exception:
    pass

print()
print("=" * 70)
print(f"结果: {PASS} 通过 / {FAIL} 失败")
sys.exit(1 if FAIL else 0)
