# -*- coding: utf-8 -*-
"""逐个跑全部 mock/回归测试，汇总结果。"""
import os, glob, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
# ★ 2026-10-19：不再写死某个人的 Python 安装路径。用当前解释器即可 ——
#   测试本来就该用"跑得起来的那一个"来跑。需要指定时用 YYB_PYTHON。
PY = os.environ.get("YYB_PYTHON", "").strip() or sys.executable

pats = ["scripts/tests/*.py", "mock_test_*.py", "verify_*.py", "tools/test_*.py"]
files = []
for p in pats:
    files += glob.glob(os.path.join(ROOT, p))
files = sorted(set(f for f in files if os.path.basename(f) != "_run_all_tests.py"))

ok, bad = [], []
for f in files:
    rel = os.path.relpath(f, ROOT)
    try:
        r = subprocess.run([PY, f], cwd=ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="ignore", timeout=600)
    except subprocess.TimeoutExpired:
        print("TIMEOUT  %s" % rel)
        bad.append((rel, "timeout"))
        continue
    out = (r.stdout or "") + (r.stderr or "")
    tail = [l for l in out.splitlines() if l.strip()][-1:] or [""]
    status = "OK   " if r.returncode == 0 else "FAIL "
    print("%s %-58s %s" % (status, rel, tail[0][:90]))
    (ok if r.returncode == 0 else bad).append((rel, tail[0][:150]))

print("\n" + "=" * 70)
print("PASS %d / FAIL %d" % (len(ok), len(bad)))
for rel, t in bad:
    print("  FAIL", rel, "::", t)
