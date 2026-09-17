# -*- coding: utf-8 -*-
"""真机端到端：直接在当前停留的字母补全题上跑 engine._handle_letter_fill。

用途：验证「点字母块 → 填空位 → 点检查 → 下一题」整条链路（不只是解析）。
会真实作答这一题（设备当前停在 15/40，属上次中断的练习会话）。
"""
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import uiautomator2 as u2  # noqa: E402
import engine  # noqa: E402

OUT = os.path.join(ROOT, "tmp_gen", "probe_letter_e2e.txt")
log = []


def w(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    log.append(s)


def snap(d):
    x = d.dump_hierarchy()
    return {
        "qno": re.findall(r'text="(\d+\s*/\s*\d+)"', x),
        "slot": [m.group(1) for m in re.finditer(
            r'text="([^"]*)"[^>]*resource-id="[^"]*select_tv"', x)],
        "检查": 'text="检查"' in x,
        "下一题": 'text="下一题"' in x,
    }


def main():
    d = u2.connect()
    w("跑前:", snap(d))
    t0 = time.time()
    ok = engine._handle_letter_fill(d, {})
    w(f"_handle_letter_fill 返回 {ok}，耗时 {time.time()-t0:.1f}s")
    w("推断记录:", engine._LAST_LETTER_FILL)
    time.sleep(1.0)
    w("跑后:", snap(d))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    main()
