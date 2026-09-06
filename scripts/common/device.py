"""设备管理：动态获取/选择 adb 设备序列号

解决多设备场景：队友手机占用了默认连接，导致本机设备离线。

核心机制：
- 设置 os.environ['ANDROID_SERIAL'] = 序列号
- uiautomator2 的 u2.connect() 原生读取 ANDROID_SERIAL → 所有模块自动连对设备，无需改模块代码
"""
import os


def list_devices():
    """返回所有已连接的 adb 设备: [{'serial': 'xxx', 'state': 'device'}]"""
    try:
        from adbutils import adb
        return [{"serial": d.serial, "state": "device"} for d in adb.device_list()]
    except Exception:
        return []


def get_serial():
    """当前选中的设备序列号（环境变量，空=默认）"""
    return os.environ.get("ANDROID_SERIAL", "").strip()


def set_device(serial):
    """设置当前设备序列号（写环境变量，u2.connect 全局生效）"""
    if serial:
        os.environ["ANDROID_SERIAL"] = serial
    else:
        os.environ.pop("ANDROID_SERIAL", None)


def get_device():
    """连接当前选中的设备（未设置则 u2.connect 默认）"""
    import uiautomator2 as u2
    return u2.connect()


def auto_select_first():
    """自动选择第一个在线设备并写 ANDROID_SERIAL。

    多设备场景：优先选 IP:端口 形式（如 192.168.x.x:port），
    把 mDNS 别名（adb-xxxx._adb-tls-connect._tcp）排后，
    避免 u2.connect() 因多设备报错。
    返回选中的序列号；无设备返回空串。
    """
    devs = list_devices()
    if not devs:
        return ""
    def _score(s):
        # IP:端口 形式优先（首字符是数字且含冒号）
        return 0 if (":" in s and s[0].isdigit()) else 1
    devs_sorted = sorted(devs, key=lambda d: _score(d.get("serial", "")))
    serial = devs_sorted[0]["serial"]
    set_device(serial)
    return serial


def device_ok(serial=None):
    """检查指定（或当前）设备是否在线。

    ★ 多设备兜底：未指定 serial 且未设置 ANDROID_SERIAL 时，
      自动选择第一个在线设备（避免 u2.connect() 因多设备报错）。
    """
    import uiautomator2 as u2
    old = os.environ.get("ANDROID_SERIAL", "")
    if serial:
        os.environ["ANDROID_SERIAL"] = serial
    elif not os.environ.get("ANDROID_SERIAL"):
        # 未选设备 → 自动选一个在线的，再检测
        try:
            auto_select_first()
        except Exception:
            pass
    try:
        d = u2.connect()
        info = d.info
        return bool(info)
    except Exception:
        return False
    finally:
        if serial:
            os.environ["ANDROID_SERIAL"] = old


if __name__ == "__main__":
    print("检测到的设备:")
    for dev in list_devices():
        print(f"  {dev['serial']}  [{dev['state']}]")
    print(f"当前选中: {get_serial() or '(默认)'}")
