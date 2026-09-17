# -*- coding: utf-8 -*-
"""探针2：在已填好的字母补全题上点「检查」，观察答对/答错与跳转方式。

用途：验证「首字母+中文提示 → by」这条推理是否正确（App 是最终裁判）。
"""
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import uiautomator2 as u2  # noqa: E402

OUT = os.path.join(ROOT, "tmp_gen", "probe_letter_check.txt")
log = []


def w(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    log.append(s)


def brief(xml):
    txts = [t for t in re.findall(r'text="([^"]*)"', xml) if t.strip()]
    return txts[:14]


def main():
    d = u2.connect()
    x = d.dump_hierarchy()
    w("检查前:", brief(x))
    has_check = 'text="检查"' in x
    w("有「检查」按钮:", has_check)
    if not has_check:
        w("无检查按钮，退出")
        return
    d(text="检查").click()
    w("已点检查")
    for i in range(10):
        time.sleep(1.0)
        x = d.dump_hierarchy()
        t = brief(x)
        qno = re.findall(r'text="(\d+\s*/\s*\d+)"', x)
        btns = [v for v in ("检查", "下一题", "查看报告", "确定", "继续答题") if f'text="{v}"' in x]
        w("  +%ds 题号=%s 按钮=%s 文字=%s" % (i + 1, qno, btns, t[:8]))
        if "下一题" in btns or (qno and qno[0] != "14/40"):
            break
    x = d.dump_hierarchy()
    w("-" * 60)
    w("最终页面文字:", brief(x))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    main()
