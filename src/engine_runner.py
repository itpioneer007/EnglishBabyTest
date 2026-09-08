"""
批量调度器（engine_runner.py）
==============================
接收模块列表 → 逐个检测 → 输出汇总 → 生成HTML报告。
"""

import uiautomator2 as u2
import time, json, os
from engine_config import APP_PACKAGE, MODULES, MODULE_ALIAS
from engine_navigator import ensure_grade, handle_popup
from engine_detector import detect_module, OUTPUT_DIR


def run_batch(module_list: list, target_grade="六年级上册",
              target_version="湘少版(2024审定)", with_report=False):
    """批量运行多个模块检测"""
    print(f"\n{'='*50}")
    print(f"英语宝 自动化引擎 v1.0")
    print(f"版本: {target_version} {target_grade}")
    print(f"目标: {module_list}")
    print(f"{'='*50}")

    # 连接设备
    try:
        d = u2.connect()
        print("✅ 设备已连接")
    except Exception as e:
        print(f"❌ 设备未连接: {e}")
        return

    # 启动 App + 年级准备
    d.app_start(APP_PACKAGE)
    time.sleep(4)
    handle_popup(d)
    if not ensure_grade(d, target_grade=target_grade, target_version=target_version):
        print("❌ 无法切换年级，终止")
        return

    # 逐个检测
    all_results = {}
    for name in module_list:
        # 别名映射
        actual = MODULE_ALIAS.get(name, name)
        config = MODULES.get(actual)
        if not config:
            print(f"  ⚠ 未知模块: {name}")
            continue

        result = detect_module(d, actual, config)
        result["module"] = name  # 用���户叫法显示
        all_results[name] = result

    # 汇总
    print(f"\n{'='*50}")
    success = fail = 0
    for name, r in all_results.items():
        ok = r["status"] == "成功"
        if ok: success += 1
        else: fail += 1
        print(f"  {'✅' if ok else '❌'} {name} - {r['status']} - {r['total']}题")
    print(f"\n📊 汇总: 总模块 {len(all_results)} | 成功 {success} | 失败 {fail}")
    print(f"📁 截图: {OUTPUT_DIR}")
    print(f"{'='*50}")

    if with_report:
        generate_html_report(all_results, target_grade, target_version)
    return all_results


def generate_html_report(results, grade="", version=""):
    """生成 HTML 报告"""
    html = f"""<html><head><meta charset='utf-8'><title>英语宝检测报告</title>
    <style>body{{font-family:sans-serif;margin:20px}}h1{{color:#333}}h2{{border-bottom:1px solid #ccc}}img{{width:180px;margin:4px;border:1px solid #ddd}}</style></head><body>
    <h1>英语宝模块检测报告</h1><p>时间: {time.strftime('%Y-%m-%d %H:%M')}</p>
    <p>版本: {version} {grade}</p>"""
    for module, data in results.items():
        html += f"<h2>{module} ({data['total']}题)</h2>"
        if data.get("errors"):
            html += f"<p style='color:red'>错误: {data['errors']}</p>"
        for img in data.get("shots", []):
            html += f"<img src='{img}'/>"
    html += "</body></html>"
    path = os.path.join(os.path.dirname(OUTPUT_DIR), "report.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"📊 HTML报告: {path}")
