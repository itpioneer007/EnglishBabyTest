# -*- coding: utf-8 -*-
"""监控巧记单词复跑 · 走前端同款接口 /api/inspect/state 读内存审查结果

验证目标：
  1. 审查结果题数是否随关卡【累积】（不再被后一关覆盖）
  2. 分模块是否按「巧记单词 · U1 第N关」分组
  3. 跨关卡题号是否连续唯一（3关起始号 > 2关最大号）
"""
import json, time, urllib.request, re
from collections import Counter

_t0 = time.time()
_seen = 0
_last_n = -1


def _state():
    return json.loads(urllib.request.urlopen(
        "http://127.0.0.1:5000/api/inspect/state", timeout=8).read())


for _i in range(70):          # 最多 ~23 分钟
    time.sleep(20)
    el = int(time.time() - _t0)
    try:
        st = _state()
    except Exception as e:
        print(f"[{el:4d}s] 读取失败: {e}", flush=True)
        continue
    qs = st.get("questions") or st.get("_questions") or {}
    if isinstance(qs, list):        # 兼容列表结构
        _tmp = {}
        for _q in qs:
            _tmp[_q.get("qid") or _q.get("id") or str(len(_tmp))] = _q
        qs = _tmp
    if len(qs) != _last_n:
        _last_n = len(qs)
        _grp = Counter(
            f"{q.get('module','?')}·{q.get('stage','') or '无'}" for q in qs.values())
        print(f"[{el:4d}s] ⭐ 审查结果题数={len(qs)}  分组={dict(_grp)}", flush=True)

    # 关卡里程碑
    try:
        ts = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:5000/api/status", timeout=8).read()).get("task_status") or {}
        logs = ts.get("log") or []
        for e in logs[_seen:]:
            m = e.get("msg", "")
            if re.search(r"进入\d+关|boss关|完成:|开始 Unit|闯关结束|数字关完成|巧记单词完成|多模块检测完成", m):
                print(f"        {e.get('time','')} [{e.get('level','')}] {m[:110]}", flush=True)
        _seen = len(logs)
        if not ts.get("running") and ts.get("end_time"):
            print(f">>> 任务结束（{el}s）", flush=True)
            break
    except Exception:
        pass

    # 达到 3 关 → 跨关卡唯一性可判定
    try:
        _all = " ".join((e.get("msg") or "") for e in (ts.get("log") or []))
        if "3关 完成" in _all:
            print(">>> 已跑完 3 个关卡 → 可判定跨关卡题号是否唯一", flush=True)
            break
    except Exception:
        pass

print("监控结束", flush=True)
