# -*- coding: utf-8 -*-
"""2026-08-25 App题干↔脚本题干 匹配校验 mock 验证（不连手机）

用户需求（txt 流程第8步）："答案与关键词是否正确、是否显示完整、是否在正确的位置
（2）听力材料是否正确（如果有的话）" → 口语训练每道小题必须核对 App 实际显示的
题干是否与脚本一致：如脚本第1大题第1小题=then，App 也必须显示 then。

验证 web_server._record_module_evidence 新增的脚本比对逻辑：
  - 按 (unit, big, stage_idx) 从脚本定位对应小题
  - App 实际题干 vs 脚本题干：包含/相似度(≥0.85) 判定
  - 一致 → 题干通过 + 写比对原因；不一致 → 题干不通过 + 明确原因
"""
import sys
import difflib

sys.path.insert(0, "src")
sys.path.insert(0, ".")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  —— {detail}" if detail and not cond else ""))


def match_stem(script_stem, app_stem):
    """复刻 web_server 的比对逻辑（包含 → 相似度≥0.85）"""
    script_stem = (script_stem or "").strip()
    app = (app_stem or "").strip()
    if not script_stem or not app:
        return False
    ok = (script_stem in app) or (app in script_stem)
    ratio = 0.0
    if not ok:
        ratio = difflib.SequenceMatcher(None, script_stem, app).ratio()
        ok = ratio >= 0.85
    return ok, ratio


# ============ 1. 读取真实脚本（U8 第1大题第1小题 = then） ============
# ★ 2026-09-10 修复：原写死微信下载目录（文件搬走后必报"解析脚本失败"）
#   → 改为项目 uploads/ 下的样本；缺失时明确跳过。
import os as _os
_root = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
_doc = _os.path.join(_root, "uploads", "260513口语训练湘少五上（U6-U10已一测）.docx")
if not _os.path.exists(_doc):
    print(f"  ⚠ 跳过（脚本样本不存在）: {_doc}")
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败（脚本样本缺失，已跳过）")
    sys.exit(0)
try:
    from parse_yingyubao_docx import parse
    qs = parse(_doc)
    u8q1s1 = next(q for q in qs if q.unit == 8 and q.big == 1 and q.stage_idx == 1)
    u8q2s1 = next(q for q in qs if q.unit == 8 and q.big == 2 and q.stage_idx == 1)
except Exception as e:
    check(f"解析脚本失败: {e}", False)
    sys.exit(1)

check("脚本 U8·大1·小1 stem=then", u8q1s1.stem == "then", f"got {u8q1s1.stem!r}")
check("脚本 U8·大2·小1 stem=句子", "worker" in u8q2s1.stem, f"got {u8q2s1.stem!r}")

# ============ 2. 匹配判定 ============
ok, _ = match_stem(u8q1s1.stem, "then")
check("App=then 与脚本一致 → 通过", ok)
ok, _ = match_stem(u8q1s1.stem, "then.")
check("App=then.（标点噪音）→ 通过", ok)
ok, _ = match_stem(u8q1s1.stem, "think")
check("App=think 与脚本then不符 → 不通过", not ok)
ok, _ = match_stem(u8q1s1.stem, "I think then we go.")
check("App=长句含then → 通过（包含）", ok)
ok, _ = match_stem(u8q1s1.stem, "apple banana")
check("App=apple banana 无关 → 不通过", not ok)
ok, ratio = match_stem(u8q2s1.stem, "My father is a worker.")
check("朗读句子 完整一致 → 通过", ok and ratio == 0.0)
ok, ratio = match_stem(u8q2s1.stem, "My mother is a teacher.")
check("朗读句子 不一致 → 不通过", not ok and ratio < 0.85, f"ratio={ratio:.2f}")

# ============ 3. 位置定位（(unit,big,stage_idx) 唯一命中） ============
def locate(unit, big, stage_idx):
    hits = [q for q in qs if q.unit == unit and q.big == big and q.stage_idx == stage_idx]
    return hits[0] if len(hits) == 1 else None

check("U8·大1·小1 唯一命中", locate(8, 1, 1) is not None)
check("U8·大2·小3 唯一命中", locate(8, 2, 3) is not None)
check("U9·大1·小1 不串到U8", locate(9, 1, 1) is not None and locate(9, 1, 1).unit == 9)

print()
if FAIL:
    print(f"结果: {len(PASS)} 通过, {len(FAIL)} 失败 ❌")
    sys.exit(1)
print(f"结果: {len(PASS)} 通过, 0 失败")
print("全部通过 ✅")
