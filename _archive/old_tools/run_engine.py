"""
入口脚本（run_engine.py）
========================
用法:
  python scripts/run_engine.py                          # 默认: 听力专项
  python scripts/run_engine.py "听力专项,单词学习"       # 指定模块
  python scripts/run_engine.py "听力专项" --report       # 跑完生成报告
  python scripts/run_engine.py "听力专项" -v "湘少版(2024审定)" -g "六年级上册"
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from engine_runner import run_batch

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="英语宝自动化引擎")
    parser.add_argument("modules", nargs="?", default="听力专项",
                        help="模块列表，逗号分隔")
    parser.add_argument("--report", "-r", action="store_true",
                        help="生成 HTML 报告")
    parser.add_argument("-v", "--version", default="湘少版(2024审定)",
                        help="目标版本")
    parser.add_argument("-g", "--grade", default="六年级上册",
                        help="目标年级")
    args = parser.parse_args()

    module_list = [m.strip() for m in args.modules.split(",") if m.strip()]

    run_batch(module_list,
              target_grade=args.grade,
              target_version=args.version,
              with_report=args.report)
