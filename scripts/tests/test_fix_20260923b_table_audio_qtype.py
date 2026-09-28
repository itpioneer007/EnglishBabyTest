# -*- coding: utf-8 -*-
"""题型误判修复回归（2026-09-23 · 口语训练五上U6第4大题「表格 + 小喇叭」）

用户实测反馈（原话）：
    这道题的题型不能乱讲，它这是一个表格，然后题目是要点击喇叭之后听题目内容
    之后再进行口语作答，不能说成是图片作答，因为每个小题里面并没有图片，
    应该是听录音作答

缺陷现象（审查卡片原文）：
    第4大题·第2小题（听音频跟读）完整性检查
      音频
        图片/大图题，听力音频通常自动播放，无需手动点扬声器
        预期: 图片题（音频自动播放/无独立播放控件）   实际: 图片作答

根因（精确到行）：
    scripts/common/evidence.py::collect_ui_evidence ④ 音频维度。
    旧代码按「页面有没有大 ImageView」判"是不是图片题"：
        _has_big_image → w>500 and h>300 and 300<y1<1600
        _is_image_q = _has_big_image or ("图片" in xml and ("看图片"/"看图"/"观察图片"))
    口语训练五上U6第4大题整页只有一张**表格素材**（大题级大图，页面还有
    "点击图片可查看高清大图"提示），每个小题里并没有图片，只有小喇叭 + 录音按钮。
    → 表格命中"大图"判据 → 音频维度被写成"图片题（音频自动播放）｜图片作答"，
      题型讲错了。且该判据依赖滚动位置（表格 y 漂移），表现为**偶发**。

修复：
    把「播放控件检测」提到「图片题判定」之前，并加守卫——「页面有大图」≠「本题是图片题」：
        _play_hint = xml 含 小喇叭/播放问题/点小喇叭/先听…（题干要求学生去点喇叭）
        if _is_image_q and (play_clickable or _play_hint):
            _is_image_q = False        # 音频需手动触发 → 属听录音作答
    守卫必须从严：只看 play_found 会误伤真·自动播放图片题（大题说明里就有
    "点击'小喇叭'播放问题"这几个字，_find_control 第二轮会把它当成控件）。

    同时把口语训练模块的无文字占位题干由「听音频跟读」改为「听录音作答」
    （学生是听问题后作答，不是复述），web_server.py 的 UI 标签豁免词表同步兼容两个值。
"""
import os
import sys
import types

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "scripts"))

# 不连手机：stub uiautomator2
sys.modules.setdefault("uiautomator2", types.ModuleType("uiautomator2"))

from common.evidence import collect_ui_evidence  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [OK] " if cond else "  [NG] ") + name + (f"   —— {detail}" if detail and not cond else ""))


def audio_ev(evs):
    return next((e for e in evs if e.get("field") == "音频"), None)


def blob(evs):
    return " | ".join(f"{e.get('field')}:{e.get('type')}:{e.get('expected')}:{e.get('actual')}:{e.get('diff')}"
                      for e in evs)


# ============================================================
# 夹具：口语训练 教科五上 U6 第4大题（真机 1080x2400 布局还原）
#   整页只有一张表格素材（大图），每个小题里没有图片，只有小喇叭 + 录音按钮
# ============================================================
U6_XML = "".join([
    '<hierarchy rotation="0">',
    # 顶部栏 / 进度
    '<node class="android.widget.TextView" resource-id="com.dinoenglish.yyb:id/tv_exit" '
    'text="退出训练" bounds="[40,150][230,220]"/>',
    '<node class="android.widget.TextView" text="口语训练教科五上U6" bounds="[300,150][820,220]"/>',
    '<node class="android.widget.TextView" resource-id="com.dinoenglish.yyb:id/tv_question_sort" '
    'text="4/4" bounds="[850,150][1030,220]"/>',
    '<node class="android.widget.TextView" text="练习结束还剩：07:57" bounds="[60,300][520,360]"/>',
    # 大题说明：明确要求学生"点击小喇叭播放问题，点击录音开始作答"
    '<node class="android.widget.TextView" resource-id="com.dinoenglish.yyb:id/tv_caption" '
    'text="请阅读表格，点击“小喇叭”播放问题，点击“录音”开始作答。每小题有10秒钟的准备时间，15秒钟的作答时间。（共10分）" '
    'bounds="[60,400][1020,560]"/>',
    '<node class="android.widget.TextView" text="点击图片可查看高清大图" bounds="[330,600][750,650]"/>',
    # ★ 表格素材：w=840 h=394 y=892 → 命中旧代码"大图"判据（就是误判来源）
    '<node class="android.widget.ImageView" resource-id="com.dinoenglish.yyb:id/table_iv" '
    'bounds="[118,892][958,1286]"/>',
    # 小题容器（tv_sort "2/5" + 分值 + 状态，无 pic_iv、无文字题面）
    '<node class="android.widget.LinearLayout" resource-id="com.dinoenglish.yyb:id/ll_container" '
    'bounds="[0,1350][1080,2050]">',
    '<node class="android.widget.TextView" resource-id="com.dinoenglish.yyb:id/tv_sort" '
    'text="2/5" bounds="[60,1380][220,1440]"/>',
    # 小喇叭：可点击的播放控件（真机上的"点它播放问题"）
    '<node class="android.widget.ImageView" resource-id="com.dinoenglish.yyb:id/iv_play" '
    'clickable="true" bounds="[300,1370][420,1450]"/>',
    '<node class="android.widget.TextView" resource-id="com.dinoenglish.yyb:id/tv_title_score" '
    'text="(2分)" bounds="[700,1380][820,1440]"/>',
    '<node class="android.widget.TextView" resource-id="com.dinoenglish.yyb:id/tv_answer_status" '
    'text="未作答" bounds="[850,1380][1020,1440]"/>',
    '</node>',
    # 录音按钮（作答入口）
    '<node class="android.widget.FrameLayout" resource-id="com.dinoenglish.yyb:id/record_btn" '
    'clickable="true" bounds="[425,2100][655,2260]">',
    '<node class="android.widget.TextView" text="点击录音" bounds="[440,2140][640,2220]"/>',
    '</node>',
    '</hierarchy>',
])

print("\n== T1 口语训练 U6 第4大题（表格素材 + 小喇叭）→ 必须是听录音作答 ==")
_ev = collect_ui_evidence(U6_XML, qtype="口语训练")
for e in _ev:
    print("      [%s] %s actual=%r diff=%r" % (e.get("field"), e.get("type"),
                                               str(e.get("actual"))[:60], str(e.get("diff"))[:80]))
_a = audio_ev(_ev)
check("T1.1 音频维度存在", _a is not None)
check("T1.2 音频维度判为通过（小喇叭可点击）", (_a or {}).get("type") == "text_ok",
      f"type={( _a or {}).get('type')}")
check("T1.3 实际值写明播放控件可点击", "播放控件" in str((_a or {}).get("actual", ""))
      and "可点击" in str((_a or {}).get("actual", "")),
      f"actual={( _a or {}).get('actual')!r}")
check("T1.4 说明写明「听录音作答」", "听录音作答" in str((_a or {}).get("diff", "")),
      f"diff={( _a or {}).get('diff')!r}")
check("T1.5 预期不再写「图片题（音频自动播放…）」",
      "图片题" not in str((_a or {}).get("expected", "")),
      f"expected={( _a or {}).get('expected')!r}")
_all = blob(_ev)
check("T1.6 全卡不再出现「图片作答」", "图片作答" not in _all)
check("T1.7 全卡不再出现「图片/大图题，听力音频通常自动播放」",
      "听力音频通常自动播放" not in _all)
_ans = next((e for e in _ev if e.get("field") == "作答"), None)
check("T1.8 作答维度仍检出麦克风/录音控件", _ans is not None and "麦克风" in str(_ans.get("actual", "")),
      f"actual={( _ans or {}).get('actual')!r}")

# ============================================================
# T2 反向用例：真·自动播放听力图片题（大图 + 无播放控件）→ 仍走图片 skip
#    这是旧逻辑存在的理由（避免"听单词/看图选词"误报"未检测到播放控件"），不能被改坏
# ============================================================
IMG_ONLY_XML = "".join([
    '<hierarchy rotation="0">',
    '<node class="android.widget.TextView" text="听录音，选出正确的图片" bounds="[60,400][1020,500]"/>',
    '<node class="android.widget.ImageView" resource-id="com.dinoenglish.yyb:id/pic_iv" '
    'bounds="[118,892][958,1286]"/>',
    '<node class="android.widget.TextView" text="A" bounds="[100,1500][160,1560]"/>',
    '<node class="android.widget.TextView" text="B" bounds="[400,1500][460,1560]"/>',
    '</hierarchy>',
])
print("\n== T2 反向用例：自动播放听力图片题（无播放控件）→ 保持图片题 skip ==")
_ev2 = collect_ui_evidence(IMG_ONLY_XML, qtype="听力专项测试")
_a2 = audio_ev(_ev2)
check("T2.1 音频维度为 skip（图片题音频自动播放）", (_a2 or {}).get("type") == "skip",
      f"type={( _a2 or {}).get('type')}")
check("T2.2 说明仍是「图片/大图题…自动播放」",
      "图片/大图题" in str((_a2 or {}).get("diff", "")), f"diff={( _a2 or {}).get('diff')!r}")

# ============================================================
# T3 反向用例：说明文字里出现"播放"二字，但并没有可点击播放控件，
#    且不是听/说题 → 绝不能被翻成"扬声器存在但不可点击"（假错）
# ============================================================
HINT_NOT_SPEAK = "".join([
    '<hierarchy rotation="0">',
    '<node class="android.widget.TextView" text="看图片，把句子补充完整（播放动画后作答）" '
    'bounds="[60,400][1020,500]"/>',
    '<node class="android.widget.ImageView" resource-id="com.dinoenglish.yyb:id/pic_iv" '
    'bounds="[118,892][958,1286]"/>',
    '<node class="android.widget.EditText" resource-id="com.dinoenglish.yyb:id/et_input" '
    'bounds="[200,1500][800,1600]"/>',
    '</hierarchy>',
])
print("\n== T3 反向用例：仅有『播放』字样、无可点击控件 → 不得误报『扬声器不可点击』 ==")
_ev3 = collect_ui_evidence(HINT_NOT_SPEAK, qtype="")
_a3 = audio_ev(_ev3)
check("T3.1 未被翻成 text_mismatch（不产生假错）", (_a3 or {}).get("type") != "text_mismatch",
      f"type={( _a3 or {}).get('type')} diff={( _a3 or {}).get('diff')!r}")

# ============================================================
# T4 模块侧：无图无文字的小题 → 占位题干必须是「听录音作答」
# ============================================================
print("\n== T4 口语训练模块：无图无文字小题 → 题干占位为「听录音作答」 ==")
import importlib  # noqa: E402
M = importlib.import_module("modules.口语训练")
sub_no, total, stem, box = M._find_active_sub_question(None, U6_XML)
print("      sub_no=%r total=%r stem=%r box=%r" % (sub_no, total, stem, box))
check("T4.1 小题号解析 v_sort '2/5' → 2", sub_no == 2, f"got {sub_no}")
check("T4.2 小题总数 5", total == 5, f"got {total}")
check("T4.3 占位题干 = 「听录音作答」", stem == "听录音作答", f"got {stem!r}")
check("T4.4 不再使用旧标签「听音频跟读」", stem != "听音频跟读", f"got {stem!r}")
check("T4.5 不得标成图片题", "图片题" not in str(stem), f"got {stem!r}")
check("T4.6 题干来源标记为 audio", M._LAST_STEM_SRC == "audio", f"got {M._LAST_STEM_SRC!r}")

# ============================================================
# T5 UI 标签豁免词表：server 侧要认「听录音作答」（否则会被当题目内容逐字比对 → 假错）
# ============================================================
print("\n== T5 后端 UI 标签豁免词表兼容新旧占位标签 ==")
_src = open(os.path.join(BASE, "web_server.py"), encoding="utf-8", errors="ignore").read()
check("T5.1 _uikit 含「听录音作答」", '"听录音作答"' in _src)
check("T5.2 _uikit 保留「听音频跟读」（兼容历史状态文件）", '"听音频跟读"' in _src)

print("\n" + "=" * 62)
print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("   -", f)
sys.exit(1 if FAIL else 0)
