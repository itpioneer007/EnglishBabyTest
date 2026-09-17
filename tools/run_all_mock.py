# -*- coding: utf-8 -*-
"""跑本项目全部 mock_test_*.py，汇总结果（专用 Python，避免 shell 缺 grep）。"""
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

rows = []
for f in sorted(glob.glob(os.path.join(ROOT, "mock_test_*.py"))):
    try:
        r = subprocess.run([PY, "-u", f], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=600)
        out = (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        rows.append((os.path.basename(f), "TIMEOUT/ERR", repr(e)[:80]))
        continue
    m = re.search(r"^Ran (\d+) tests?", out, re.M)
    n = m.group(1) if m else "?"
    if re.search(r"^OK", out, re.M):
        status = "OK"
    elif "FAILED" in out:
        status = "FAILED"
    else:
        status = "NON-UNITTEST(exit=%s)" % r.returncode
    rows.append((os.path.basename(f), f"{n} tests", status))

lines = ["%-52s %-10s %s" % r for r in rows]
lines.append("")
lines.append("FAILED 明细：")
for f, n, s in rows:
    if s != "OK":
        lines.append("  - %s (%s)" % (f, s))

txt = "\n".join(lines)
open(os.path.join(ROOT, "tmp_gen", "_all_mock.txt"), "w", encoding="utf-8").write(txt)
print(txt)
