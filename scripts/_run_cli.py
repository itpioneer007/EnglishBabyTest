# -*- coding: utf-8 -*-
"""终端版"网页运行"入口：与 http://localhost:5000 的「开始运行」走完全相同的代码路径
（scheduler.run_all → 切版本年级 → 关广告 → 模块 run_module → engine.run_single_module）。

用法示例（在 Windows 终端 CMD 里）：
    cd /d "C:/Users/yangj/Desktop/EnglishBabyTest-yangjiangliu"
    D:\Drivers\Audio\python.exe scripts/_run_cli.py --version "湘少版（2024审定）" --grade "五年级上册" --module "听力专项" --units "1"

多个模块 / 练测分开：
    ... --module "听力专项" --module "单元自检" --units "1-3" --test-units "1"
"""
import argparse
import os
import sys
import time

BASE = r"C:\Users\yangj\Desktop\EnglishBabyTest-yangjiangliu"
SCRIPTS = os.path.join(BASE, "scripts")
sys.path.insert(0, SCRIPTS)

import scheduler  # 复用网页同一条运行路径


def main():
    ap = argparse.ArgumentParser(description="英语宝 终端检测运行（与网页同路径）")
    ap.add_argument("--version", required=True, help="教材版本，如 湘少版 / 湘少版（2024审定）")
    ap.add_argument("--grade", required=True, help="年级，如 五年级上册 / 三年级上册")
    ap.add_argument("--module", action="append", dest="modules",
                    default=None, help="要跑的模块，可重复；默认 听力专项")
    ap.add_argument("--units", default="1", help="练习单元范围，如 1 / 1-3 / 全部(留空)")
    ap.add_argument("--test-units", default=None,
                    help="听力专项·测试单元范围（不传=只跑练习）。传 NONE 表示只跑练习")
    args = ap.parse_args()

    modules = args.modules or ["听力专项"]

    # 组装 units 映射（与网页 /api/modules/run 一致）
    units = {}
    for m in modules:
        if m == "听力专项":
            units["听力专项"] = args.units if args.units else "1"
            if args.test_units is not None:
                units["听力专项_测试"] = args.test_units
        else:
            units[m] = args.units

    print(f"\n==== 终端检测启动 ====")
    print(f"  版本 : {args.version}")
    print(f"  年级 : {args.grade}")
    print(f"  模块 : {modules}")
    print(f"  单元 : {units}")
    print(f"  路径 : scheduler.run_all（与网页完全一致）\n")

    t0 = time.time()
    res = scheduler.run_all(
        module_names=modules,
        version=args.version,
        grade=args.grade,
        units=units,
    )
    print(f"\n==== 运行结束 ({time.time()-t0:.0f}s) ====")
    print("RESULT:", res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
