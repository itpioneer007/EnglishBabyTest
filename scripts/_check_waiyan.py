"""真机检查：自动进入「切换课本」页，扫描所有教材系列，判断是否含「外研版」。

- 找到外研版：打印存在的版本名 + 其下年级，测评可继续。
- 未找到：打印「未查到该版本，测评结束。」并回主页停止。
"""
import os, sys, time

BASE = r"C:\Users\yangj\Desktop\EnglishBabyTest-yangjiangliu"
SCRIPTS = os.path.join(BASE, "scripts")
for p in (SCRIPTS, os.path.join(SCRIPTS, "common"), BASE):
    if p not in sys.path:
        sys.path.insert(0, p)

import uiautomator2 as u2
from common.setup import _enter_switchbook, _norm, S_swipe, _back_home

SERIAL = "adb-AJ5KUT2B25008138-TFCx69._adb-tls-connect._tcp"
TARGET = "外研版"

PKG = "com.dinoenglish.yyb"
d = u2.connect(SERIAL)
print(f">> 已连接设备: {SERIAL}")

# ★ 确保英语宝在前台（当前可能停在别的应用，如作业帮，导致进不了切换课本页）
print(f">> 启动英语宝({PKG}) 到前台...")
try:
    d.app_start(PKG)
except Exception as _e:
    print(f"   app_start 失败, 尝试 resume: {_e}")
    try:
        d.app_resume(PKG)
    except Exception:
        pass
time.sleep(4)

# ★ 自动点击：进入「切换课本」页
print(">> 自动点击进入「切换课本」页...")
if not _enter_switchbook(d):
    print("✘ 无法进入切换课本页，终止")
    sys.exit(1)
print(">> 已进入切换课本页，开始扫描所有教材系列...")

# 回到页面顶部（版本分组从上方开始）
for _ in range(3):
    S_swipe(d, 540, 650, 540, 1850, 0.3)
    time.sleep(0.4)

versions = []          # 去重后的版本/系列标题（原始 text）
seen_norm = set()
current_vn = None      # 顺序扫描：跨屏保留的当前版本（用于归属年级）
grades_under = []      # [(版本_norm, 年级_text)]

for _scan in range(15):
    try:
        elems = d.xpath('//*[@text!=""]').all()
    except Exception:
        elems = []
    nodes = []
    for e in elems:
        t = (e.text or "").strip()
        if not t:
            continue
        tn = _norm(t)
        try:
            b = e.bounds
        except Exception:
            b = None
        if not b:
            continue
        # 版本标题：含'版'/'审定'，不含年级/册/切换/如何，长度<=20
        if (('版' in t or '审定' in t) and '年级' not in t and '册' not in t
                and '切换' not in t and '如何' not in t and len(t) <= 20):
            nodes.append((b[3], 'ver', t, tn, None))
        # 年级封面：含'年级'且含'册'
        elif '年级' in t and '册' in t:
            nodes.append((b[1], 'grade', t, tn, e))
    nodes.sort(key=lambda x: x[0])
    page_has_node = bool(nodes)
    for y, typ, t, tn, e in nodes:
        if typ == 'ver':
            current_vn = tn
            if tn not in seen_norm:
                seen_norm.add(tn)
                versions.append(t)
        elif typ == 'grade':
            grades_under.append((current_vn, t, tn))
    if not page_has_node:
        # 本屏无任何版本/年级节点，可能已到底
        S_swipe(d, 540, 1850, 540, 650, 0.45)
        time.sleep(0.7)
        continue
    # 下滑继续
    S_swipe(d, 540, 1850, 540, 650, 0.45)
    time.sleep(0.7)

print("\n>> 扫描到的所有教材系列（共 %d 个）：" % len(versions))
for v in versions:
    print("   -", v)

# 判断外研版
found = [v for v in versions if TARGET in _norm(v)]
if found:
    print(f"\n✅ 已找到「外研版」：{found}")
    # 列出外研版分组下的年级
    target_norms = {_norm(v) for v in found}
    waiyan_grades = sorted({g for cv, g, gn in grades_under if cv in target_norms},
                           key=lambda s: _norm(s))
    if waiyan_grades:
        print("   外研版下的年级：")
        for g in waiyan_grades:
            print("     ·", g)
    print("✅ 外研版存在，测评可继续。")
else:
    print("\n⚠ 未查到该版本（外研版），测评结束。")

_back_home(d)
print(">> 已返回主页。")
