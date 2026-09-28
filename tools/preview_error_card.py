# -*- coding: utf-8 -*-
"""生成「错题卡新样式」预览页（用真实脚本数据 + 真实截图，无需连手机）。

用途：改版前后对比、给检查人员确认"现在的卡片是不是一眼能看懂"。

跑法：
    python tools/preview_error_card.py
产出：
    outputs/reports/card_preview.html
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from src.report_exporter import ReportExporter  # noqa: E402
from src.review_agent import check_answer_keyword_consistency as kwcheck  # noqa: E402

DOCX = ROOT / "uploads" / "260727口语训练新教科五上U4-7（已二校）.docx"
SHOT = "auto_口语训练_q001_144548.png"        # 真机截图（口语训练 U7 第4大题）
OUT = ROOT / "outputs" / "reports" / "card_preview.html"


def _find_box_for_text(text: str):
    """在项目里现存的 UI dump 中找该文本的控件坐标（有则用于演示特写截图）。"""
    from common.evidence import _box_of_text
    for p in list(ROOT.glob("*.xml")) + list((ROOT / "tmp_gen").glob("*.xml")):
        try:
            xml = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if text[:8] not in xml:
            continue
        box = _box_of_text(xml, text)
        if box:
            return box
    return None


def build_questions():
    from src.parse_yingyubao_docx import parse
    qs = parse(str(DOCX))
    out = []

    # ① 关键词 ↔ 参考答案 不一致（用户实测：答案 take / 关键词 bring）
    q = next(x for x in qs
             if x.unit == 4 and x.big == 4 and x.stage_idx == 3)
    probs, n, _ = kwcheck(q.answer, q.keywords, q.passage or q.recording)
    if probs:
        out.append({
            "idx": 3, "question_type": "口语训练·看文回答",
            "module": "口语训练", "position": "U4·第4大题·第3小题",
            "stem": f"第4大题·第3小题　{q.stem}",
            "script_answer": (q.answer or "").split("\n")[0],
            "ai_answer": False,
            "answer_reason": "❌ " + probs[0],
            "answer_suggestion": ("把「关键词」改成与参考答案一致的表达"
                                  "「take their raincoats」；或反向统一短文/答案用词，"
                                  "两者必须一致，否则学生按关键词作答会被判错"),
            "screenshot": SHOT,
            "overall_passed": False,
            "_boxes": {"answer": _find_box_for_text(q.stem) or {}},
        })

    # ② 大题说明与脚本不符（旧版把"大题说明"当"小题题面"比 → 整单元误报）
    q2 = next(x for x in qs if x.unit == 4 and x.big == 4 and x.stage_idx == 1)
    out.append({
        "idx": 1, "question_type": "口语训练·看文回答",
        "module": "口语训练", "position": "U4·第4大题·第1小题",
        "stem": f"第4大题·第1小题　{q2.stem}",
        "script_answer": (q2.answer or "").split("\n")[0],
        "ai_stem": False,
        "stem_reason": ("❌ 大题说明与脚本不符：App 显示「请阅读短文，点击“小喇叭”播放问题，"
                        "点击“录音”开始作答。」，脚本应为「请阅读短文，点击“小喇叭”播放问题，"
                        "点击“录音”开始作答。每小题有10秒钟的准备时间，15秒钟的作答时间。」"
                        "（位置：第4大题·第1小题）"),
        "stem_suggestion": ("把 App 该处大题说明补齐为脚本全文"
                            "（含「每小题有10秒钟的准备时间，15秒钟的作答时间。」），"
                            "保证与脚本逐字一致"),
        "screenshot": SHOT,
        "overall_passed": False,
        "_boxes": {"stem": {"x": 40, "y": 150, "w": 1000, "h": 130}},
    })

    # ③ 一条正常通过、不应出现在错题报告里的题（防误报）
    out.append({
        "idx": 2, "question_type": "口语训练·看文回答",
        "stem": "第4大题·第2小题　When will the heavy rain come?",
        "script_answer": "It will come in the afternoon. / In the afternoon.",
        "ai_stem": True, "ai_content": True, "ai_answer": True,
        "overall_passed": True,
    })
    return out


def demo_crop():
    """用真实截图 + 手工圈定的题干区域，演示「出错区域特写」效果。

    ⚠ 这里的手工坐标只为"让你看到特写长什么样"。真机上坐标来自 uiautomator
      的 node bounds（scripts/common/evidence.py _box_of_text），无需手工标注。
    """
    from trace_engine import TraceEngine
    box = {"x": 40, "y": 150, "w": 1000, "h": 130}      # 截图里"请阅读短文…"那两行
    eng = TraceEngine(str(ROOT / "screenshots"))
    out = ROOT / "outputs" / "web" / f"crop_v2_{SHOT}"
    if not out.exists():
        if not eng.crop_evidence(SHOT, [{"error_region": box}], str(out)):
            return False
    return out.exists()


def main():
    if not DOCX.exists():
        print("缺少样本脚本:", DOCX)
        return 1
    if not (ROOT / "screenshots" / SHOT).exists():
        print("缺少样本截图:", SHOT)
        return 1
    qs = [q for q in build_questions() if not q.get("overall_passed", True)]
    demo_crop()
    exp = ReportExporter()
    meta = {"version": "教科版(2024审定)", "unit": "4", "stage": "口语训练",
            "date": "2026-09-17 样例", "total": len(qs)}
    doc = exp._render_live_html(qs, meta)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    print("已生成:", OUT)
    print("错题卡数量:", doc.count('<details class="card">'),
          "| 双栏对照:", doc.count('class="cmp"'),
          "| 怎么改:", doc.count("怎么改"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
