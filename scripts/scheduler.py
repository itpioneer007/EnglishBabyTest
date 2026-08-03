"""
英语宝 · 模块调度器
===================
批量调用各模块自动化流程：
  python scheduler.py               # 跑全部模块
  python scheduler.py 听力专项       # 只跑指定模块

每个模块文件暴露 run_module(d) -> 题数，供本调度器统一调用。
"""
import sys, os, time, importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uiautomator2 as u2

# ═══════════ 模块注册表：新增模块只需在此加一行 ═══════════
MODULE_MAP = {
    "听力专项": "modules.听力专项",
    # "单词听写": "modules.单词听写",   # 迁移后取消注释
    # "单元自检": "modules.单元自检",
    # "听力训练": "modules.听力训练",
    # "单词学习": "modules.单词学习",
    # "口语训练": "modules.口语训练",
}

# 年级/版本（进入每个模块前确认一次）
APP_PACKAGE = "com.dinoenglish.yyb"
GRADE_LEVEL = "五年级上册"
BOOK_VERSION = "湘少版"


def run_all(module_names=None, d=None):
    """依次跑指定模块（默认全部），返回 {模块: 题数}"""
    if d is None:
        d = u2.connect()
        print("✅ 设备已连接")

    if module_names is None:
        module_names = list(MODULE_MAP.keys())

    results = {}
    for name in module_names:
        if name not in MODULE_MAP:
            print(f"❌ 未知模块: {name}（可选: {list(MODULE_MAP.keys())}）")
            continue
        print(f"\n{'='*50}\n🚀 开始模块: {name}\n{'='*50}")
        try:
            mod = importlib.import_module(MODULE_MAP[name])
            q = mod.run_module(d)
            results[name] = q
        except Exception as e:
            print(f"❌ {name} 异常: {e}")
            results[name] = 0
        # 模块间回到主页
        time.sleep(2)

    # 汇总
    print(f"\n{'='*50}\n📊 调度汇总\n{'='*50}")
    for name, q in results.items():
        print(f"  {name}: {q} 题")
    print(f"  总模块: {len(results)} | 有题: {sum(1 for v in results.values() if v > 0)}")
    return results


def main():
    args = sys.argv[1:]
    d = u2.connect()
    # 重启 App 回主页（保证干净起点）
    d.press("home"); time.sleep(1)
    d.app_stop(APP_PACKAGE); time.sleep(2)
    d.app_start(APP_PACKAGE); time.sleep(8)
    run_all(args if args else None, d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
