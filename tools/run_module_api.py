# -*- coding: utf-8 -*-
"""触发一次模块检测（直接调用前端同款后端 API），并轮询日志到结束。

用法: python tools/_run_and_watch.py
"""
import json
import sys
import time
import urllib.request

# 实时输出：被重定向到文件时 Python 默认块缓冲，会导致"看不到进展"
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

BASE = "http://127.0.0.1:5000"
# 默认：口语训练 U1（验证无答案题不产脚本）+ 单元自检 U1（验证有答案题出脚本并查原文错误）
DEFAULT_PAYLOAD = {
    "version": "湘少版(2024审定)",
    "grade": "六年级上册",
    "modules": [{"name": "口语训练", "units": "1"},
                {"name": "单元自检", "units": "1"}],
}


def build_payload(argv):
    """argv: [version, grade, "模块名:单元", "模块名:单元", ...]（可省略，用默认）"""
    if not argv:
        return DEFAULT_PAYLOAD
    version = argv[0] if len(argv) > 0 else DEFAULT_PAYLOAD["version"]
    grade = argv[1] if len(argv) > 1 else DEFAULT_PAYLOAD["grade"]
    mods = []
    for spec in argv[2:]:
        name, _, units = spec.partition(":")
        mods.append({"name": name.strip(), "units": (units or "1").strip()})
    return {"version": version, "grade": grade,
            "modules": mods or DEFAULT_PAYLOAD["modules"]}


def post(path, body):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def status():
    with urllib.request.urlopen(BASE + "/api/status", timeout=6) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def main():
    payload = build_payload(sys.argv[1:])
    print(f"[payload] {json.dumps(payload, ensure_ascii=False)}")
    code, body = post("/api/modules/run", payload)
    print(f"[trigger] HTTP {code} {body[:300]}")
    if code != 200:
        return 1

    seen = 0
    idle = 0
    for _ in range(600):          # 最多轮询 ~20 分钟
        time.sleep(2)
        st = status()["task_status"]
        logs = st.get("log", [])
        for item in logs[seen:]:
            t = item.get("time", "")
            lv = (item.get("level") or "info").upper()
            print(f"{t} [{lv}] {item.get('msg','')}")
        if len(logs) > seen:
            seen = len(logs)
            idle = 0
        else:
            idle += 1
        if not st.get("running") and seen:
            print(f"[done] running=False, end_time={st.get('end_time')}")
            return 0
        if not st.get("running") and idle > 5 and not seen:
            print("[done] 任务未启动或无日志")
            return 1
    print("[timeout] 轮询超时")
    return 2


if __name__ == "__main__":
    sys.exit(main())
