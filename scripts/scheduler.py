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
# ★ 2026-10-08：导入即补全 u2 的异常映射缺口（RemoteDisconnected 等 http.client
#   家族异常原本裸逃逸 → 设备瞬断会掀翻整个模块）。详见 common/u2_resilience.py
try:
    from common import u2_resilience as _u2_resilience  # noqa: F401
except Exception:
    pass
from common.setup import switch_version_grade
from common.tools import close_ad, dismiss_global_popups, settle_ads
from common.logger import step_log
# ★ 2026-10-19：面向使用者的错误翻译层。前端日志只留人话，
#   技术细节（异常类名/调用栈）走 print → server_output.log。
from common.user_msg import human_error, summary_text, fmt_unit_value, status_of

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


def _stage_log(label: str, q: int):
    """子阶段（如听力专项·练习）结束时的日志：0 题绝不能写成「完成」。

    ★ 2026-10-19：试用反馈"检测完了 5 个、累计零题"就是在这一步骗人的 ——
      旧日志无论题数多少都写「✅ xx 完成: 0 题」，测试员据此以为已经测过。
    """
    try:
        q = int(q or 0)
    except Exception:
        q = 0
    if q > 0:
        step_log(f"✅ {label} 检测完成：{q} 题", "success")
    else:
        step_log(f"⚠ {label} 未检测到题目（0 题），不计入检测结果", "warning")


def _wait_home_ready(d, timeout=25):
    """轮询等待英语宝主页就绪（主页特征命中即 True）。

    ★ 2026-10-08 新增。见 run_all 里"重启 App"处的说明：冷启动 + 开屏广告
      通常超过固定 sleep，必须等主页真正就绪再切版本/年级，否则
      switch_version_grade 会因 `_is_home()` 为假而直接中止。
    """
    try:
        from common.setup import _is_home as _is_home_fn
    except Exception:
        _is_home_fn = None
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if _is_home_fn and _is_home_fn(d):
                return True
        except Exception:
            pass
        time.sleep(0.8)
    return False


def _switch_if_needed(d, version, grade):
    """切换到目标版本+年级；已是目标则跳过。返回 True=已确认，False=切换失败。

    返回值语义（★ 2026-10-08 修正）：
      switch_version_grade 返回 True 有两种含义 —— "本来就对，无需切换" 与
      "切换成功"。旧实现仅在 `ok is True` 时打一条日志，且文案恒为"无需切换"
      （切成功了也这么说）；`ok is False`（切换中止/失败）则【完全没有处理】
      → 静默吞掉，整轮继续跑在上一个版本/年级上，结论全部作废却看不出来。

    现在：失败 → 明确告警 + 回主页后重试一次 → 仍失败则返回 False，
    由调用方中止本轮（宁可不测，也不能拿错年级的结果冒充）。
    """
    if not (version and grade):
        return True
    for attempt in (1, 2):
        ok = False
        try:
            ok = switch_version_grade(d, version, grade, skip_if_ok=True)
        except Exception as e:
            print(f"  ⚠ 切换版本/年级异常: {e}")
        if ok:
            step_log(f"✔ 版本/年级已确认: {version} {grade}", "info")
            return True
        if attempt == 1:
            step_log(f"⚠ 版本/年级切换失败，回主页后重试一次: {version} {grade}", "warning")
            try:
                _back_to_home(d)
            except Exception:
                pass
            time.sleep(2)
    step_log(f"❌ 版本/年级未切换至「{version} {grade}」，本轮已中止"
             f"（不使用错误年级的检测结果作为结论）", "error")
    step_log("　　处理建议：上述日志已记录中断位置，请按提示处理后重新检测。", "info")
    return False


def _back_to_home(d):
    """★ 模块间回主页（修复切换卡顿 + back 过头退桌面）：统一走 common.tools.safe_back_to_home。

    之前只是 sleep 0.8s 打日志没有实际动作 → 下一模块从模块内部页开始
    → 找不到入口 → 卡很久 → 最后重启 App（用户实测"切模块不丝滑"）。
    ★ 用户实测"back 过多退到手机页面"：模块内部 back 循环只认目标特征，
      特征变化时一路退到桌面 → safe_back_to_home 增加"主页特征命中即停"保底，
      非 yyb 前台自动冷启动。
    """
    try:
        from common.tools import safe_back_to_home, is_home_xml
    except Exception:
        safe_back_to_home, is_home_xml = None, None
    if safe_back_to_home:
        safe_back_to_home(d, max_backs=8)
    else:
        # 兜底：旧逻辑
        import re as _re
        try:
            _cur = d.app_current()
            _is_yyb = (_cur or {}).get("package") == APP_PACKAGE
        except Exception:
            _is_yyb = False
        if not _is_yyb:
            try:
                d.press("home"); time.sleep(0.4)
                d.app_start(APP_PACKAGE); time.sleep(3)
            except Exception:
                pass
            return
        for _ in range(8):
            try:
                xml = d.dump_hierarchy(timeout=2)
            except Exception:
                xml = ""
            if is_home_xml and is_home_xml(xml):
                break
            try:
                d.press("back"); time.sleep(0.4)
            except Exception:
                break
    # 兜底：确认主页，必要时清广告
    for _ in range(2):
        dismiss_global_popups(d)
    close_ad(d)


def _ensure_screen_on(d):
    """★ 2026-09-15 跑前亮屏：设备息屏时 uiautomator dump 拿不到 UI。

    实测（口语训练 U1 复跑）：手机闲置息屏后点开始检测，切版本/年级与
    找模块入口全部失败，日志却显示"完成 0 题"——看起来像模块没内容，
    实际是屏幕没亮。这里先亮屏并上滑解除无密码锁屏（坐标按屏幕尺寸算，
    不写死）。
    """
    try:
        if (d.info or {}).get("screenOn"):
            return
        step_log("💡 设备息屏中，先亮屏...", "step")
        d.screen_on()
        time.sleep(1.2)
        _w, _h = d.window_size()
        try:
            d.swipe(_w // 2, int(_h * 0.8), _w // 2, int(_h * 0.3), 0.1)
        except Exception:
            pass
        time.sleep(0.8)
    except Exception as e:
        print(f"  ⚠ 亮屏检查异常: {e}")


def run_all(module_names=None, d=None, version=None, grade=None, units=None, stop_check=None, on_module_done=None):
    """依次跑指定模块（默认全部），返回 {模块: {q, t, ok}}

    version/grade: 目标教材版本+年级，执行前自动切换（已正确则跳过）
    units: 每个模块的单元范围映射，如 {"听力专项": "1-3", "单元自检": "1-5"}
          未指定的模块跑默认全部单元
    stop_check: 可选回调，每次模块循环前调用；返回 True 表示收到停止请求 → 中断
    on_module_done: 可选回调(name, result)，每模块完成后调用（如 LLM 脚本审查）
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
        _hl, _act, _tech = human_error(e)
        step_log(f"❌ 设备不可用，本轮无法开始检测：{_hl}", "error")
        step_log(f"　　处理建议：{_act}", "info")
        print(f"[设备不可用] {_tech}")
        return {name: {"q": 0, "t": 0, "ok": False, "status": "failed",
                       "error": _hl, "error_action": _act}
                for name in (module_names or MODULE_MAP.keys())}

    if module_names is None:
        module_names = list(MODULE_MAP.keys())
    if version is None:
        version = DEFAULT_VERSION
    if grade is None:
        grade = DEFAULT_GRADE
    units = units or {}

    # 0. 重启 App 回主页（保证干净起点，避免停留在上个模块的答题页）
    # ★ 移除 app_start 前的 d.press("home")：紧接着就是 app_stop 直接杀进程，回不回桌面无区别，
    #   每次点开始检测那一下"回主页"纯属多余且拖慢启动。
    step_log("🔄 重启 App，准备开始检测...", "step")
    try:
        _ensure_screen_on(d)   # ★ 息屏时 dump 为空 → 会跑出"0 题"假成功
        d.app_stop(APP_PACKAGE); time.sleep(0.8)
        d.app_start(APP_PACKAGE)
        # ★ 2026-10-08 修复（实测踩坑）：原为固定 `time.sleep(3)` 后立刻切版本/年级。
        #   但冷启动 + 开屏广告普遍 >3s，彼时 App 还在启动页：
        #     _is_home() 为假 → _back_home() 的 back 反而把启动中的 App 顶到桌面
        #     → switch_version_grade 打印"✘ 无法回到主页，切换中止"并返回 False
        #     → 上一层又静默忽略该 False（见 _switch_if_needed 说明）
        #     → 整轮跑在【上一个年级】上，结论全部作废却毫无提示。
        #   实测日志：21:25:05 重启 App → 21:25:10 切年级 → ✘ 无法回到主页（仅隔 5s）。
        #   改为轮询等待主页特征就绪（最多 25s），就绪后才继续。
        if not _wait_home_ready(d, timeout=25):
            step_log("⚠ App 启动 25 秒内未进入首页（可能被开屏广告或系统弹窗遮挡），将继续尝试",
                     "warning")
    except Exception as e:
        step_log(f"⚠ App 重启异常: {e}", "error")

    # 1. 前提：切换版本+年级（全部模块共用一次）
    #   ★ 修复：日志顺序与操作顺序一致——先切版本年级再关广告
    #   （切完版本/年级后页面会重载，可能产生新广告，必须在操作前关掉）
    step_log(f"🔧 切换版本/年级: {version} {grade}", "step")
    if not _switch_if_needed(d, version, grade):
        # ★ 版本/年级没切到位 → 继续跑只会产出"错年级的结论"。
        #   宁可不测：全部模块标记失败并原样返回，让用户在日志里一眼看到拦停原因。
        return {name: {"q": 0, "t": 0, "ok": False, "status": "failed",
                       "error": "版本/年级没有切换成功，本模块没有开始检测"}
                for name in module_names}

    # 1.5 关广告（与单模块 main() 一致：先清全局弹窗 + 关广告，再操作界面，
    #     否则切完版本/年级后主页新广告/弹窗未关，后续点坐标会点到广告上！）
    step_log("🧹 清理广告弹窗...", "step")
    try:
        # ★ 广告延迟加载（冷重启后 4-6s 甚至更晚才出现）+ 可能弹多个：
        #   用 settle_ads 循环「检测→关闭→再检测」，连续 2 轮干净才继续，
        #   消除"关早了→点空 / 点听力专项时广告刚弹出→误点广告"的竞态（用户实测根因）。
        settle_ads(d, wait_total=12)
    except Exception as e:
        print(f"  ⚠ 关广告异常: {e}")

    results = {}
    for i, name in enumerate(module_names):
        # ★ 停止检查：web_server 收到停止请求后注入的回调返回 True → 中断
        if stop_check is not None and stop_check():
            step_log("⏹ 收到停止请求，中断剩余模块", "warning")
            break
        if name not in MODULE_MAP:
            print(f"未知模块: {name}（可选: {list(MODULE_MAP.keys())}）")
            results[name] = {"q": 0, "t": 0, "ok": False, "status": "failed",
                             "error": "当前版本不支持该模块，无法检测"}
            step_log(f"❌ {name} 无法检测：当前版本不支持该模块", "error")
            continue

        # 该模块的单元范围（未指定 → None = 默认全部）
        module_units = units.get(name)
        units_desc = fmt_unit_value(module_units) or "全部单元"
        step_log(f"▶ 第 {i+1}/{len(module_names)} 个模块：{name}（{units_desc}）", "step")
        # ★ 设置模块上下文（供错题定位：哪个模块·哪个子模块）
        try:
            from common.logger import set_current_module
            set_current_module(name, "")
        except Exception:
            pass
        t0 = time.time()
        try:
            mod = importlib.import_module(MODULE_MAP[name])
            # ★ 听力专项特殊：练习+测试两部分
            #   units["听力专项"] = 练习单元，units["听力专项_测试"] = 测试单元（可分开）
            #   ★ 前端"练/测"勾选：未勾选的部分传 'NONE' 哨兵 → 跳过
            if name == "听力专项" and hasattr(mod, "run_test_module"):
                practice_units = units.get("听力专项")
                test_units = units.get("听力专项_测试")
                _p_on = practice_units is not None and practice_units != "NONE"
                _t_on = test_units is not None and test_units != "NONE"
                # ★ 辅助：分别记录"练习/测试"的题数和回调状态，用于拆 on_module_done
                _p_res = None
                _t_res = None
                if _p_on and _t_on:
                    step_log(f"📌 听力专项：练习 {fmt_unit_value(practice_units)}，测试 {fmt_unit_value(test_units)}，分开检测", "step")
                    set_current_module("听力专项", "练习")
                    _p_q = mod.run_module(d, units=practice_units) if _p_on else 0
                    _stage_log("听力专项·练习", _p_q)
                    _p_res = {"q": _p_q, "t": 0, "ok": True, "stage": "练习",
                              "status": "ok" if _p_q > 0 else "empty"}
                    set_current_module("听力专项", "测试")
                    _t_q = mod.run_test_module(d, test_units=test_units) if _t_on else 0
                    _stage_log("听力专项·测试", _t_q)
                    _t_res = {"q": _t_q, "t": 0, "ok": True, "stage": "测试",
                              "status": "ok" if _t_q > 0 else "empty"}
                    q = _p_q + _t_q
                elif _p_on:
                    set_current_module("听力专项", "练习")
                    _p_q = mod.run_module(d, units=practice_units)
                    step_log(f"📌 听力专项：只测练习（测试未勾选）", "info")
                    _stage_log("听力专项·练习", _p_q)
                    _p_res = {"q": _p_q, "t": 0, "ok": True, "stage": "练习",
                              "status": "ok" if _p_q > 0 else "empty"}
                    q = _p_q
                elif _t_on:
                    set_current_module("听力专项", "测试")
                    _t_q = mod.run_test_module(d, test_units=test_units)
                    step_log(f"📌 听力专项：只测测试（练习未勾选）", "info")
                    _stage_log("听力专项·测试", _t_q)
                    _t_res = {"q": _t_q, "t": 0, "ok": True, "stage": "测试",
                              "status": "ok" if _t_q > 0 else "empty"}
                    q = _t_q
                elif practice_units == "NONE" and test_units == "NONE":
                    # 前端明确"练/测 都不勾选" → 跳过听力专项（不跑）
                    step_log("📌 听力专项：练习和测试都没勾选，本模块跳过", "warning")
                    q = 0
                else:
                    # 都未指定（旧调用，无 units 传参）→ 都跑，兼容
                    set_current_module("听力专项", "练习")
                    _p_q = mod.run_module(d, units=module_units) if module_units else mod.run_module(d)
                    _p_res = {"q": _p_q, "t": 0, "ok": True, "stage": "练习",
                              "status": "ok" if _p_q > 0 else "empty"}
                    set_current_module("听力专项", "测试")
                    _t_q = mod.run_test_module(d, test_units=module_units) if module_units else mod.run_test_module(d)
                    _t_res = {"q": _t_q, "t": 0, "ok": True, "stage": "测试",
                              "status": "ok" if _t_q > 0 else "empty"}
                    q = _p_q + _t_q
                    step_log(f"📌 听力专项：练习 + 测试都跑完了，合计 {q} 题", "info")
            else:
                # ★ 其他模块：设置模块上下文（模块名 + 子模块从模块内部 step_log 更新）
                set_current_module(name, "")
                if module_units:
                    q = mod.run_module(d, units=module_units)
                else:
                    q = mod.run_module(d)
            elapsed = round(time.time() - t0)
            # ★ 2026-10-19：三态落库。q>0 才是「检测完成」；
            #   跑完但 0 题 → empty（没有题目，未检测）—— 不许再算成功。
            _st = "ok" if int(q or 0) > 0 else "empty"
            results[name] = {"q": q, "t": elapsed, "ok": True, "status": _st}
            if _st == "ok":
                step_log(f"✅ {name} 检测完成：{q} 题，用时 {elapsed} 秒", "success")
            else:
                step_log(
                    f"⚠ {name} 未检测到题目（0 题）：该模块已完整遍历，App 内未出现可检测的题目，"
                    f"不计入检测完成。若 App 内该模块确有题目，则说明进入或翻页失败，"
                    f"请重新检测该模块。", "warning")
                if elapsed <= 5:
                    step_log(
                        f"　　本次耗时 {elapsed} 秒，模块入口可能未被进入。"
                        f"请确认当前版本/年级的首页存在「{name}」入口；若不存在，请在模块列表中取消勾选。",
                        "info")
            # ★ 模块完成后回调（web_server 用它跑 LLM 脚本审查，不阻塞下一模块）
            if on_module_done is not None:
                # ★ 听力专项：练习/测试分别完成后回调（stage 区分，避免脚本错配比对）
                if name == "听力专项" and (_p_res or _t_res):
                    if _p_res and on_module_done is not None:
                        try:
                            on_module_done(name, _p_res)
                        except Exception as _e:
                            step_log(f"⚠ 听力专项·练习 完成后回调异常: {_e}", "warning")
                    if _t_res and on_module_done is not None:
                        try:
                            on_module_done(name, _t_res)
                        except Exception as _e:
                            step_log(f"⚠ 听力专项·测试 完成后回调异常: {_e}", "warning")
                elif on_module_done is not None:
                    try:
                        on_module_done(name, results[name])
                    except Exception as _e:
                        step_log(f"⚠ {name} 完成后回调异常: {_e}", "warning")
        except SystemExit:
            raise
        except Exception as e:
            elapsed = round(time.time() - t0)
            _headline, _action, _tech = human_error(e, name)
            results[name] = {"q": 0, "t": elapsed, "ok": False, "status": "failed",
                             "error": _headline, "error_action": _action}
            # ★ 2026-10-19：前端只给人话 + 下一步动作；调用栈 print 到服务端日志。
            #   旧写法把 `device 'xxx' not found [ ' File "C:\...\adb.py", line 192…`
            #   直接甩到测试员面前（试用反馈最刺眼的一条）。
            step_log(f"❌ {name} 检测中断：{_headline}", "error")
            step_log(f"　　处理建议：{_action}", "info")
            print(f"[模块中断] {name} → {_tech}")
            import traceback as _tb
            _tb.print_exc()

        # 模块间回到主页（★ 修复：真正 back 回主页，保证下一模块干净起点；
        #   之前只打日志不动作 → 卡顿+重启 App。不再切换年级，调度器只在开头切一次）
        if results.get(name, {}).get("status") == "failed":
            step_log("↩ 本模块已中断，返回首页继续下一模块…", "info")
        else:
            step_log("↩ 返回首页，准备下一模块…", "info")
        _back_to_home(d)

    # 汇总：口径统一走 user_msg（0 题不算成功，失败不说完成）
    if results:
        _sum = summary_text(results)
        _lv = "success"
        if any(status_of(r) == "failed" for r in results.values()):
            _lv = "warning"
        if sum(int((r or {}).get("q") or 0) for r in results.values()) == 0:
            _lv = "error"
        step_log(_sum, _lv)
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
    # 重启 App 回主页（保证干净起点）；app_start 前无需 press home（app_stop 直接杀进程）
    _ensure_screen_on(d)   # ★ 息屏时 dump 为空 → 会跑出"0 题"假成功
    d.app_stop(APP_PACKAGE); time.sleep(0.8)
    d.app_start(APP_PACKAGE); time.sleep(3)
    run_all(names if names else None, d, version=version, grade=grade, units=units_map)
    return 0


if __name__ == "__main__":
    sys.exit(main())
