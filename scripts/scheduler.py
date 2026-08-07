"""
英语宝 · 模块调度器
===================
批量调用各模块自动化流程：
  python scheduler.py                # 跑全部模块
  python scheduler.py 听力专项 口语训练  # 只跑指定模块
  python scheduler.py --version 湘少版 --grade 五年级上册 听力专项 单元自检
  python scheduler.py --units "听力专项:1-3,单元自检:1-5"   # 指定单元范围
  python scheduler.py 听力专项 --units "听力专项:1-3"        # 指定模块+单元

每个模块文件暴露 run_module(d, units=None) -> 题数，供本调度器统一调用。
units 支持格式：'1-3'（区间）、'1,3,5'（枚举）、[1,2]（列表）；None=默认全部。
多模块检测时：先切版本/年级（已正确则跳过），再依次执行各模块，最后汇总。
"""
import sys, os, time, importlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uiautomator2 as u2
from common.setup import switch_version_grade
from common.tools import close_ad, dismiss_global_popups
from common.logger import step_log

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
    """切换到目标版本+年级；已是目标则跳过
    ★ 调度器统一在此做一次年级切换，各模块的 run_module 不再各自切换"""
    if version and grade:
        try:
            ok = switch_version_grade(d, version, grade, skip_if_ok=True)
            if ok is True:
                step_log(f"✔ 版本/年级已是 {version} {grade}，无需切换", "info")
        except Exception as e:
            print(f"  ⚠ 切换版本/年级异常: {e}")


def run_all(module_names=None, d=None, version=None, grade=None, units=None):
    """依次跑指定模块（默认全部），返回 {模块: {q, t, ok}}

    version/grade: 目标教材版本+年级，执行前自动切换（已正确则跳过）
    units: 每个模块的单元范围映射，如 {"听力专项": "1-3", "单元自检": "1-5"}
          未指定的模块跑默认全部单元
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
    units = units or {}

    # 0. 重启 App 回主页（保证干净起点，避免停留在上个模块的答题页）
    step_log("🔄 重启 App，准备开始烹饪...", "step")
    try:
        d.press("home"); time.sleep(0.4)
        d.app_stop(APP_PACKAGE); time.sleep(0.8)
        d.app_start(APP_PACKAGE); time.sleep(3)
    except Exception as e:
        step_log(f"⚠ App 重启异常: {e}", "error")

    # 0.5 关广告（与单模块 main() 一致：先清全局弹窗 + 关广告，再操作界面，
    #     否则重启 App 后主页广告/弹窗未关，后续点坐标会点到广告上！）
    step_log("🧹 清理广告弹窗...", "step")
    try:
        for _ in range(3):
            dismiss_global_popups(d)
        close_ad(d)
    except Exception as e:
        print(f"  ⚠ 关广告异常: {e}")

    # 1. 前提：切换版本+年级（全部模块共用一次）
    step_log(f"🔧 切换版本/年级: {version} {grade}", "step")
    _switch_if_needed(d, version, grade)

    results = {}
    for i, name in enumerate(module_names):
        if name not in MODULE_MAP:
            print(f"未知模块: {name}（可选: {list(MODULE_MAP.keys())}）")
            results[name] = {"q": 0, "t": 0, "ok": False, "error": "未知模块"}
            continue

        # 该模块的单元范围（未指定 → None = 默认全部）
        module_units = units.get(name)
        units_desc = f"{module_units}" if module_units else "全部"
        step_log(f"🍳 开始烹饪第 {i+1}/{len(module_names)} 道菜: {name}（单元: {units_desc}）", "step")
        t0 = time.time()
        try:
            mod = importlib.import_module(MODULE_MAP[name])
            if module_units:
                q = mod.run_module(d, units=module_units)
            else:
                q = mod.run_module(d)
            elapsed = round(time.time() - t0)
            results[name] = {"q": q, "t": elapsed, "ok": True}
            step_log(f"✅ {name} 完成: {q} 题, 耗时 {elapsed}s", "success")
        except Exception as e:
            elapsed = round(time.time() - t0)
            results[name] = {"q": 0, "t": elapsed, "ok": False, "error": str(e)}
            step_log(f"❌ {name} 烹饪失败: {e}", "error")

        # 模块间回到主页（保证下一模块干净起点；★ 不再切换年级，调度器只在开头切一次）
        step_log(f"↩ {name} 完成，返回主页准备下一道菜…", "info")
        time.sleep(0.8)

    # 汇总
    total_q = sum(r.get("q", 0) for r in results.values())
    ok_n = sum(1 for r in results.values() if r.get("ok"))
    step_log(f"🍲 全部烹饪完成！{len(results)} 道菜, {ok_n} 道成功, 累计 {total_q} 题", "success")
    return results


def main():
    args = sys.argv[1:]
    version, grade = DEFAULT_VERSION, DEFAULT_GRADE
    names = []
    units_map = {}
    i = 0
    while i < len(args):
        if args[i] == "--version" and i + 1 < len(args):
            version = args[i + 1]; i += 2
        elif args[i] == "--grade" and i + 1 < len(args):
            grade = args[i + 1]; i += 2
        elif args[i] == "--units" and i + 1 < len(args):
            # 格式: 模块名:1-3,模块名:1-5
            raw = args[i + 1]; i += 2
            for item in raw.split(","):
                item = item.strip()
                if ":" not in item:
                    continue
                mod_name, unit_range = item.split(":", 1)
                mod_name = mod_name.strip()
                unit_range = unit_range.strip()
                if mod_name in MODULE_MAP and unit_range:
                    units_map[mod_name] = unit_range
        else:
            names.append(args[i]); i += 1

    if units_map:
        print(f"📌 单元范围: {units_map}")

    d = u2.connect()
    # 重启 App 回主页（保证干净起点）
    d.press("home"); time.sleep(0.4)
    d.app_stop(APP_PACKAGE); time.sleep(0.8)
    d.app_start(APP_PACKAGE); time.sleep(3)
    run_all(names if names else None, d, version=version, grade=grade, units=units_map)
    return 0


if __name__ == "__main__":
    sys.exit(main())
