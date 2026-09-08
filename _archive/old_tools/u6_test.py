"""U6 听力专项 去练习 → 开始答题 → 遍历"""
import uiautomator2 as u2, time

d = u2.connect()
print("✅ 已连接")

# === 1. 确保在听力专项页 ===
print("[1] 进听力专项...")
for _ in range(8):
    d.press("back"); time.sleep(0.4)
d.app_start("com.dinoenglish.yyb"); time.sleep(2.5)

for _ in range(8):
    if d(text="听力专项").exists(timeout=1.5): break
    d.swipe(500,1400,500,400,0.3); time.sleep(0.4)
d(text="听力专项").click(); time.sleep(1.6)
print("   ✅ 已在听力专项")

# === 2. 滚到 Unit 6 ===
print("[2] 找 Unit 6...")
for _ in range(12):
    els = [e.text for e in (d.xpath('//*[@text!=""]').all() or [])]
    if any(t and t.startswith("Unit 6") for t in els):
        break
    d.swipe(500,1400,500,400,0.3); time.sleep(0.4)
print("   ✅ 找到 Unit 6")

# === 3. 点 U6 的 去练习 ===
print("[3] 点 U6 去练习...")
# 找 Unit 6 那一行的 去练习
unit_texts = [(e, e.text, e.bounds[1]) for e in (d.xpath('//*[@text!=""]').all() or []) if (e.text or "").startswith("Unit ")]
btn_els = d.xpath('//*[@text="去练习"]').all() or []

for ue, uname, uy in unit_texts:
    if "Unit 6" in (uname or ""):
        for be in btn_els:
            if abs(be.bounds[1] - uy) < 100:
                be.click(); time.sleep(1.6)
                print(f"   ✅ 点击 @{uname}")
                break
        break

# === 4. 检查页面，点开始答题/重新答题 ===
print("[4] 检查答题入口...")
time.sleep(1.2)
els = [e.text for e in (d.xpath('//*[@text!=""]').all() or [])]
print("   页面:", sorted(set(els))[:10])

# 点重新答题/开始答题/去练习
for kw in ("重新答题","开始答题","去练习","进入"):
    if d(text=kw).exists(timeout=2):
        d(text=kw).click(); time.sleep(1.2)
        print(f"   ✅ 点击 {kw}")
        break

# === 5. 答题循环 ===
print("[5] 答题...")
q = 0
while q < 20:
    # 检查是否回到单元详情（完成标志）
    if d(text="重新答题").exists(timeout=1):
        print(f"   ⏹ 回到单元详情（完成）")
        break

    # 截图
    d.screenshot(f"u6_Q{q+1}.png")
    q += 1
    print(f"   📸 第{q}题")

    # 选答案
    for opt in ("A","B","C","T","F"):
        if d(text=opt).exists(timeout=0.15):
            d(text=opt).click(); time.sleep(0.5)
            break

    # 检查
    for kw in ("检查","提交"):
        if d(text=kw).exists(timeout=1.5):
            d(text=kw).click(); time.sleep(0.4)
            break

    # 下一题
    for kw in ("下一题","继续"):
        if d(text=kw).exists(timeout=2):
            d(text=kw).click(); time.sleep(0.8)
            break
    else:
        if d(text="重新答题").exists(timeout=2):
            break

print(f"\n✅ U6 答题完成，共{q}题")
