"""复现用户的批量任务：scheduler.run_all(听力专项, units={"听力专项":"1","听力专项_测试":"1"})
抓完整日志，定位测试模块在哪一步停止。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uiautomator2 as u2
import scheduler

SERIAL = "SKSCIF4T7PFMQS5X"


def main():
    d = u2.connect(SERIAL)
    print("✅ 设备已连接")

    print("\n===== 调度器 run_all 开始（复现用户参数）=====\n")
    try:
        results = scheduler.run_all(
            ["听力专项"],
            d=d,
            version="湘少版",
            grade="五年级上册",
            units={"听力专项": "1", "听力专项_测试": "1"},
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        results = {}
    print(f"\n===== 调度器返回: {results} =====")
    total = sum(r.get("q", 0) for r in results.values())
    print(f"===== 累计: {total} 题 =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())
