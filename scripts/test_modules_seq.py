# -*- coding: utf-8 -*-
"""顺序单独运行各模块，找出卡住/异常问题。

用法: python test_modules_seq.py
- 按顺序: 听力专项 → 口语训练 → 单元自检 → 知识过关 → 巧记单词 → 语音评测
- 每个模块前: 回主页 + 关广告 + 切年级（模拟 main() 的独立运行前置）
- 输出到 test_seq.log，含每个模块开始/结束/耗时/异常
"""
import sys, os, time, importlib, io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# 确保 stdout 实时刷新（重定向到文件时能看到进度）
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

import uiautomator2 as u2
from common.tools import close_ad, dismiss_global_popups
from common.setup import switch_version_grade
from config import APP_PACKAGE, GRADE_LEVEL, BOOK_VERSION

MODULES = ["听力专项", "口语训练", "单元自检", "知识过关", "巧记单词", "语音评测"]
MODULE_MAP = {
    "听力专项": "modules.听力专项",
    "口语训练": "modules.口语训练",
    "单元自检": "modules.单元自检",
    "知识过关": "modules.知识过关",
    "巧记单词": "modules.巧记单词",
    "语音评测": "modules.语音评测",
}


def back_to_home(d, max_back=6):
    """按 back 直到回到主页（switch_textbook_tv 年级栏 或 教材精学 可见）
    若退过头到桌面，重新启动 App"""
    for _ in range(max_back):
        # 处理退出确认弹窗
        try:
            if d(text="确定退出").exists(timeout=0.3):
                d(text="确定退出").click(); time.sleep(0.8)
            elif d(text="退出").exists(timeout=0.3) and d(text="继续答题").exists(timeout=0.3):
                d(text="退出").click(); time.sleep(0.8)
            elif d(text="继续答题").exists(timeout=0.3):
                d(text="继续答题").click(); time.sleep(0.8)
        except Exception:
            pass
        try:
            xml = d.dump_hierarchy()
        except Exception:
            xml = ""
        if "switch_textbook_tv" in xml or "教材精学" in xml or "专项突破" in xml:
            return True
        d.press("back")
        time.sleep(0.6)
        # 检查是否退到桌面（无 App 元素），若是则重新启动 App
        try:
            xml2 = d.dump_hierarchy()
            if "英语学习" in xml2 and "游戏助手" in xml2:
                print("  ⚠ 退过头到桌面，重启 App", flush=True)
                d.app_start("com.dinoenglish.yyb")
                time.sleep(4)
        except Exception:
            pass
    return False


def pre_setup(d):
    """独立运行前置：回主页 + 关广告 + 切年级"""
    back_to_home(d)
    try:
        for _ in range(3):
            dismiss_global_popups(d)
        close_ad(d)
    except Exception as e:
        print(f"  ⚠ 关广告异常: {e}")
    try:
        switch_version_grade(d, BOOK_VERSION, GRADE_LEVEL, skip_if_ok=True)
        print(f"  ✅ 年级: {BOOK_VERSION} {GRADE_LEVEL}")
    except Exception as e:
        print(f"  ⚠ 切年级异常: {e}")


def run_one(name, d, timeout=900):
    """跑一个模块，超时或异常都记录"""
    print(f"\n{'='*60}", flush=True)
    print(f"▶▶▶ 模块开始: {name}  ({time.strftime('%H:%M:%S')})", flush=True)
    print(f"{'='*60}", flush=True)
    t0 = time.time()
    try:
        mod = importlib.import_module(MODULE_MAP[name])
        q = mod.run_module(d)
        dt = time.time() - t0
        print(f"✅ [{name}] 完成: {q} 题, 耗时 {dt:.0f}s ({time.strftime('%H:%M:%S')})", flush=True)
        return {"name": name, "q": q, "t": round(dt), "ok": True}
    except Exception as e:
        dt = time.time() - t0
        import traceback
        traceback.print_exc()
        print(f"❌ [{name}] 异常: {e} (耗时 {dt:.0f}s)", flush=True)
        return {"name": name, "q": 0, "t": round(dt), "ok": False, "error": str(e)}


def main():
    d = u2.connect("SKSCIF4T7PFMQS5X")
    print(f"✅ 设备已连接: SKSCIF4T7PFMQS5X", flush=True)
    # 支持命令行指定模块: python test_modules_seq.py 听力专项 口语训练
    target = sys.argv[1:]
    modules = [m for m in MODULES if not target or m in target]
    results = []
    for name in modules:
        pre_setup(d)
        r = run_one(name, d)
        results.append(r)
        # 模块间回到主页
        back_to_home(d, max_back=8)
        time.sleep(0.8)

    print(f"\n{'='*60}", flush=True)
    print("📊 顺序测试汇总", flush=True)
    print(f"{'='*60}", flush=True)
    for r in results:
        st = "OK" if r["ok"] else "FAIL"
        err = f" | {r.get('error')}" if not r["ok"] else ""
        print(f"  [{st}] {r['name']}: {r['q']} 题, {r['t']}s{err}", flush=True)


if __name__ == "__main__":
    main()
