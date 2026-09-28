"""★ 2026-09-23 修复回归测试：实时报告必须把「未判定（证据不足）」列成清单。

现场（教科版五上 U7 第4大题「听录音作答」）：
    第4大题每小题在 App 上只有音频图标 + 录音按钮，没有文字题干
    → 基础层只查得到 1 维（作答）→ `overall_passed=None`（未判定）。
    报告统计卡写着「未判定 5」，正文却**一条明细都没有**：
    `export_html_live` 只把 False / 有脚本问题的题放进卡片列表，
    None 分支仅 `_undet += 1`；提示语也只说"脚本自检命中 2 处"。
    审查员看到数字无从下手（用户对"未审"一直要求可见、可点、可查）。

本测试锁定：
  1) 未判定题必须进「未判定」区块，带题号定位 + 「仅 N 维可查（维度名）」
  2) 未判定题**绝不**出现在"不通过"卡片里（三态严格互斥）
  3) 三数自洽：通过 + 不通过 + 未判定 = 总题数，通过率同源
  4) 无未判定题时**不出**该区块（不产生空区块噪音）
  5) 模块自动生成的占位题面（'第4大题·第1题（口语训练）'）不展示；
     真实题干正常展示
  6) 反向用例：True / False 的题都不许混进未判定清单
  7) 未判定 + 脚本自检可共存，提示语同时提及两者

运行：python scripts/tests/test_fix_20260923h_undet_section.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src.report_exporter import ReportExporter  # noqa: E402

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


def _q(idx, passed, dims=(), stem="", unit="7", big=4, sub=None, progress=None,
       extra=None):
    """造一条题记录。dims = 可查维度名元组（都算"已核验且通过"）。"""
    _sub = sub if sub is not None else idx
    q = {
        "qid": f"auto-Q0{big}-0{idx}", "idx": idx, "big": big, "module": "口语训练",
        "stage": "全部", "progress": progress or f"大{big}-Q{_sub}", "_unit": unit,
        "overall_passed": passed, "question_type": "口语训练", "stem": stem,
        "_score": {
            "checked_count": len(dims), "passed_count": len(dims),
            "dims": [{"name": n, "passed": True, "severity": "high"} for n in dims],
        },
    }
    q.update(extra or {})
    return q


def _render(qs, meta_extra=None):
    tmp = Path(tempfile.mkdtemp(prefix="undet_test_"))
    meta = {"version": "教科版(2024审定)", "unit": "7", "stage": "全部",
            "date": "2026-09-23 19:50", "total": len(qs)}
    meta.update(meta_extra or {})
    p = Path(ReportExporter(save_dir=str(tmp)).export_html_live(qs, meta))
    return p.read_text(encoding="utf-8")


def _stat(h, lab):
    m = re.search(r'class="num"[^>]*>\s*([^<]*?)\s*</div>\s*<div class="lab"[^>]*>\s*'
                  + lab + r'\s*</div>', h, re.S)
    return m.group(1).strip() if m else None


print("【1】U7 实况：15 通过 + 5 未判定（第4大题听录音作答）")
_und = [_q(i, None, dims=("作答",), stem=f"第4大题·第{i}题（口语训练）")
        for i in range(1, 6)]
_ok = [_q(i, True, dims=("题干", "作答"), stem="sit in the sun",
          big=2, sub=i, progress=f"大2-Q{i}") for i in range(1, 16)]
h = _render(_und + _ok)

chk("未判定区块存在", 'class="ud-sec"' in h)
chk("区块标题写明 5 道", "未判定（5 道）" in h)
chk("逐题列出 5 行", h.count('class="ud-row"') == 5)
chk("每行带题号定位（U7 · 第4大题 · 第1小题）", "U7 · 第4大题 · 第1小题" in h)
chk("注明仅 N 维可查", "仅 1 维可查" in h)
chk("带出具体维度名（作答）", "仅 1 维可查（作答）" in h)
chk("说明含「不参与通过/不通过判定」", "不参与通过/不通过判定" in h)
chk("占位题面不展示（无信息量）", "第4大题·第1题（口语训练）" not in h)
chk("通过题不进卡片（报告只列问题）", 'class="card' not in h)
chk("统计卡：不通过 0", _stat(h, "不通过") == "0", _stat(h, "不通过"))
chk("统计卡：未判定 5", _stat(h, "未判定") == "5", _stat(h, "未判定"))
chk("统计卡：已审查 20", _stat(h, "已审查") == "20", _stat(h, "已审查"))
chk("统计卡：通过率 75%", _stat(h, "通过率") == "75%", _stat(h, "通过率"))
chk("三数自洽 15+0+5=20", 15 + 0 + 5 == 20)
chk("提示语提及未判定数", "5 道题证据不足未判定" in h)

print()
print("【2】反向：overall_passed=False 的题绝不进未判定清单")
_qf = _q(1, False, dims=("题干",), stem="wrong sentence",
         extra={"ai_stem": False, "stem_reason": "❌ 与脚本不符"})
h2 = _render([_qf])
chk("不出未判定区块", 'class="ud-sec"' not in h2)
chk("生成错题卡片", 'class="card' in h2)
chk("未判定统计 = 0", _stat(h2, "未判定") == "0", _stat(h2, "未判定"))
chk("不通过统计 = 1", _stat(h2, "不通过") == "1", _stat(h2, "不通过"))

print()
print("【3】反向：overall_passed=True 的题不进未判定清单")
h3 = _render([_q(1, True, dims=("题干", "作答"), stem="ok sentence")])
chk("不出未判定区块", 'class="ud-sec"' not in h3)
chk("文案为「全部通过」", "全部通过" in h3)
chk("通过率 100%", _stat(h3, "通过率") == "100%", _stat(h3, "通过率"))

print()
print("【4】未判定 + 脚本自检 共存")
_sc = {"口语训练": [{"severity": "中", "type": "知识点为占位符",
                   "location": "U7 第4大题", "detail": "知识点写成了占位符「/」",
                   "quote": "/", "suggestion": "替换为真实知识点"}]}
h4 = _render(_und, {"script_issues": _sc})
chk("脚本自检区块仍在", 'class="sc-sec"' in h4)
chk("未判定区块仍在", 'class="ud-sec"' in h4)
chk("提示语同时提及未判定", "5 道题证据不足未判定" in h4)
chk("提示语同时提及脚本自检", "脚本自检命中 1 处问题" in h4)

print()
print("【5】缺 _unit 时回退到本次运行单元；真实题干照常展示")
_qn = _q(1, None, dims=("作答",), stem="What do the birds need?")
_qn["_unit"] = ""
h5 = _render([_qn])
chk("回退 meta.unit 生成定位", "U7 · 第4大题" in h5)
chk("真实题干展示在行尾", "What do the birds need?" in h5)

print()
print("【6】空数据不炸；全空时无未判定区块")
h6 = _render([])
chk("空输入可渲染", 'class="empty"' in h6)
chk("空输入无未判定区块", 'class="ud-sec"' not in h6)

print()
print("=" * 56)
print(f"PASS {PASS} / FAIL {len(FAIL)}")
if FAIL:
    for n in FAIL:
        print("  -", n)
    sys.exit(1)
