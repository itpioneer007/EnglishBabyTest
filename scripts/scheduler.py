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


def run_all(module_names=None, d=None, version=None, grade=None, units=None, stop_check=None):
    """依次跑指定模块（默认全部），返回 {模块: {q, t, ok}}

    version/grade: 目标教材版本+年级，执行前自动切换（已正确则跳过）
    units: 每个模块的单元范围映射，如 {"听力专项": "1-3", "单元自检": "1-5"}
          未指定的模块跑默认全部单元
    stop_check: 可选回调，每次模块循环前调用；返回 True 表示收到停止请求 → 中断
    """
    # ★ 全局 u2 操作超时：默认 300s，设备断连时每个操作挂 5 分钟 = 看起来"卡死"
    #   设为 15s，设备异常时快速失败并报错
    try:
        import uiautomator2 as _u2
        _u2.HTTP_TIMEOUT = 15
        _u2.WAIT_FOR_DEVICE_TIMEOUT = 10
    except Exception:
        pass

    if d is None:
        # ★ 设备就绪检查：u2.connect 在没设备时可能长时间挂起，先快速检测
        try:
            from common.device import device_ok
            if not device_ok():
                raise RuntimeError("设备未连接或离线")
        except ImportError:
            pass
        d = u2.connect()
        print("设备已连接")

    # ★ 无论 d 是否传入，都做一次快速设备探活（u2 操作失败会挂起，不如提前检查）
    try:
        info = d.info
        if not info:
            raise RuntimeError("设备离线")
    except Exception as e:
        step_log(f"❌ 设备不可用: {e}，请先连接设备再开始", "error")
        return {name: {"q": 0, "t": 0, "ok": False, "error": f"设备不可用: {e}"} for name in (module_names or MODULE_MAP.keys())}

    if module_names is None:
        module_names = list(MODULE_MAP.keys())
    if version is None:
        version = DEFAULT_VERSION
    if grade is None:
        grade = DEFAULT_GRADE
    units = units or {}

    # 0. 重启 App 回主页（保证干净起点，避免停留在上个模块的答题页）
    step_log("🔄 重启 App，准备开始检测...", "step")
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
        # ★ 广告是延迟加载的（实测重启后 4-6s 才出现 fl_ad_container/iv_close）：
        #   先轮询等广告出现再关，最多等 6s，避免关广告时广告还没加载出来
        import re as _re2
        for _wait in range(3):
            try:
                _xml_now = d.dump_hierarchy()
                if 'fl_ad_container' in _xml_now or 'iv_close' in _xml_now or '关闭' in _xml_now:
                    break
            except Exception:
                pass
            time.sleep(2)
        # ★ 优化：dismiss 已用一次 dump 判断，最多 2 轮（有弹窗才点，无弹窗立刻返回）
        for _ in range(2):
            if not dismiss_global_popups(d):
                break
        close_ad(d)
        # 广告可能一次关不完（有多个），再确认一次
        time.sleep(0.8)
        close_ad(d)
    except Exception as e:
        print(f"  ⚠ 关广告异常: {e}")

    # 1. 前提：切换版本+年级（全部模块共用一次）
    step_log(f"🔧 切换版本/年级: {version} {grade}", "step")
    _switch_if_needed(d, version, grade)

    results = {}
    for i, name in enumerate(module_names):
        # ★ 停止检查：web_server 收到停止请求后注入的回调返回 True → 中断
        if stop_check is not None and stop_check():
            step_log("⏹ 收到停止请求，中断剩余模块", "warning")
            break
        if name not in MODULE_MAP:
            print(f"未知模块: {name}（可选: {list(MODULE_MAP.keys())}）")
            results[name] = {"q": 0, "t": 0, "ok": False, "error": "未知模块"}
            continue

        # 该模块的单元范围（未指定 → None = 默认全部）
        module_units = units.get(name)
        units_desc = f"{module_units}" if module_units else "全部"
        step_log(f"▶ 开始检测第 {i+1}/{len(module_names)} 个模块: {name}（单元: {units_desc}）", "step")
        t0 = time.time()
        try:
            mod = importlib.import_module(MODULE_MAP[name])
            # ★ 听力专项特殊：练习+测试两部分
            #   units["听力专项"] = 练习单元，units["听力专项_测试"] = 测试单元（可分开）
            if name == "听力专项" and hasattr(mod, "run_test_module"):
                practice_units = units.get("听力专项")
                test_units = units.get("听力专项_测试")
                if practice_units and test_units:
                    step_log(f"📌 听力专项: 练习单元{practice_units} + 测试单元{test_units} 分开检测", "step")
                    q1 = mod.run_module(d, units=practice_units)
                    step_log(f"✅ 听力专项·练习 完成: {q1} 题", "success")
                    q2 = mod.run_test_module(d, test_units=test_units)
                    step_log(f"✅ 听力专项·测试 完成: {q2} 题", "success")
                    q = q1 + q2
                else:
                    q = mod.run_module(d, units=module_units) if module_units else mod.run_module(d)
                    q2 = mod.run_test_module(d, test_units=module_units) if module_units else mod.run_test_module(d)
                    q = q + q2
                    step_log(f"📌 听力专项: 练习+测试 全部完成（{q} 题）", "info")
            else:
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
            step_log(f"❌ {name} 检测失败: {e}", "error")

        # 模块间回到主页（保证下一模块干净起点；★ 不再切换年级，调度器只在开头切一次）
        step_log(f"↩ {name} 完成，返回主页准备下一个模块…", "info")
        time.sleep(0.8)

    # 汇总
    total_q = sum(r.get("q", 0) for r in results.values())
    ok_n = sum(1 for r in results.values() if r.get("ok"))
    step_log(f"✅ 全部检测完成！{len(results)} 个模块, {ok_n} 个成功, 累计 {total_q} 题", "success")
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
