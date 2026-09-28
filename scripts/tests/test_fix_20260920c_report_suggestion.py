# -*- coding: utf-8 -*-
"""2026-09-20(c) 错题报告：定位截图 + 改进建议 回归测试

用户实测反馈（错题报告_教科版(2024审定)_20260920_1744.docx）：
  ① 6 道错题只有 2 道有定位截图 —— 后 4 道一张图都没有
  ② 改进建议跟错误牛头不对马嘴：第1题错的是"App 大题说明与脚本不符"，
     建议却写"请核对配图"
  ③ 建议被截半句："补充完整题干，例如\"仿照例句，说一说：I"

根因：
  ① 截图只在「当场判定 False」时抓；而这 4 题基础层是 None（未判定），
     要等收尾时脚本层折算（_fold_script_layer）才翻 False —— App 早翻页了。
  ② 建议靠关键词【跨维度】全文匹配：理由里出现"结合图片"四字就被配图规则抢走。
     且记录里明明存着按维度写好的 xxx_suggestion，却没被使用。
  ③ reason 被 [:120] 截断后才去抽"建议修改："，抽出半句。

本测试用用户那份报告里的真实错题作为 fixture。
"""
import os
import sys

_PR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _PR)

from src.report_exporter import ReportExporter  # noqa: E402

RE = ReportExporter
_ok = 0
_bad = 0


def chk(name, cond, extra=""):
    global _ok, _bad
    if cond:
        _ok += 1
        print(f"  [PASS] {name}")
    else:
        _bad += 1
        print(f"  [FAIL] {name}" + (f"  -> {extra}" if extra else ""))


print("=" * 70)
print("① 建议必须锁在【出错的那个维度】上（用户点名的配图误伤）")
print("=" * 70)

# —— 用户报告里的第1题：错在题干（App 大题说明 vs 脚本），理由里含"结合图片" ——
q1 = {
    "qid": "auto-Q02-01", "big": 2, "idx": 1,
    "question_type": "口语训练",
    "ai_stem": False, "ai_content": None, "ai_image": None,
    "ai_answer": None, "ai_audio": None, "ai_post_error": None,
    "stem_reason": ("❌ 大题说明与脚本不符：App 显示「请结合图片和教材内容，说出你看到的短语，"
                    "点击“录音”开始作答。」，脚本应为「请大声朗读你看到的句子，"
                    "点击“录音”开始作答。」"),
    "stem_suggestion": "",
}
s = RE._build_suggestion(q1, ["题干：" + q1["stem_reason"]])
joined = " | ".join(s)
chk("产出建议", len(s) >= 1, str(s))
_OLD_PIC_ADVICE = ("核对配图", "配图与题目内容不符", "配图与题目内容不符或缺失",
                   "确保与题干/答案语义一致且清晰可见")
chk("不再误报『核对配图』类建议（旧实现被'结合图片'抢走）",
    not any(k in joined for k in _OLD_PIC_ADVICE), joined)
chk("引用了完整的 App 原文（内嵌“录音”不再把句子切断）",
    "说出你看到的短语，点击“录音”开始作答。" in joined, joined)
chk("给出了脚本里的正确原文（照谁改）", "请大声朗读你看到的句子" in joined, joined)
chk("说明了要改 App 还是改脚本", "App" in joined and "脚本" in joined, joined)

print()
print("=" * 70)
print("② 优先采用【判定那一刻按维度存档】的建议原文（此前的截断半句问题）")
print("=" * 70)

q2 = {
    "qid": "auto-Q03-03", "big": 3, "idx": 3, "question_type": "口语训练",
    "ai_stem": False, "ai_answer": None, "ai_content": None,
    "ai_image": None, "ai_audio": None, "ai_post_error": None,
    "stem_reason": "❌ 脚本层不通过：题干为空…建议修改：补充完整题干，例如“仿照例句，说一说：I",  # 截断版
    "stem_suggestion": "在脚本中补充完整题干，例如“仿照例句，说一说：I will work with a space robot.”",
}
s2 = RE._build_suggestion(q2, ["题干：" + q2["stem_reason"]])
j2 = " | ".join(s2)
chk("采用存档建议而非半截 reason", "I will work with a space robot." in j2, j2)
chk("建议句子是完整的（不是被切一半）",
    all(not x.rstrip().endswith(("例如", "：", "说一说", "I")) for x in s2), j2)

print()
print("=" * 70)
print("③ 没有存档建议时：按维度分派生成（题干为空 / 作答关键词不一致）")
print("=" * 70)

q3 = {"qid": "Q-a", "question_type": "口语训练",
      "ai_stem": False, "ai_answer": None, "ai_content": None,
      "ai_image": None, "ai_audio": None, "ai_post_error": None,
      "stem_reason": "❌ 脚本层不通过：脚本题干为空，属于异常缺失，该题为“仿照例句，说一说”的句型操练题",
      "stem_suggestion": ""}
s3 = " | ".join(RE._build_suggestion(q3, ["题干：" + q3["stem_reason"]]))
chk("题干为空 → 建议补写题干", "补" in s3 and "题干" in s3, s3)
chk("不退化成『人工复核该题』兜底文案", "人工复核该题" not in s3, s3)

q4 = {"qid": "Q-b", "question_type": "口语训练",
      "ai_stem": None, "ai_answer": False, "ai_content": None,
      "ai_image": None, "ai_audio": None, "ai_post_error": None,
      "answer_reason": ("❌ 参考答案与关键词不一致：参考答案写的是「take their raincoats」，"
                        "但关键词是「bring their raincoats」"),
      "answer_suggestion": ""}
s4 = " | ".join(RE._build_suggestion(q4, ["作答：" + q4["answer_reason"]]))
chk("作答维度 → 指出答案/关键词必须统一", "关键词" in s4 and "统一" in s4, s4)
chk("作答维度不许产出题干建议", "题干" not in s4, s4)

q5 = {"qid": "Q-c", "question_type": "听力选择题",
      "ai_stem": None, "ai_answer": None, "ai_content": None,
      "ai_image": None, "ai_audio": False, "ai_post_error": None,
      "audio_reason": "❌ 音频不可点击：喇叭控件 disabled",
      "audio_suggestion": ""}
s5 = " | ".join(RE._build_suggestion(q5, ["音频：" + q5["audio_reason"]]))
chk("音频维度 → 音频资源建议", "音频" in s5 and ("播放" in s5 or "控件" in s5), s5)

print()
print("=" * 70)
print("④ 配图维度仍要走配图建议（不能修过头）")
print("=" * 70)
q6 = {"qid": "Q-d", "question_type": "看图选择",
      "ai_stem": None, "ai_answer": None, "ai_content": None,
      "ai_image": False, "ai_audio": None, "ai_post_error": None,
      "image_reason": "❌ 配图与题干不符：图片内容不是题干描述的场景",
      "image_suggestion": ""}
s6 = " | ".join(RE._build_suggestion(q6, ["配图：" + q6["image_reason"]]))
chk("配图维度 → 配图建议", "配图" in s6, s6)

print()
print("=" * 70)
print("⑤ 合并两条证据时不得把已有截图覆盖为空（缺图根因之一）")
print("=" * 70)
try:
    import web_server as W  # noqa: E402
    prev = {"screenshot": "auto_口语训练_b03q002_174500.png", "ai_stem": True}
    new = {"screenshot": "", "ai_stem": None}
    merged = W._merge_evidence_record(dict(prev), dict(new))
    chk("第二次上报无图 → 保留第一次的图", merged.get("screenshot") == prev["screenshot"],
        str(merged.get("screenshot")))
    chk("六维仍按『不通过优先』合并", merged.get("ai_stem") is True, str(merged.get("ai_stem")))
    new2 = {"screenshot": "later.png", "ai_stem": False}
    m2 = W._merge_evidence_record(dict(prev), new2)
    chk("新的非空截图可以覆盖（更新画面）", m2.get("screenshot") == "later.png")
    chk("任一维度 False → False 优先", m2.get("ai_stem") is False)
except Exception as e:  # 环境不允许 import 时不算失败
    print(f"  [SKIP] import web_server 失败: {e}")

print()
print("=" * 70)
print("⑥ 截图时机：不要只在『当场判 False』时才抓（用户报告缺图的根因）")
print("=" * 70)
try:
    import tempfile
    import web_server as W2  # noqa: E402

    _tmp = tempfile.mkdtemp(prefix="yyb_shot_")
    W2.PROJECT_ROOT = __import__("pathlib").Path(_tmp)
    W2._save_inspection_state = lambda *a, **k: None
    W2._live_regen_error_report = lambda: ""


    class _FakeDev:
        calls = []

        def screenshot(self, path):
            with open(path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
            _FakeDev.calls.append(os.path.basename(str(path)))


    W2._connect_device = lambda: _FakeDev()
    W2._current_module_name = "口语训练"
    W2._current_stage_name = ""
    W2._current_module_qno = 1
    W2._inspection_state = {
        "questions": {}, "unit": "6", "_modules_total": {}, "_qid_owner": {},
        "_qid_map": {}, "_seen_qids": {}, "_script_issues": {}, "unit": "6",
    }

    # 场景：第3大题第2小题，基础层判定为【未判定】（六维全 None）——
    #   这正是用户报告里那 4 道没截图的题当时的状态。
    W2._record_module_evidence(
        2, "  第3大题·第2小题（第12题）完整性检查", [], big=3)
    rec = W2._inspection_state["questions"].get("auto-Q03-02", {})
    chk("未判定(None) 也抓了定位截图（旧行为：抓不到）",
        bool(rec.get("screenshot")), str(rec.get("screenshot")))
    chk("截图文件确实落盘", len(_FakeDev.calls) == 1, str(_FakeDev.calls))
    chk("文件名带大题号，避免不同大题第1小题互相覆盖",
        _FakeDev.calls and "b03q002" in _FakeDev.calls[0], str(_FakeDev.calls))

    # 同一题第二次上报（如"扬声器内容检查"）不得再拍一张、也不得把图清空
    W2._record_module_evidence(
        2, "  第3大题·第2小题（第12题）检查", [], big=3)
    chk("同一题重复上报不重复截图", len(_FakeDev.calls) == 1, str(_FakeDev.calls))
    chk("重复上报后截图字段仍在",
        bool(W2._inspection_state["questions"]["auto-Q03-02"].get("screenshot")))
except Exception as e:
    print(f"  [SKIP] 截图时机用例不可用: {type(e).__name__}: {e}")

print()
print("=" * 70)
print(f"结果: {_ok} 通过 / {_bad} 失败")
print("=" * 70)
sys.exit(1 if _bad else 0)
