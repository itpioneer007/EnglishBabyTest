"""巧记单词模拟流程测试：点关卡→进马上闯关→退出→下一个"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import uiautomator2 as u2
import re

d = u2.connect()

# 关卡位置（U1 地图）
LEVELS = {
    1: (681, 1593),
    2: (767, 1312),
    3: (583, 1096),
    4: (346, 923),
    5: (313, 642),
    'boss': (313, 619),  # boss关卡片
}

def find_levels():
    """动态找关卡数字位置"""
    pos = {}
    xml = d.dump_hierarchy()
    for m in re.finditer(r'text="(\d+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        t = int(m.group(1))
        x1,y1,x2,y2 = int(m.group(2)),int(m.group(3)),int(m.group(4)),int(m.group(5))
        if 400<y1<1800 and t<=99:
            pos[t] = ((x1+x2)//2, (y1+y2)//2)
    return pos

def enter_level(level_pos):
    """点关卡→马上闯关→进入答题页"""
    d.click(*level_pos)
    time.sleep(3)
    # 单词浏览页
    if d(text="马上闯关").exists(timeout=3):
        print(f"  ✅ 进入单词浏览页，点马上闯关")
        d(text="马上闯关").click()
        time.sleep(3)
        # 答题页
        texts = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
        qinfo = [t for t in texts if '/' in t and '关' in t]
        print(f"  📝 答题页: {qinfo[:1]}")
        return True
    elif d(text="马上闯关").exists(timeout=0.5) is False:
        # 可能直接进答题页或关卡锁定
        texts = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
        print(f"  ⚠ 未出现马上闯关: {texts[:4]}")
    return False

def exit_to_map():
    """从答题页/浏览页 back 回地图"""
    for _ in range(4):
        texts = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
        if 'boss关' in texts or any(t.isdigit() and int(t)<=9 for t in texts if t.isdigit()):
            return True
        d.press('back')
        time.sleep(1.5)
    return False

# ==== 主流程 ====
print("=== 模拟流程测试：U1 关卡 1-5 + boss ===")

# 当前在地图页，逐个进入关卡
for level_key in [1, 2, 3, 4, 5]:
    # 先确保在地图页
    texts = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
    if 'boss关' not in texts:
        print(f"  不在地图页，back 中...")
        exit_to_map()
    # 动态找关卡位置（地图可能刷新）
    pos = find_levels()
    if level_key not in pos:
        print(f"  ⚠ 找不到关卡 {level_key}，用固定坐标")
        pos[level_key] = LEVELS[level_key]
    print(f"\n🎮 关卡 {level_key} @ {pos[level_key]}")
    ok = enter_level(pos[level_key])
    if ok:
        exit_to_map()
        print(f"  ✅ 关卡 {level_key} 完成（进入答题页后退出）")
    else:
        print(f"  ❌ 关卡 {level_key} 失败")
        break

# boss 关
texts = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
if 'boss关' not in texts:
    exit_to_map()
print(f"\n🎮 boss关 @ {LEVELS['boss']}")
ok = enter_level(LEVELS['boss'])
if ok:
    print(f"  ✅ boss关 进入答题页")
    # boss 关退出后看下一单元
    exit_to_map()
    texts = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
    print(f"  boss关后地图: {texts[:10]}")
    # 点下一单元
    if d(text="下一单元").exists(timeout=2):
        d(text="下一单元").click()
        print(f"  ✅ 点下一单元")
        time.sleep(3)
        texts = [e.text for e in (d.xpath('//*[@text!=""]').all() or []) if e.text]
        print(f"  下一单元地图: {texts[:12]}")
else:
    print(f"  ❌ boss关 失败")

print("\n=== 模拟流程测试完成 ===")
