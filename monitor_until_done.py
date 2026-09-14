# -*- coding: utf-8 -*-
"""等待巧记单词真机任务结束（结束后再重启 web_server 加载全部改动）

每 30s 打印一次进度；running=False 且已写 end_time → 退出。
"""
import json, time, urllib.request, re
from collections import Counter

_t0 = time.time()
_last = -1
for _i in range(70):          # 最多 ~35 分钟
    time.sleep(30)
    el = int(time.time() - _t0)
    try:
        st = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:5000/api/inspect/state", timeout=8).read())
    except Exception as e:
        print(f"[{el:4d}s] state 读取失败: {e}", flush=True)
        st = {}
    qs = st.get("questions") or {}
    grp = Counter(f"{q.get('module','?')}·{q.get('stage','') or '无'}"
                  for q in qs.values()) if qs else {}
    try:
        ts = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:5000/api/status", timeout=8).read()).get("task_status") or {}
    except Exception:
        ts = {}
    n = len(qs)
    if n != _last:
        _last = n
        print(f"[{el:4d}s] 审查结果={n} 条 | 分组={dict(grp)}", flush=True)
    if not ts.get("running") and ts.get("end_time"):
        print(f">>> 任务结束（{el}s）", flush=True)
        # 打印关卡与单元汇总
        for e in (ts.get("log") or []):
            m = e.get("msg", "")
            if re.search(r"进入\d+关|boss关|完成:|闯关结束|巧记单词完成|多模块检测完成|解析脚本", m):
                print(f"    {e.get('time','')} [{e.get('level','')}] {m[:110]}", flush=True)
        break
else:
    print(">>> 等待超时（任务仍在跑）", flush=True)
print("等待结束", flush=True)
