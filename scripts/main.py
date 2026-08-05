"""
英语宝 · 运行入口
=================
python main.py
"""
import uiautomator2 as u2
import time
from config import TARGET_MODULES, GRADE_LEVEL, BOOK_VERSION, APP_PACKAGE
from engine import close_ad, dismiss_global_popups, ensure_grade, run_single_module, MODULE_CONFIG

if __name__ == "__main__":
    d = u2.connect()
    print("✅ 设备已连接")

    modules = TARGET_MODULES
    print(f"📋 待跑模块: {len(modules)} 个 → {modules}")

    # 强制重启 App 回主页
    d.app_stop(APP_PACKAGE); time.sleep(2)
    d.app_start(APP_PACKAGE); time.sleep(7)
    # 关广告
    for _ in range(3):
        dismiss_global_popups(d)
    close_ad(d)
    # ═════════════════════════════════════════════════

    if not ensure_grade(d, GRADE_LEVEL, BOOK_VERSION):
        print("❌ 年级切换失败"); exit(1)

    # 逐个模块执行
    total_q = 0
    ok_count = 0
    results = []

    for i, mod_name in enumerate(modules, 1):
        cfg = MODULE_CONFIG.get(mod_name)
        if not cfg:
            print(f"❌ 未知模块: {mod_name}，跳过")
            continue

        print(f"\n  [{i}/{len(modules)}]")
        q = run_single_module(d, mod_name, cfg)
        results.append((mod_name, q))
        total_q += q
        if q > 0:
            ok_count += 1

        # 回到主页（最后一个模块不用回）
        if i < len(modules):
            print(f"  ↩ 返回主页...")
            back_to_home(d, GRADE_LEVEL)
            time.sleep(2)

    # 汇总
    print(f"\n{'='*45}")
    print(f"📊 批量调度汇总")
    print(f"{'='*45}")
    for mod, q in results:
        print(f"  {'✅' if q > 0 else '⚠'} {mod}: {q} 题")
    print(f"  总模块: {len(modules)} | 有题: {ok_count}")
    print(f"  总截图: {total_q} 张")
    print(f"{'='*45}")
