# -*- coding: utf-8 -*-
"""2026-09-10 巧记单词"跑完 6 关审查结果只有 15 题"修复验证（统一入口）

根因：审查结果 qid = `auto-Q{页面题号}`，而**每个关卡的页面题号都从 1 重新开始**
     → 后一关的同号题覆盖前一关（真实数据实测：6 关 101 题最后只剩 20 条）。

真实用例在项目根的 `mock_test_qno_unique.py`（51 个用例：真实执行 `_answer_loop`
跑 3 关验证题号全局唯一 / 跨阶段冲突防御 / 证据合并 / 题干清洗 / stage 过滤）。
本文件只是让 `scripts/tests/` 目录下也能发现并运行该测试。
"""
import os
import subprocess
import sys

_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_target = os.path.join(_root, "mock_test_qno_unique.py")
if not os.path.exists(_target):
    print(f"⚠ 未找到测试脚本，跳过: {_target}")
    sys.exit(0)
sys.exit(subprocess.call([sys.executable, _target], cwd=_root))
