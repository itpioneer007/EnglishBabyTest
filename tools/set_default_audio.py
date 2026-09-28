# -*- coding: utf-8 -*-
"""读写 Windows 默认音频端点（播放/录音）—— 用 pycaw 内置的 IPolicyConfig。

背景（实测结论，2026-09-17）：
    `mumu-cli setting --vmindex 0 --all` 列出 MuMu 12 全部 112 个配置键，
    **没有任何音频/麦克风设备选择项**（只有 system_volume_close）。
    → 模拟器麦克风只能来自「Windows 默认录音设备」。
    所以要让英语宝拿到 TTS 音频，只能把默认录音设备指向 CABLE Output。

实现：pycaw 已封装 IPolicyConfig（未公开 COM 接口），
      用 AudioUtilities.SetDefaultDevice + GetEndpointDataFlow 即可，无需手写 vtable。

用法：
    python tools/set_default_audio.py list                 # 列出全部端点
    python tools/set_default_audio.py current              # 当前默认
    python tools/set_default_audio.py backup               # 输出备份 JSON（重定向保存）
    python tools/set_default_audio.py set-in CABLE         # 默认录音→含CABLE的端点
    python tools/set_default_audio.py set-out CABLE        # 默认播放
    python tools/set_default_audio.py restore backup.json  # 还原
"""
import json
import sys
import warnings

warnings.filterwarnings("ignore")

try:
    import comtypes
    comtypes.CoInitialize()
    from pycaw.utils import AudioUtilities
    from pycaw.constants import ERole, EDataFlow
except Exception as e:
    print("pycaw/comtypes 不可用:", e)
    sys.exit(2)

ROLES = [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications]
FLOW_CN = {"eRender": "播放", "eCapture": "录音"}


def endpoints(include_point=False):
    """返回 [{'name','id','flow','flow_cn'}]。默认排除 VB-Audio Point（那是 VoiceMeeter 的）。"""
    res = []
    for d in AudioUtilities.GetAllDevices():
        name = d.FriendlyName
        if not name:
            continue
        if not include_point and "vb-audio point" in name.lower():
            continue
        try:
            flow = AudioUtilities.GetEndpointDataFlow(d.id)
        except Exception:
            flow = "eAll"
        res.append({"name": name, "id": d.id, "flow": flow,
                    "flow_cn": FLOW_CN.get(flow, flow)})
    res.sort(key=lambda x: (x["flow"], x["name"].lower()))
    return res


def current_default():
    """读当前默认端点（API 方式：GetDefaultAudioEndpoint）。"""
    out = {}
    try:
        devEnum = AudioUtilities.GetDeviceEnumerator()
    except Exception as e:
        return {"error": str(e)}
    for flow_name, flow in (("播放", EDataFlow.eRender),
                            ("录音", EDataFlow.eCapture)):
        out[flow_name] = {}
        for role in ROLES:
            try:
                dev = devEnum.GetDefaultAudioEndpoint(flow.value, role.value)
                disp = AudioUtilities.CreateDevice(dev)
                out[flow_name][role.name] = {"name": disp.FriendlyName,
                                             "id": disp.id}
            except Exception as e:
                out[flow_name][role.name] = {"error": str(e)}
    return out


def set_default(match, flow="eCapture", roles=None):
    roles = roles or ROLES
    cands = [e for e in endpoints() if e["flow"] == flow
             and match.lower() in e["name"].lower()]
    if not cands:
        print("未找到匹配端点 flow=%s match=%r。候选：" % (flow, match))
        for e in endpoints():
            if e["flow"] == flow:
                print("   ", e["name"])
        return False
    dev = cands[0]
    print("目标: [%s] %s\n  id=%s" % (dev["flow_cn"], dev["name"], dev["id"]))
    try:
        AudioUtilities.SetDefaultDevice(dev["id"], roles)
        print("  SetDefaultDevice OK (roles=%s)" % [r.name for r in roles])
        return True
    except Exception as e:
        print("  SetDefaultDevice 失败:", e)
        return False


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "list"

    if action == "list":
        for e in endpoints():
            print("[%s] %-52s\n      %s" % (e["flow_cn"], e["name"], e["id"]))

    elif action == "current":
        cur = current_default()
        for flow_name, roles in cur.items():
            print("=== %s ===" % flow_name)
            if isinstance(roles, dict):
                for role, info in roles.items():
                    print("   %-16s %s" % (role, info.get("name") or info))
            else:
                print("  ", roles)

    elif action == "backup":
        print(json.dumps(current_default(), ensure_ascii=False, indent=1))

    elif action in ("set-in", "set-out"):
        m = sys.argv[2] if len(sys.argv) > 2 else "CABLE"
        flow = "eCapture" if action == "set-in" else "eRender"
        ok = set_default(m, flow)
        print("\n结果:", "成功" if ok else "失败")
        if ok:
            print("\n=== 设置后默认 ===")
            cur = current_default()
            for flow_name, roles in cur.items():
                if isinstance(roles, dict):
                    mm = roles.get("eMultimedia", {}).get("name")
                    print("   %s(eMultimedia): %s" % (flow_name, mm))

    elif action == "restore":
        data = json.load(open(sys.argv[2], encoding="utf-8"))
        for flow_name, roles in data.items():
            flow = "eRender" if flow_name == "播放" else "eCapture"
            if not isinstance(roles, dict):
                continue
            for role_name, info in roles.items():
                if not isinstance(info, dict) or "id" not in info:
                    continue
                try:
                    role = next(r for r in ROLES if r.name == role_name)
                    AudioUtilities.SetDefaultDevice(info["id"], [role])
                    print("还原 %s/%s -> %s" % (flow_name, role_name, info["name"]))
                except Exception as e:
                    print("还原失败 %s/%s: %s" % (flow_name, role_name, e))
    else:
        print("未知动作:", action)


if __name__ == "__main__":
    main()
