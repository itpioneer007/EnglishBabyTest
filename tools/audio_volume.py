# -*- coding: utf-8 -*-
"""检查/设置音频端点音量与静音状态（VB-Cable 常见「装好了但没声音」根因）。

为什么需要：VB-CABLE 安装后，CABLE Input 在 Windows 音量合成器里的电平
可能不是 100%，或被静音 → 音频流写进去了但虚拟线里是静音。

用法：
    python tools/audio_volume.py list             # 列出所有端点 + 音量 + 静音
    python tools/audio_volume.py set 100          # 把所有含 CABLE 的端点设为 100% 且取消静音
"""
import sys

try:
    from pycaw.utils import AudioUtilities
    from pycaw.constants import EDataFlow, DEVICE_STATE
    from comtypes import CLSCTX_ALL, CoInitialize
except Exception as e:
    print("pycaw 不可用:", e)
    sys.exit(2)


def all_endpoints():
    """用 MMDeviceEnumerator 枚举所有 render/capture 端点。"""
    from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
    from pycaw.constants import CLSID_MMDeviceEnumerator
    from comtypes import CoCreateInstance
    import ctypes

    enum = CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator,
                            CLSCTX_ALL)
    out = []
    for flow, label in ((EDataFlow.eRender.value, "播放"),
                        (EDataFlow.eCapture.value, "录音")):
        coll = enum.EnumAudioEndpoints(flow, DEVICE_STATE.ACTIVE.value)
        n = coll.GetCount()
        for i in range(n):
            dev = coll.Item(i)
            # 友好名
            from pycaw.api.mmdeviceapi import IPropertyStore
            from pycaw.constants import STGM_READ
            from pycaw.utils import PROPERTYKEY
            store = dev.OpenPropertyStore(STGM_READ)
            name = "?"
            try:
                pv = store.GetValue(PROPERTYKEY(
                    "{a45c254e-df1c-4efd-8020-67d146a850e0}", 14))
                name = pv.GetValue()
            except Exception:
                try:
                    pv = store.GetValue(PROPERTYKEY(
                        "{b3f8fa53-0004-438e-9003-51a46e139bfc}", 6))
                    name = pv.GetValue()
                except Exception:
                    pass
            # 音量
            vol, mute = None, None
            try:
                from pycaw.api.endpointvolume import IAudioEndpointVolume
                itf = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                v = itf.QueryInterface(IAudioEndpointVolume)
                vol = round(v.GetMasterVolumeLevelScalar() * 100, 1)
                mute = bool(v.GetMute())
            except Exception:
                pass
            out.append({"flow": label, "name": name, "vol": vol,
                        "mute": mute, "raw": dev})
    return out


def set_cable(level=100):
    eps = all_endpoints()
    changed = []
    for ep in eps:
        if "cable" not in (ep["name"] or "").lower():
            continue
        try:
            from pycaw.api.endpointvolume import IAudioEndpointVolume
            itf = ep["raw"].Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            v = itf.QueryInterface(IAudioEndpointVolume)
            v.SetMute(0, None)
            v.SetMasterVolumeLevelScalar(level / 100.0, None)
            changed.append("%s %s -> %d%% 静音=否" % (ep["flow"], ep["name"], level))
        except Exception as e:
            changed.append("%s %s 设置失败: %s" % (ep["flow"], ep["name"], e))
    return changed


def main():
    CoInitialize()
    action = sys.argv[1] if len(sys.argv) > 1 else "list"
    if action == "list":
        eps = all_endpoints()
        print("=== 活动音频端点 %d 个 ===" % len(eps))
        for ep in eps:
            mark = "  <<< CABLE" if "cable" in (ep["name"] or "").lower() else ""
            print("  [%s] vol=%-6s mute=%-5s %s%s"
                  % (ep["flow"], ep["vol"], ep["mute"], ep["name"], mark))
    elif action == "set":
        lv = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        for line in set_cable(lv):
            print("  ", line)
        print("\n=== 设置后 ===")
        for ep in all_endpoints():
            if "cable" in (ep["name"] or "").lower():
                print("  [%s] vol=%-6s mute=%-5s %s"
                      % (ep["flow"], ep["vol"], ep["mute"], ep["name"]))
    else:
        print("未知动作:", action)


if __name__ == "__main__":
    main()
