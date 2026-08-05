"""
英语宝 · 模块调度器
===================
批量调用各模块自动化流程：
  python scheduler.py                # 跑全部模块
  python scheduler.py 听力专项 口语训练  # 只跑指定模块
  python scheduler.py --version 湘少版 --grade 五年级上册 听力专项 单元自检

每个模块文件暴露 run_module(d) -> 题数，供本调度器统一调用。
多模块检测时：先切版本/年级（已正确则跳过），再依次执行各模块，最后汇总。
"""
import sys, os, time, importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uiautomator2 as u2
from common.setup import switch_version_grade
from common.tools import close_ad, dismiss_global_popups

# ═══════════ 模块注册表：新增模块只需在此加一行 ═══════════
MODULE_MAP = {
    "听力专项": "modules.听力专项",
    "口语训练": "modules.口语训练",
    "单元自检": "modules.单元自检",
    "知识过关": "modules.知识过关",
    "语音评测": "modules.语音评测",
    "巧记单词": "modules.巧记单词",
}

# 年级/版本（进入每个模块前确认一次）
APP_PACKAGE = "com.dinoenglish.yyb"
DEFAULT_GRADE = "五年级上册"
DEFAULT_VERSION = "湘少版"


def _switch_if_needed(d, version, grade):
    """切换到目标版本+年级；已是目标则跳过"""
    if version and grade:
        try:
            switch_version_grade(d, version, grade, skip_if_ok=True)
        except Exception as e:
            print(f"  ⚠ 切换版本/年级异常: {e}")


def run_all(module_names=None, d=None, version=None, grade=None):
    """依次跑指定模块（默认全部），返回 {模块: {q, t, ok}}

    version/grade: 目标教材版本+年级，执行前自动切换（已正确则跳过）
    """
    if d is None:
        d = u2.connect()
        print("设备已连接")

    if module_names is None:
        module_names = list(MODULE_MAP.keys())
    if version is None:
        version = DEFAULT_VERSION
    if grade is None:
        grade = DEFAULT_GRADE

    # 0. 重启 App 回主页（保证干净起点，避免停留在上个模块的答题页）
    try:
        d.press("home"); time.sleep(1)
        d.app_stop(APP_PACKAGE); time.sleep(2)
        d.app_start(APP_PACKAGE); time.sleep(8)
    except Exception as e:
        print(f"  ⚠ App 重启异常: {e}")

    # 0.5 关广告（与单模块 main() 一致：先清全局弹窗 + 关广告，再操作界面，
    #     否则重启 App 后主页广告/弹窗未关，后续点坐标会点到广告上！）
    try:
        for _ in range(3):
            dismiss_global_popups(d)
        close_ad(d)
    except Exception as e:
        print(f"  ⚠ 关广告异常: {e}")

    # 1. 前提：切换版本+年级（全部模块共用一次）
    print(f"前提设置: {version} {grade}")
    _switch_if_needed(d, version, grade)

    results = {}
    for name in module_names:
        if name not in MODULE_MAP:
            print(f"未知模块: {name}（可选: {list(MODULE_MAP.keys())}）")
            results[name] = {"q": 0, "t": 0, "ok": False, "error": "未知模块"}
            continue

        print(f"{'='*50}")
        print(f"开始模块: {name}")
        print(f"{'='*50}")
        t0 = time.time()
        try:
            mod = importlib.import_module(MODULE_MAP[name])
            q = mod.run_module(d)
            results[name] = {"q": q, "t": round(time.time() - t0), "ok": True}
        except Exception as e:
            print(f"{name} 异常: {e}")
            results[name] = {"q": 0, "t": round(time.time() - t0), "ok": False, "error": str(e)}

        # 模块间回到主页（保证下一模块干净起点）
        time.sleep(2)

    # 汇总
    print(f"{'='*50}")
    print("调度汇总")
    print(f"{'='*50}")
    total_q = 0
    for name, r in results.items():
        status = "OK" if r.get("ok") else "FAIL"
        print(f"  [{status}] {name}: {r['q']} 题, {r['t']}s")
        total_q += r["q"]
    print(f"  总模块: {len(results)} | 总题数: {total_q}")
    return results


def main():
    args = sys.argv[1:]
    version, grade = DEFAULT_VERSION, DEFAULT_GRADE
    names = []
    i = 0
    while i < len(args):
        if args[i] == "--version" and i + 1 < len(args):
            version = args[i + 1]; i += 2
        elif args[i] == "--grade" and i + 1 < len(args):
            grade = args[i + 1]; i += 2
        else:
            names.append(args[i]); i += 1

    d = u2.connect()
    # 重启 App 回主页（保证干净起点）
    d.press("home"); time.sleep(1)
    d.app_stop(APP_PACKAGE); time.sleep(2)
    d.app_start(APP_PACKAGE); time.sleep(8)
    run_all(names if names else None, d, version=version, grade=grade)
    return 0


if __name__ == "__main__":
    sys.exit(main())
