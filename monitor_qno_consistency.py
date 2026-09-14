# -*- coding: utf-8 -*-
"""真机复跑监控：验证「题数口径一致」+「按关卡分组」+「LLM 故障降级不崩」

监控直到任务结束或超时，输出：
  - 审查结果条数曲线（应按关卡累积，不覆盖）
  - 分组明细（巧记单词·U1 第N关）
  - 关卡级节点（进入N关 / N关完成 X 题）
  - ★ 一致性校验：每关「完成 X 题」是否等于该关卡分组下的审查结果条数
"""
import json
import re
import sys
import time
import urllib.request
from collections import Counter

BASE = "http://127.0.0.1:5000"
MAX_SEC = int(sys.argv[1]) if len(sys.argv) > 1 else 1800


def _get(path, timeout=12):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=timeout).read())


def _inspect():
    d = _get("/api/inspect/state")
    qs = d.get("questions") or {}
    grp = Counter(f"{q.get('module','?')}·{q.get('stage','') or '无'}" for q in qs.values())
    return len(qs), grp


def _norm(lv):
    """关卡标签归一化。

    ⚠ 两处来源用词不同，必须归一后才能比对（否则会误报"不一致"）：
      模块日志写「1关 / boss关」，审查结果分组写「第1关 / boss关」。
    """
    lv = str(lv).strip()
    if lv in ("boss", "boss关", "BOSS关"):
        return "boss关"
    m = re.search(r"(\d+)", lv)
    return f"第{m.group(1)}关" if m else lv


def _levels_from_group(grp):
    """从分组名提取每关题数 {归一化关卡标签: 条数}"""
    out = {}
    for k, v in grp.items():
        m = re.match(r"^巧记单词·U(\d+)\s+(.+)$", k)
        if m:
            out[_norm(m.group(2))] = v
    return out


print(f"{'时间':10s} {'审查结果':>6s}  分组明细")
print("-" * 78)

t0 = time.time()
seen = 0
_last_n = -1
_level_done = {}   # 关卡标签 -> 模块自报题数
_milestones = []

while time.time() - t0 < MAX_SEC:
    try:
        st = _get("/api/status")
        ts = st.get("task_status") or {}
    except Exception as e:
        print(f"  (status 读取失败: {str(e)[:50]})")
        time.sleep(8)
        continue

    logs = ts.get("log") or []
    for e in logs[seen:]:
        m = e.get("msg", "")
        # 关卡级节点
        if re.search(r"🎮 进入|关 完成:|数字关完成|闯关结束|巧记单词完成|已生成解析脚本|多模块检测完成", m):
            _milestones.append(f"{e.get('time','')} {m[:100]}")
            _mm = re.search(r"(boss关|\d+关)\s*完成:\s*(\d+)\s*题", m)
            if _mm:
                _level_done[_norm(_mm.group(1))] = int(_mm.group(2))
        # LLM 降级提示
        if "LLM" in m and ("熔断" in m or "不可用" in m or "额度" in m):
            _milestones.append(f"{e.get('time','')} [LLM] {m[:110]}")
    seen = len(logs)

    try:
        n, grp = _inspect()
    except Exception:
        n, grp = None, {}

    if n is not None and n != _last_n:
        _last_n = n
        _detail = " ".join(f"{k.split(chr(183))[-1].strip()}:{v}" for k, v in sorted(grp.items()))
        print(f"{time.strftime('%H:%M:%S'):10s} {n:>6d}  {_detail}")
    elif n is not None and int(time.time() - t0) % 120 < 8:
        print(f"{time.strftime('%H:%M:%S'):10s} {n:>6d}  (无变化)")

    if not ts.get("running") and ts.get("end_time"):
        print(f"\n>>> 任务结束（耗时 {time.time()-t0:.0f}s）")
        break
    time.sleep(7)
else:
    print(f"\n>>> 监控 {MAX_SEC}s 截止（任务可能仍在跑）")

# ---------- 汇总 ----------
print("\n" + "=" * 78)
print("关卡级节点")
print("=" * 78)
for m in _milestones:
    print("  ", m)

print("\n" + "=" * 78)
print("★ 一致性校验：模块自报题数 vs 审查结果条数（按关卡）")
print("=" * 78)
try:
    n, grp = _inspect()
    _lv_group = _levels_from_group(grp)
    _keys = sorted(set(list(_level_done) + list(_lv_group)))
    _ok = True
    for k in _keys:
        _a = _level_done.get(k)
        _b = _lv_group.get(k)
        _flag = "✅" if (_a is not None and _b == _a) else ("⚠" if _a is not None else "·")
        if _a is not None and _b != _a:
            _ok = False
        print(f"  {_flag} {k:8s} 模块报告={_a if _a is not None else '-':>4}  审查结果={_b if _b is not None else '-':>4}")
    print()
    print(f"  审查结果总计: {n} 条 | 分组数: {len(grp)}")
    print(f"  结论: {'✅ 每一关的题数完全一致' if _ok else '⚠ 存在不一致（见上）'}")
except Exception as e:
    print("  校验失败:", e)
