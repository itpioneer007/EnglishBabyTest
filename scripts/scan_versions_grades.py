# -*- coding: utf-8 -*-
"""遍历 App 所有版本 → 按「标题分组」准确记录每个版本的年级列表 → versions_grades.json

修复：旧版 get_grades_from_app 用正则收集所有"X年级上/下册"，没有按标题分组，
在「切换课本」页下滑翻页时把相邻标题（如 人教版（PEP）（2024审定））下的
1-2 年级也扫进"人教版"（人教版小学实际只有 3-6 年级）。

正确流程（对每个版本）：
  1. switch_version 切到目标版本（我的→设置→英语所学教材版本）
  2. 打开「切换课本」页（此时只显示该版本系列的标题分组）
  3. 按 title_tv/segment_tv（标题）+ book_tv（年级）按 y 坐标归属分组收集
  4. 保存 {版本名: {grades:[...], current:...}}

用法: python scripts/scan_versions_grades.py
"""
import sys, os, time, json, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2
from common.setup import switch_version, _is_home, _back_home, switch_version_grade

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "outputs", "web", "versions_grades.json")

# ★ 版本条目（保留 App 原文，不规范化合并）：同一大类下有多个变体条目
VERSIONS = [
    "通用", "人教版", "湘少版", "湘鲁版", "人教版(PEP)", "教科版",
    "外研版(三起)", "湘少版(2024审定)", "外研版(一起)", "冀教版",
    "陕旅版", "新概念青少版",
]

GRADE_ORDER = "一二三四五六"


def _grade_key(g: str) -> int:
    m = re.match(r'([一二三四五六])年级([上下])册', g)
    if not m:
        return 999
    return GRADE_ORDER.index(m.group(1)) * 2 + (0 if m.group(2) == "上" else 1)


def parse_screen(xml: str):
    """解析一屏 XML → (title_map, books)
    title_map: {标题文本: {"seg": 学段, "y": 标题y}}
    books: [(年级文本, y)]
    ★ 宽松匹配（text 属性在 resource-id 之前，不能假设属性顺序）
    """
    title_map = {}
    books = []
    cur_title = None
    for m in re.finditer(r'<node[^>]*>', xml):
        tag = m.group(0)
        rid = re.search(r'resource-id="([^"]*)"', tag)
        ridv = rid.group(1) if rid else ""
        if 'title_tv' not in ridv and 'segment_tv' not in ridv and 'book_tv' not in ridv:
            continue
        t = re.search(r'text="([^"]*)"', tag)
        b = re.search(r'bounds="\[(\d+),(\d+)\]', tag)
        text = t.group(1).strip() if t and t.group(1) else ""
        if not text or not b:
            continue
        y = int(b.group(2))
        if 'title_tv' in ridv:
            cur_title = text
            title_map.setdefault(cur_title, {"seg": "", "y": y})
        elif 'segment_tv' in ridv:
            if cur_title:
                title_map[cur_title]["seg"] = text
        elif 'book_tv' in ridv:
            # 只保留标准年级格式"X年级上/下册"，排除"全册/视频/其他"噪音
            if re.match(r'^[一二三四五六]年级[上下]册$', text):
                books.append((text, y))
    return title_map, books


def scan_grades_for_current(d, max_pages=15):
    """在切换课本页（当前版本系列）按标题分组收集年级。

    返回: {标题|学段: [年级...]}  （只含本屏及下滑可见的该系列标题分组）
    """
    groups = {}
    order = []
    prev_books_sig = ""
    no_new = 0
    for page in range(max_pages):
        xml = d.dump_hierarchy()
        title_map, books = parse_screen(xml)
        for tname, info in title_map.items():
            key = f"{tname}|{info['seg']}"
            if key not in groups:
                groups[key] = set()
            if key not in order:
                order.append(key)
        added = 0
        for gtext, gy in books:
            best, best_y = None, -1
            for tname, info in title_map.items():
                if info["y"] < gy and info["y"] > best_y:
                    best, best_y = tname, info["y"]
            if best:
                key = f"{best}|{title_map[best]['seg']}"
                if gtext not in groups.get(key, set()):
                    added += 1
                groups.setdefault(key, set()).add(gtext)
        # 终止：本屏未产生任何新年级 → 连续 3 屏结束（按年级而非标题判断，防单标题分组过早停止）
        books_sig = sorted(gtext for gtext, _ in books)
        if added == 0:
            no_new += 1
            if no_new >= 3:
                break
        else:
            no_new = 0
        prev_books_sig = books_sig
        d.swipe(540, 1900, 540, 400, 0.5)
        time.sleep(0.8)

    result = {}
    for key in order:
        result[key] = sorted(groups.get(key, set()), key=_grade_key)
    return result


def open_switchbook(d):
    """打开「切换课本」页（主页顶部版本栏）"""
    if not _is_home(d):
        d.press('back'); time.sleep(0.8)
    d.click(300, 275)
    time.sleep(2.2)
    xml = d.dump_hierarchy()
    return 'title_tv' in xml or 'book_tv' in xml


def main():
    d = u2.connect()
    # 尝试读旧配置表保留 current
    old = {}
    try:
        old = json.load(open(OUT, encoding="utf-8")).get("table", {})
    except Exception:
        pass

    result = {}
    for i, v in enumerate(VERSIONS):
        print(f"\n[{i+1}/{len(VERSIONS)}] 切版本 → {v}", flush=True)
        try:
            # 从任何状态强制回主页（关闭可能残留的切换课本页/设置面板）
            _back_home(d)
            time.sleep(0.5)
            ok = switch_version(d, v)
            if not ok:
                print(f"  ⚠ 切版本失败: {v}", flush=True)
                result[v] = {"ok": False, "error": "切版本失败", "grades": [], "current": ""}
                continue
            if not open_switchbook(d):
                print(f"  ⚠ 打开切换课本页失败: {v}", flush=True)
                result[v] = {"ok": False, "error": "切换课本页打开失败", "grades": [], "current": ""}
                continue
            groups = scan_grades_for_current(d)
            # 取目标版本对应的标题分组：标题文本包含版本名
            target_key = None
            for key in groups:
                tname = key.split("|")[0]
                if tname == v or tname.replace(" ", "") == v.replace(" ", ""):
                    target_key = key
                    break
            if target_key is None and groups:
                # 未精确匹配：取第一个分组（当前版本系列的标题）
                target_key = list(groups.keys())[0]
            grades = groups.get(target_key, []) if target_key else []
            print(f"  ✅ {v}: 标题分组={target_key} 年级({len(grades)}): {grades}", flush=True)
            result[v] = {"ok": True, "raw": target_key or "", "grades": grades, "current": ""}
        except SystemExit:
            print("  任务被停止", flush=True)
            break
        except Exception as e:
            print(f"  ⚠ 异常: {e}", flush=True)
            result[v] = {"ok": False, "error": str(e), "grades": [], "current": ""}
        # 逐版本写盘
        table = {}
        for k, vv in result.items():
            table[k] = {"grades": vv.get("grades", []), "current": vv.get("current", "")}
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, "w", encoding="utf-8") as f:
            json.dump({"table": table, "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      f, ensure_ascii=False, indent=2)

    # 恢复现场：湘少版/五年级上册
    try:
        switch_version_grade(d, "湘少版", "五年级上册")
    except Exception:
        pass
    print(f"\n✅ 扫描完成，已保存: {OUT}", flush=True)


if __name__ == "__main__":
    main()
