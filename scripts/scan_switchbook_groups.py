# -*- coding: utf-8 -*-
"""扫描 App「切换课本」页 → 按标题分组提取 标题→年级 映射

修复：旧版 get_grades_from_app 用正则收集所有"X年级上/下册"，没有按标题分组，
下滑翻页时把相邻标题（如 人教版（PEP）（2024审定））下的年级也扫进"人教版"。

本脚本解析 App「切换课本」页的 title_tv/segment_tv（标题）与 book_tv（年级），
按 y 坐标把每个年级归属到其上方最近的标题分组，跨屏去重，得到准确映射：
    "人教版|小学": [三年级上册, ...]   (3-6年级, 无 1-2 年级)
    "人教版（PEP）（2024审定）|小学": [一年级上册, ...]  (1-6年级)

输出: outputs/web/switchbook_groups.json
"""
import sys, os, time, json, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import uiautomator2 as u2

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "outputs", "web", "switchbook_groups.json")

GRADE_ORDER = "一二三四五六"


def _grade_key(g: str) -> int:
    m = re.match(r'([一二三四五六])年级([上下])册', g)
    if not m:
        return 999
    return GRADE_ORDER.index(m.group(1)) * 2 + (0 if m.group(2) == "上" else 1)


def parse_screen(xml: str):
    """解析一屏 XML → (title_segments, books)
    title_segments: {标题文本: {"seg": 学段, "y": 标题y}}
    books: [(年级文本, y)]
    ★ 用宽松匹配（text 属性在 resource-id 之前，不能假设属性顺序）
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
            books.append((text, y))
    return title_map, books


def scan_all(d, max_pages=20):
    """下滑扫描整页，按标题分组收集年级。返回 {标题|学段: [年级...]}"""
    groups = {}       # "标题|学段" -> set(年级)
    order = []        # 标题出现顺序（含学段）
    prev_sig = ""
    no_new = 0

    for page in range(max_pages):
        xml = d.dump_hierarchy()
        title_map, books = parse_screen(xml)

        # 收集新标题（含学段）
        for tname, info in title_map.items():
            key = f"{tname}|{info['seg']}"
            if key not in groups:
                groups[key] = set()
            if key not in order:
                order.append(key)

        # 给每个年级归属：找 y 上方最近的标题
        for gtext, gy in books:
            best, best_y = None, -1
            for tname, info in title_map.items():
                if info["y"] < gy and info["y"] > best_y:
                    best, best_y = tname, info["y"]
            if best:
                key = f"{best}|{title_map[best]['seg']}"
                groups.setdefault(key, set()).add(gtext)

        # 终止：整屏标题无变化且无新年级 → 连续 3 次结束
        sig = tuple(sorted(title_map.keys()))
        if sig == prev_sig:
            no_new += 1
            if no_new >= 3:
                break
        else:
            no_new = 0
        prev_sig = sig

        # 下滑（从网格区下方空白起滑，避免误触）
        d.swipe(540, 1900, 540, 400, 0.5)
        time.sleep(0.8)

    # 结果排序
    result = {}
    for key in order:
        result[key] = sorted(groups.get(key, set()), key=_grade_key)
    return result


def main():
    d = u2.connect()
    print("[scan] 打开切换课本页…", flush=True)
    # 确保在主页（有 switch_textbook 入口则点开）
    xml = d.dump_hierarchy()
    if 'title_tv' in xml:
        print("  已在切换课本页", flush=True)
    elif 'switch_textbook' in xml:
        d.click(300, 275)
        time.sleep(2.2)
        xml = d.dump_hierarchy()
        if 'title_tv' not in xml:
            print("⚠ 打开切换课本页失败", flush=True)
            return
    else:
        # 先回主页
        d.press('back')
        time.sleep(1)
        d.click(300, 275)
        time.sleep(2.2)

    groups = scan_all(d)
    print(f"\n=== 扫描完成: {len(groups)} 个标题分组 ===", flush=True)
    for k, gs in groups.items():
        print(f"  {k}: {gs}", flush=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"groups": groups, "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  f, ensure_ascii=False, indent=2)
    print(f"\n已保存: {OUT}", flush=True)

    try:
        d.press('back')
        time.sleep(0.5)
    except Exception:
        pass


if __name__ == "__main__":
    main()
