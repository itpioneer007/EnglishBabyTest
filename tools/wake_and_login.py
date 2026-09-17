# -*- coding: utf-8 -*-
"""诊断/恢复：唤醒屏幕并把英语宝恢复到「已登录 + 主页」状态。

背景：设备息屏后 uiautomator dump 拿不到 UI，scheduler 的"切版本/年级"与
"找模块入口"都会失败 → 任务跑出 0 题（实测 2026-09-15，App 停在 UserLoginActivity）。
"""
import re
import sys
import time

import uiautomator2 as u2

PKG = "com.dinoenglish.yyb"


def wake(d):
    info = d.info or {}
    print(f"[info] screenOn={info.get('screenOn')} pkg={info.get('currentPackageName')}")
    if not info.get("screenOn"):
        d.screen_on()
        time.sleep(1.2)
    # 上滑解除锁屏（无密码设备）
    try:
        d.swipe(540, 1900, 540, 700, 0.1)
    except Exception as e:
        print(f"[warn] 上滑解锁异常: {e}")
    time.sleep(1.0)
    print(f"[info] after wake screenOn={(d.info or {}).get('screenOn')}")


def dump_texts(d):
    xml = d.dump_hierarchy()
    return xml, [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]


def ensure_front(d):
    cur = (d.app_current() or {}).get("package", "")
    if cur != PKG:
        print(f"[app] 前台是 {cur}，冷启动 {PKG}")
        d.app_start(PKG)
        time.sleep(3)
    else:
        print(f"[app] 前台已是 {PKG}")


def login_if_needed(d):
    xml, txts = dump_texts(d)
    if not any("学生登录" in t for t in txts):
        print("[login] 不在登录页，跳过")
        return True
    # 勾选协议（若未勾选）
    m = re.search(r'<node[^>]*resource-id="[^"]*check[^"]*"[^>]*checked="(true|false)"', xml, re.I)
    if m and m.group(1) == "false":
        print("[login] 勾选用户协议")
        for kw in ("我已阅读并同意", "隐私政策"):
            el = d(textContains=kw)
            if el.exists(timeout=0.5):
                el.click()
                time.sleep(0.4)
                break
    print("[login] 点击登录")
    ok = False
    for sel in (d(text="登录"), d(textContains="登 录")):
        try:
            if sel.exists(timeout=1.5):
                sel.click()
                ok = True
                break
        except Exception:
            pass
    if not ok:
        print("[login] ❌ 没找到登录按钮")
        return False
    # 等主页
    for i in range(20):
        time.sleep(1.5)
        _, txts2 = dump_texts(d)
        if any("教材精学" in t or "专项突破" in t or "听课文" in t for t in txts2):
            print(f"[login] ✅ 已进入主页（{i * 1.5:.0f}s）")
            print("[home] sample:", " | ".join(txts2[:25]))
            return True
    _, txts3 = dump_texts(d)
    print("[login] ⚠ 未见主页特征，当前文本:", " | ".join(txts3[:30]))
    return False


if __name__ == "__main__":
    dev = u2.connect()
    wake(dev)
    ensure_front(dev)
    ok = login_if_needed(dev)
    sys.exit(0 if ok else 1)
