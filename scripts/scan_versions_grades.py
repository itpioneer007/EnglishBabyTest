# -*- coding: utf-8 -*-
"""遍历 App 所有版本 → 记录每个版本的年级列表 → outputs/web/versions_grades.json

用法: python scripts/scan_versions_grades.py
说明:
  - 对 VERSIONS 每个版本: 切版本(走"我的"页) → 回主页 → 打开「切换课本」页读年级列表
  - 逐版本实时写入 JSON（中断不丢已扫数据）
  - 扫描完自动切回 湘少版/五年级上册（恢复现场）
"""
import sys, os, time, json, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from common.setup import switch_version, get_grades_from_app, _is_home, _back_home, switch_version_grade

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs", "web", "versions_grades.json")

# ★ 版本条目（保留 App 原文，不规范化合并！）：同一大类下有多个变体条目
#   （如 湘少版 / 湘少版(2024审定)；人教版 / 人教版(PEP)…），各自年级可能不同，须分别扫描
VERSIONS = [
    "通用", "人教版", "湘少版", "湘鲁版", "人教版(PEP)", "教科版",
    "外研版(三起)", "湘少版(2024审定)", "外研版(一起)", "冀教版",
    "陕旅版", "新概念青少版",
]


def homebar_info(d):
    """主页顶部栏文本 → (版本名, 年级名)"""
    try:
        xml = d.dump_hierarchy()
        m = re.search(r'<node[^>]*resource-id="[^"]*switch_textbook_tv"[^>]*>', xml)
        if m:
            tm = re.search(r'text="([^"]*)"', m.group(0))
            if tm:
                t = tm.group(1)
                vm = re.search(r'([\u4e00-\u9fa5A-Za-z()（）]+版)', t)
                gm = re.search(r'([一二三四五六]年级(?:上|下)册)', t)
                return (vm.group(1) if vm else ""), (gm.group(1) if gm else "")
    except Exception:
        pass
    return "", ""


def main():
    d = u2.connect()
    print(f"[scan] 设备连接，开始遍历 {len(VERSIONS)} 个版本…", flush=True)
    # 先确保回主页
    if not _is_home(d):
        _back_home(d)

    result = {}
    for i, v in enumerate(VERSIONS, 1):
        print(f"[scan] [{i}/{len(VERSIONS)}] 切版本 → {v}", flush=True)
        try:
            ok = switch_version(d, v)
            if not ok:
                print(f"  ⚠ 切版本失败: {v}", flush=True)
                result[v] = {"ok": False, "error": "切版本失败", "grades": [], "current": ""}
                continue
            time.sleep(1.5)
            grades = get_grades_from_app(d)
            _, cur_grade = homebar_info(d)
            # 版本名即 App 原文（含变体，如"湘少版(2024审定)"）
            raw = v
            result[v] = {"ok": True, "raw": raw, "grades": grades, "current": cur_grade}
            print(f"  ✅ {v}: {len(grades)} 个年级（当前: {cur_grade or '?'}） {grades[:8]}", flush=True)
        except Exception as e:
            print(f"  ❌ {v} 异常: {e}", flush=True)
            result[v] = {"ok": False, "error": str(e), "grades": [], "current": ""}
        # 实时保存
        try:
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  ⚠ 保存失败: {e}", flush=True)

    # 恢复现场：切回湘少版五年级上册
    print("[scan] 恢复现场 → 湘少版 五年级上册", flush=True)
    try:
        switch_version_grade(d, "湘少版", "五年级上册")
    except Exception as e:
        print(f"  ⚠ 恢复失败: {e}", flush=True)

    print(f"[scan] 完成! 配置表: {OUT}", flush=True)
    print(json.dumps({k: {"ok": vv.get("ok"), "n": len(vv.get("grades", []))} for k, vv in result.items()}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
