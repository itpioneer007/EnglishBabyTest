# -*- coding: utf-8 -*-
"""探测「口语训练·结合句型图片题」的真实页面结构。

目标：拿到含「结合句型 / 例句」的大题（如 湘少六上 U1 第3大题）的
      dump_hierarchy 与截图，确认：
        ① 例句文本节点（text 属性、bounds）
        ② 图片节点 pic_iv 的 bounds
        ③ 小题容器 ll_container 的 bounds
        ④ 例句与图片是否在同一容器内（决定解析策略）

用法：
    python tools/probe_oral_pattern.py [--units 1] [--max-big 5] [--no-skip-parse]
只做只读探测，不改动项目其它状态。
"""
import io
import os
import re
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import uiautomator2 as u2  # noqa: E402

SERIAL = os.environ.get("YYB_SERIAL", "SKSCIF4T7PFMQS5X")
GRADE = os.environ.get("YYB_GRADE", "六年级上册")
VERSION = os.environ.get("YYB_VERSION", "湘少版")
OUT_DIR = os.path.join(_ROOT, "screenshots", "oral_probe")


def log(*a):
    print(*a, flush=True)


def save(xml, tag):
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, f"{tag}.xml")
    with open(p, "w", encoding="utf-8") as f:
        f.write(xml)
    return p


def shot(tag):
    os.makedirs(OUT_DIR, exist_ok=True)
    p = os.path.join(OUT_DIR, f"{tag}.png")
    try:
        d.screenshot(p)
    except Exception as e:
        log("  ⚠ 截图失败:", e)
        return None
    return p


def texts_of(xml):
    return [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]


def has_pattern_kw(xml):
    return any(k in xml for k in ("结合句型", "例句", "句型提示", "看图说"))


def big_progress(xml):
    for m in re.finditer(r'<node[^>]*tv_question_sort[^>]*>', xml):
        tm = re.search(r'text="(\d+)\s*/\s*(\d+)"', m.group(0))
        if tm:
            return int(tm.group(1)), int(tm.group(2))
    return None, None


def back_to_app_home():
    try:
        if (d.app_current() or {}).get("package") != "com.dinoenglish.yyb":
            d.press("home")
            time.sleep(0.4)
            d.app_start("com.dinoenglish.yyb")
            time.sleep(3.0)
    except Exception:
        pass
    for _ in range(8):
        try:
            xml = d.dump_hierarchy()
            if ("教材精学" in xml or "专项突破" in xml or "听课文" in xml):
                return True
        except Exception:
            pass
        try:
            d.press("back")
        except Exception:
            pass
        time.sleep(0.6)
    return False


def main():
    log(f"连接设备 {SERIAL} …")
    global d
    d = u2.connect(SERIAL)
    log("  分辨率:", d.window_size())

    if not back_to_app_home():
        log("  ❌ 无法回到英语宝主页")
        return 1
    log("  ✅ 已回到主页")

    # 切年级/版本
    try:
        from common.setup import _current_texts
        v, g = _current_texts(d)
        log(f"  当前设备: {v or '?'} {g or '?'}")
    except Exception as e:
        log("  (年级读取失败:", e, ")")
    try:
        from common.tools import ensure_grade
        ok = ensure_grade(d, GRADE, VERSION)
        log(f"  切到 {VERSION} {GRADE}: {ok}")
        time.sleep(1.5)
    except Exception as e:
        log("  ⚠ 切年级异常:", type(e).__name__, e)

    # 进口语训练
    try:
        from common.tools import scroll_and_find
        found = scroll_and_find(d, "口语训练", max_swipes=4)
    except Exception:
        found = d(text="口语训练").exists(timeout=2)
    if not found:
        log("  ❌ 主页找不到「口语训练」入口")
        save(d.dump_hierarchy(), "home_not_found")
        return 1
    d(text="口语训练").click()
    time.sleep(1.8)
    log("  ✅ 已进入口语训练模块页")
    try:
        from modules.口语训练 import _close_bottom_ad
        _close_bottom_ad(d)
    except Exception:
        pass

    xml = d.dump_hierarchy()
    save(xml, "oral_list")
    log("  模块页文本:", [t for t in texts_of(xml) if len(t) < 30][:20])

    # 找 U1 入口
    clicked = False
    for attempt in range(6):
        xml = d.dump_hierarchy()
        elements = d.xpath('//*[@text!=""]').all() or []
        row_y = None
        for e in elements:
            t = (e.text or "").strip()
            if "口语训练" in t and re.search(r"U1\b|U\s*1\b", t):
                row_y = e.bounds[1]
                log(f"  找到 U1 标题行: {t!r} y={row_y}")
                break
        if row_y is not None:
            for e in elements:
                t = (e.text or "").strip()
                if t in ("重新答题", "继续答题", "开始答题") and abs(e.bounds[1] - row_y) < 320:
                    cx = (e.bounds[0] + e.bounds[2]) // 2
                    cy = (e.bounds[1] + e.bounds[3]) // 2
                    d.click(cx, cy)
                    log(f"  ✅ 点击「{t}」进入 U1")
                    clicked = True
                    break
        if clicked:
            break
        d.swipe(540, 1800, 540, 700, 0.3)
        time.sleep(0.5)
    if not clicked:
        log("  ❌ 未找到 U1 入口")
        save(d.dump_hierarchy(), "u1_not_found")
        return 1

    time.sleep(1.5)
    # 入口弹窗 + 开始答题
    try:
        from modules.口语训练 import _after_unit_enter
        _after_unit_enter(d)
    except Exception as e:
        log("  ⚠ _after_unit_enter 异常:", e)
        if d(text="好的，我知道啦~").exists(timeout=3):
            d(text="好的，我知道啦~").click()
            time.sleep(0.6)
        if d(text="开始答题").exists(timeout=3):
            d(text="开始答题").click()
            time.sleep(1.5)
    log("  ✅ 已进入答题页")

    # 逐大题探测
    for big in range(1, 6):
        time.sleep(1.0)
        try:
            xml = d.dump_hierarchy()
        except Exception as e:
            log("  ⚠ dump 失败:", e)
            continue
        cur, tot = big_progress(xml)
        tag = f"big{cur or big}"
        save(xml, tag)
        pat = has_pattern_kw(xml)
        log(f"  --- 第{cur or big}/{tot or '?'}大题  含句型/例句关键词: {pat}")
        if pat:
            p = shot(tag)
            log(f"      ✅ 命中！已保存 dump 与截图: {p}")
            _describe(xml)
            return 0
        # 未命中 → 尝试跳下一大题
        jumped = False
        for kw in ("下一题", "下一大题", "跳过"):
            if d(text=kw).exists(timeout=0.3):
                d(text=kw).click()
                log(f"      → 点「{kw}」")
                time.sleep(1.5)
                jumped = True
                break
        if not jumped:
            # 试试答题卡
            if d(text="答题卡").exists(timeout=0.3):
                d(text="答题卡").click()
                time.sleep(1.2)
                save(d.dump_hierarchy(), "answer_card")
                log("      → 已打开答题卡（见 answer_card.xml）")
                # 尝试选第3项
                for e in (d.xpath('//*[@text!=""]').all() or []):
                    t = (e.text or "").strip()
                    if t in ("3", "第3题", "3/4"):
                        d.click((e.bounds[0] + e.bounds[2]) // 2, (e.bounds[1] + e.bounds[3]) // 2)
                        log(f"      → 答题卡点选 {t}")
                        time.sleep(1.5)
                        jumped = True
                        break
                if not jumped:
                    d.press("back")
                    time.sleep(0.8)
            if not jumped:
                log("      ⚠ 无跳转手段，停止探测")
                return 1
    return 1


def _describe(xml):
    """打印命中页面里所有文本节点 + pic_iv + ll_container 的 bounds。"""
    log("\n===== 页面结构明细 =====")
    log("-- ll_container --")
    for m in re.finditer(r'<node[^>]*resource-id="([^"]*ll_container)"[^>]*bounds="([^"]+)"', xml):
        log(f"   {m.group(1)}  {m.group(2)}")
    log("-- pic_iv --")
    for m in re.finditer(r'<node[^>]*resource-id="([^"]*pic_iv)"[^>]*bounds="([^"]+)"', xml):
        log(f"   {m.group(1)}  {m.group(2)}")
    log("-- 文本节点（text 与 bounds 按真实属性顺序解析）--")
    for m in re.finditer(r"<node[^>]*>", xml):
        seg = m.group(0)
        tm = re.search(r'text="([^"]*)"', seg)
        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', seg)
        rm = re.search(r'resource-id="([^"]*)"', seg)
        if tm and tm.group(1).strip() and bm:
            rid = (rm.group(1) or "").split("/")[-1] if rm else ""
            log(f"   y={int(bm.group(2)):>5} x={int(bm.group(1)):>5}  [{rid:<22}] {tm.group(1)[:70]!r}")


if __name__ == "__main__":
    sys.exit(main())
