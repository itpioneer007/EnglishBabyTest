# -*- coding: utf-8 -*-
"""触发一次模块检测（直接调用前端同款后端 API），并轮询日志到结束。

用法: python tools/run_module_api.py [<版本> <年级> <模块:单元> ...]

⚠ 这会**真的**驱动设备跑一遍检测（重启 App / 逐题操作 / 调 LLM），不是 dry-run。
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


USAGE = """用法:
  python tools/run_module_api.py                                  # 默认 payload
  python tools/run_module_api.py <版本> <年级> <模块:单元> [<模块:单元> ...]

例:
  python tools/run_module_api.py "教科版（2024审定）" 五年级上册 口语训练:4

⚠ 这会**真的**驱动设备跑一遍检测（重启 App / 逐题操作 / 调 LLM），不是 dry-run。
   脚本会自动在 uploads/ 里挑文件名含模块名的 docx 挂 docxMap（等价前端传参），
   否则服务端拿不到脚本、脚本层检查一条都不会跑。
"""


def build_payload(argv):
    """argv: [version, grade, "模块名:单元", ...]（可省略，用默认）。"""
    if not argv:
        return DEFAULT_PAYLOAD
    # ★ 2026-09-20 护栏：以前 `--help` 会被当成**版本名**，直接触发一次真实运行
    #   （实测误跑 "--help / 六年级上册 / 口语训练U1 + 单元自检U1"：状态文件被清空、
    #   App 被重启、`/api/status` 还被阻塞到超时）。任何以 "-" 开头的参数一律拒绝，
    #   绝不允许"只是敲了个 --help"就动设备。
    _bad = [a for a in argv if a.startswith("-")]
    if _bad:
        raise SystemExit(f"[拒绝] 无法识别的参数 {_bad}（本工具不接受选项参数）\n\n{USAGE}")
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
    """读 /api/status。

    ★ 2026-09-21：/api/status 在调度器忙（设备操作持有锁）时会阻塞到 6s 以上，
      旧实现直接让 urlopen 抛 timeout → **轮询线程整个崩掉**，而设备上的任务还在跑：
      用户看到的是"工具报错退出、任务却还在动"，日志也断了。改为长超时 + 重试。
    """
    _last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(BASE + "/api/status", timeout=30) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:      # noqa: BLE001
            _last = e
            time.sleep(1.0)
    raise _last


_VERSION_FILE_KW = {
    "湘少": ("湘少",), "湘鲁": ("湘鲁", "新湘鲁"), "教科": ("教科",),
    "人教": ("人教", "PEP", "pep"), "外研": ("外研",), "译林": ("译林",),
    "教研": ("教研",),
}
_GRADE_FILE_KW = {
    "一年级上册": ("一上", "一年级上"), "一年级下册": ("一下", "一年级下"),
    "二年级上册": ("二上", "二年级上"), "二年级下册": ("二下", "二年级下"),
    "三年级上册": ("三上", "三年级上"), "三年级下册": ("三下", "三年级下"),
    "四年级上册": ("四上", "四年级上"), "四年级下册": ("四下", "四年级下"),
    "五年级上册": ("五上", "五年级上"), "五年级下册": ("五下", "五年级下"),
    "六年级上册": ("六上", "六年级上"), "六年级下册": ("六下", "六年级下"),
}


def auto_docx_map(mods, version: str = "", grade: str = ""):
    """为每个模块在 uploads/ 里自动挑一份脚本（前置前端会传 docxMap）。

    ★ 2026-09-20 新增。此前本工具不传 docxMap → 服务端 `_GLOBAL_DOCX_MAP` 为空 →
      日志永远打「无匹配脚本 → 仅基础完整性检查」，**脚本层检查（题目内容/关键词/
      知识点/答案↔关键词）一条都不会跑**，于是"脚本明明有问题却查不出来"在 CLI
      复跑时根本复现不了（只有走前端才带上 docxMap）。

    ★ 2026-09-20（用户反馈：跑教科六上 U6 却挂了五上 U4-7 脚本，报出一堆没测过的题）
      匹配规则对齐前端四要素：模块 + 版本 + 年级（单元维度由服务端按单元提取）。
      - 第一轮：模块关键词 ∧ 版本关键词 ∧ 年级关键词 全命中 → 取最后修改的
      - 无命中 → **宁缺毋滥**：不挂脚本（服务端按"无匹配脚本 → 仅基础完整性"处理），
        绝不拿错年级/版本的脚本去比对（那会报出根本没测过的题）
    """
    import glob
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = glob.glob(os.path.join(root, "uploads", "*.docx"))
    ver_kws = []
    for v, ks in _VERSION_FILE_KW.items():
        if v in str(version or ""):
            ver_kws = list(ks)
            break
    grade_kws = list(_GRADE_FILE_KW.get(str(grade or "").strip(), ()))
    out = {}
    for m in mods:
        name = m.get("name", "")
        if not name:
            continue
        cands = [f for f in files if name in os.path.basename(f)]
        if not cands:
            continue
        base = os.path.basename
        full = [f for f in cands
                if (not ver_kws or any(k in base(f) for k in ver_kws))
                and (not grade_kws or any(k in base(f) for k in grade_kws))]
        if not full:
            print(f"[warn] {name}：uploads/ 里有 {len(cands)} 个含模块名的脚本，"
                  f"但没有同时匹配 版本={version or '?'} 年级={grade or '?'} 的"
                  f"→ 不挂脚本（避免拿错脚本乱报）")
            continue
        full.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        out[name] = os.path.basename(full[0])
    return out


def main():
    argv = sys.argv[1:]
    # ★ 先处理 --help：必须早于任何 API 调用（否则又会"看一眼帮助就开跑"）
    if any(a in ("-h", "--help", "help") for a in argv):
        print(USAGE)
        return 0
    payload = build_payload(argv)
    # ★ 2026-09-20 新增前置检查：已有任务在跑时拒绝叠加
    #   （两个任务抢同一台设备 → 互相点错页面、证明题数/截图全乱，
    #    而日志看起来又"都在正常跑"）
    try:
        _cur = status()
        if _cur.get("running"):
            print(f"[拒绝] 已有任务在跑（{_cur.get('current_task')}，"
                  f"start={_cur.get('start_time')}）→ 先 /api/modules/stop 或等它结束。")
            return 1
    except Exception as e:
        print(f"[warn] 读 /api/status 失败（服务没起？）: {e}")
    # 自动挂脚本（与前端 docxMap 等价），让脚本层检查真正跑起来
    # ★ 2026-09-20：带上版本/年级做四要素匹配，杜绝"六上挂五上脚本"
    try:
        dm = auto_docx_map(payload.get("modules") or [],
                           version=payload.get("version", ""),
                           grade=payload.get("grade", ""))
        if dm:
            payload["docxMap"] = dm
    except Exception as e:
        print(f"[warn] 自动匹配脚本失败: {e}")
    print(f"[payload] {json.dumps(payload, ensure_ascii=False)}")
    code, body = post("/api/modules/run", payload)
    print(f"[trigger] HTTP {code} {body[:300]}")
    if code != 200:
        return 1

    seen = 0
    idle = 0
    _poll_err = 0
    for _ in range(600):          # 最多轮询 ~20 分钟
        time.sleep(2)
        try:
            st = status()["task_status"]
        except Exception as e:      # noqa: BLE001 —— 单次读状态失败不该终止监控
            _poll_err += 1
            if _poll_err <= 3:
                print(f"[warn] 读 /api/status 失败（第{_poll_err}次，任务可能仍在跑）: {e}")
            continue
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
