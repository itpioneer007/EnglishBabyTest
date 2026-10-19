"""回归：跨设备差异的显式化（环境自检 / 设备解耦 / 能力降级）

背景（2026-10-19 用户报）：同一份代码在作者真机上正常，同事手机与 MuMu 模拟器上
各出不同问题。排查结论不是"代码随机"，而是运行条件不同却被当成同一条件：

  1. 设备串号硬编码在 config.yaml（作者真机）→ 别人电脑 adb 一律 not found；
  2. 参考图库是本机绝对路径（D:\\压缩包存储）→ 别人机器上缺失，视觉核对静默跳过；
  3. 屏幕 dp 不同 → Android 布局重排，按像素比例换算的坐标只能近似；
  4. 模拟器响应慢 → 固定超时被当成"控件找不到"，题目被记成未检测到；
  5. App 版本/LLM 密钥/录音能力不同 → 有的维度能做、有的做不了，报告却一样。

本测试锁住四件事：
  A. env_check 能把这些条件探测出来并给出阻断/降级结论；
  B. 阻断项会真正拦住任务（预检在清状态之前），降级项会进日志与报告；
  C. 设备串号不再硬编码，所有 adb 通路统一走 _intended_serial()；
  D. 模拟器的超时倍数生效，真机不受影响。

跑法：python scripts/tests/test_fix_20261019c_env_check.py
"""
import io
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "scripts"))

PASS = FAIL = 0


def chk(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f"  << {detail}" if detail else ""))


def _read(p):
    return (_ROOT / p).read_text(encoding="utf-8")


print("=" * 68)
print("T1  env_check 基本契约：无设备时阻断，且不抛异常")
print("=" * 68)
import common.env_check as ec  # noqa: E402

_orig_online = ec._online_serials
_orig_run = ec._run
ec._online_serials = lambda adb: []
_r = ec.run_check("", remember=False)
chk("无在线设备 → ok=False", _r["ok"] is False)
chk("无在线设备 → blockers 非空", len(_r["blockers"]) >= 1, str(_r["blockers"]))
chk("阻断文案以「当前没有已连接的设备」开头或含之",
    any("当前没有已连接的设备" in b for b in _r["blockers"]),
    str(_r["blockers"])[:120])
chk("阻断文案不以「请」开头（陈述在前、建议在后）",
    all(not b.startswith("请") for b in _r["blockers"]))
chk("无设备时不产生假能力（record=None）", _r["capabilities"]["record"] is None)


print("=" * 68)
print("T2  设备探测：分辨率 / dpi / dp / 布局是否重排")
print("=" * 68)

_FAKE = {
    "getprop": (
        "[ro.product.model]: [Pixel 7]\n"
        "[ro.product.brand]: [google]\n"
        "[ro.build.version.release]: [14]\n"
        "[ro.build.characteristics]: [default]\n"
    ),
    "wm size": "Physical size: 1080x2400\n",
    "wm density": "Physical density: 480\n",
    "dumpsys power": "mWakefulness=Awake\n",
    "dumpsys package": "versionName=5.2.1\n",
    "pm list features": "feature:android.hardware.microphone\n",
}


def _fake_run(adb, serial, args, timeout=6):
    key = " ".join(args)
    # 生产代码统一走 `adb shell <cmd>`；这里剥掉 shell 前缀再匹配
    key = key[6:] if key.startswith("shell ") else key
    for k, v in _FAKE.items():
        if key.startswith(k):
            return 0, v
    return 0, ""


ec._online_serials = lambda adb: ["SKSCIF4T7PFMQS5X"]
ec._run = _fake_run
ec._find_adb = lambda: "/fake/adb"

_rs = ec.device_snapshot("SKSCIF4T7PFMQS5X")
_d = _rs["device"]
chk("真机可达", _d["reachable"] is True)
chk("分辨率解析为 1080x2400", _d["size"] == [1080, 2400], str(_d["size"]))
chk("dpi 解析为 480", _d["density"] == 480, str(_d["density"]))
chk("dp 解析为 360x800", _d["dp"] == [360, 800], str(_d["dp"]))
chk("1080x2400@480dpi → 布局与基准一致",
    _d["layout_matches_reference"] is True, str(_d["layout_matches_reference"]))
chk("真机判定 emulator=False", _d["emulator"] is False)
chk("App 版本读到 5.2.1", _d["app_version"] == "5.2.1", _d["app_version"])
chk("麦克风 feature → record_capable=True", _d["record_capable"] is True)

# 换成模拟器（900x1600@240dpi → 600x1067dp，布局必然重排）
_FAKE["wm size"] = "Physical size: 900x1600\n"
_FAKE["wm density"] = "Physical density: 240\n"
_FAKE["getprop"] = (
    "[ro.product.model]: [MuMu]\n"
    "[ro.product.brand]: [Netease]\n"
    "[ro.build.version.release]: [12]\n"
    "[ro.kernel.qemu]: [1]\n"
)
ec._online_serials = lambda adb: ["127.0.0.1:16384"]
_rm = ec.device_snapshot("127.0.0.1:16384")
_m = _rm["device"]
chk("模拟器判定 emulator=True", _m["emulator"] is True)
chk("900x1600@240dpi → dp=600x1067", _m["dp"] == [600, 1067], str(_m["dp"]))
chk("布局标记为与基准不同", _m["layout_matches_reference"] is False)
chk("给出「布局与基准不同」的降级提示",
    any("布局" in w or "重排" in w for w in _rm["warnings"]), str(_rm["warnings"])[:200])
chk("给出模拟器提示（布局/音频差异）",
    any("模拟器" in w for w in _rm["warnings"]))


print("=" * 68)
print("T3  设备不可达 / App 未安装 / 串号不在线")
print("=" * 68)
ec._online_serials = lambda adb: ["AAA"]
_r3 = ec.device_snapshot("BBB")
chk("串号不在线 → reachable=False", _r3["device"]["reachable"] is False)
chk("串号不在线 → 阻断说明含该串号",
    any("BBB" in b for b in _r3["blockers"]), str(_r3["blockers"]))

_FAKE2 = dict(_FAKE)


def _fake_run_noapp(adb, serial, args, timeout=6):
    key = " ".join(args)
    key = key[6:] if key.startswith("shell ") else key
    if key.startswith("dumpsys package"):
        return 0, "Packages:\n"
    return _fake_run(adb, serial, args, timeout)


ec._run = _fake_run_noapp
ec._online_serials = lambda adb: ["127.0.0.1:16384"]
_r4 = ec.device_snapshot("127.0.0.1:16384")
chk("App 未安装 → app_installed=False", _r4["device"]["app_installed"] is False)
chk("App 未安装 → 阻断（而不是等到首页找不到入口才报）",
    any("未安装" in b for b in _r4["blockers"]), str(_r4["blockers"]))


print("=" * 68)
print("T4  本机环境：目录可写 / 参考图库 / 依赖 / LLM 配置")
print("=" * 68)
ec._run = _fake_run
_ls = ec.local_snapshot()["local"]
chk("项目目录可写", _ls["root_writable"] is True, str(_ls["dirs"]))
chk("关键依赖齐全", all(_ls["deps"].values()), str(_ls["deps"]))
chk("参考图库路径已解析（含相对路径转绝对）",
    all(os.path.isabs(p) for p in _ls["ref_images"]["configured"]),
    str(_ls["ref_images"]["configured"]))
chk("相对路径 uploads/ref_images 以项目根解析",
    any(p.endswith(os.path.join("uploads", "ref_images"))
        and os.path.isabs(p) for p in _ls["ref_images"]["configured"]))
chk("没有出现「未配置参考图库」这类假告警",
    not any("未配置参考图库" in w for w in ec.local_snapshot()["warnings"]))


print("=" * 68)
print("T5  能力映射：缺密钥/缺参考图库 → 对应维度关掉")
print("=" * 68)
_caps = ec._capabilities(
    {"record_capable": False, "emulator": True, "layout_matches_reference": False},
    {"llm": {"text_key": True, "vision_key": False},
     "ref_images": {"existing": []}})
chk("无参考图库 → vision_ref=False", _caps["vision_ref"] is False)
chk("有文本密钥 → llm_text=True", _caps["llm_text"] is True)
chk("无视觉密钥 → llm_vision=False", _caps["llm_vision"] is False)
chk("无麦克风 → record=False", _caps["record"] is False)

_lines = ec.capability_lines(_caps)
chk("能力说明含「本轮不做」", any("本轮不做" in x for x in _lines), str(_lines))
chk("能力说明明确「不计为不通过」",
    any("不计为不通过" in x for x in _lines), str(_lines))


print("=" * 68)
print("T6  format_lines：阻断优先，其次能力边界")
print("=" * 68)
_f = ec.format_lines({"ok": False, "blockers": ["当前没有已连接的设备。"],
                      "warnings": ["x"], "device": {}, "capabilities": {}})
chk("有阻断时只输出阻断行", len(_f) == 1 and _f[0].startswith("检测未开始"), str(_f))
_f2 = ec.format_lines({
    "ok": True, "blockers": [], "warnings": ["参考图库不可用。"],
    "device": {"brand": "google", "model": "Pixel 7", "size": [1080, 2400],
               "density": 480, "app_version": "5.2.1", "emulator": False},
    "capabilities": {"vision_ref": False, "llm_text": True, "llm_vision": True,
                     "record": True}})
chk("环境行包含型号与分辨率",
    any("Pixel 7" in x and "1080x2400" in x for x in _f2), str(_f2))
chk("降级项以「能力边界：」开头", any(x.startswith("能力边界：") for x in _f2))
chk("能力边界里不出现 emoji",
    not any(re.search(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", x) for x in _f2))


print("=" * 68)
print("T7  web_server 接入：路由 + 预检 + 串号解耦")
print("=" * 68)
_ws = _read("web_server.py")
chk("有 /api/env/check 路由", '"/api/env/check"' in _ws)
chk("有 _preflight_env()", "def _preflight_env(" in _ws)
chk("/api/modules/run 里调用 _preflight_env",
    re.search(r"_env_ok,\s*_env_msg\s*=\s*_preflight_env\(", _ws) is not None)
chk("预检失败返回 400（不是继续跑）",
    "return jsonify({\"error\": _env_msg}), 400" in _ws)
chk("get_adb() 不再直接读 config.device.serial",
    "ADBController(serial=_intended_serial() or config.device.serial" in _ws)
chk("重启 App / 截图通路改用 adb.serial",
    "[adb_path, '-s', adb.serial," in _ws)
chk("/api/status 透出 env 摘要", '"env": _env_brief(device_ok)' in _ws)
chk("/api/status 透出逻辑尺寸与布局标记",
    '"coord_layout_shifted": _layout_shifted' in _ws)
chk("报告 meta 带 env", '"env": _env_report_meta()' in _ws)

# 预检必须在清状态之前（否则注定失败的运行会清掉上一轮结果）
_i_pre = _ws.find("_env_ok, _env_msg = _preflight_env(_cur_serial)")
_i_clr = _ws.find("_inspection_state[\"questions\"] = {}", _i_pre)
chk("环境预检在清空审查结果之前", 0 < _i_pre < _i_clr, f"{_i_pre} vs {_i_clr}")


print("=" * 68)
print("T8  config.yaml：不写死他人设备与个人路径")
print("=" * 68)
_cfg = _read("config.yaml")
chk("config.yaml 不再含作者真机串号", "SKSCIF4T7PFMQS5X" not in _cfg)
chk("device.serial 留空（自动选在线设备）",
    re.search(r"^\s*serial:\s*[\"']{0,2}\s*$", _cfg, re.M) is not None)
chk("有 runtime.emulator_timeout_scale", "emulator_timeout_scale" in _cfg)
chk("image_dir 含项目内相对路径", "uploads/ref_images" in _cfg)
import yaml  # noqa: E402
_c = yaml.safe_load(_cfg)
chk("YAML 可解析", isinstance(_c, dict))
chk("runtime 下 emulator_timeout_scale 在合理区间",
    1.0 <= float(_c["runtime"]["emulator_timeout_scale"]) <= 5.0)


print("=" * 68)
print("T9  scheduler：模拟器超时倍数生效，真机保持 1.0")
print("=" * 68)
_sched_src = _read("scripts/scheduler.py")
chk("有 _timeout_scale()", "def _timeout_scale(" in _sched_src)
chk("HTTP_TIMEOUT 乘了倍数", "_u2.HTTP_TIMEOUT = int(15 * _ts)" in _sched_src)
chk("主页等待也乘了倍数", "int(25 * _ts)" in _sched_src)

import scheduler as sch  # noqa: E402
_old_env = os.environ.get("ANDROID_SERIAL", "")
os.environ["ANDROID_SERIAL"] = "SKSCIF4T7PFMQS5X"
sch._T_SCALE_CACHE = None
chk("真机（无 host:port）→ 倍数 1.0", sch._timeout_scale() == 1.0,
    str(sch._timeout_scale()))
os.environ["ANDROID_SERIAL"] = "127.0.0.1:16384"
sch._T_SCALE_CACHE = None
chk("模拟器（host:port）→ 倍数 2.0", sch._timeout_scale() == 2.0,
    str(sch._timeout_scale()))
if _old_env:
    os.environ["ANDROID_SERIAL"] = _old_env
else:
    os.environ.pop("ANDROID_SERIAL", None)
sch._T_SCALE_CACHE = None


print("=" * 68)
print("T10 报告：环境块渲染（设备 / 不做维度 / 提示）")
print("=" * 68)
from src.report_exporter import ReportExporter  # noqa: E402

_exp = ReportExporter(save_dir=str(_ROOT / "outputs" / "_env_test"))
_meta = {"env": {
    "available": True,
    "device": {"brand": "Netease", "model": "MuMu", "size": [900, 1600],
               "density": 240, "dp": [600, 1067], "app_version": "5.2.1",
               "emulator": True, "layout_matches_reference": False},
    "capabilities": {"vision_ref": False, "llm_text": True, "llm_vision": False,
                     "record": False},
    "warnings": ["模拟器未声明麦克风能力。"],
}}
_html = _exp._render_env_block(_meta)
chk("报告环境块非空", bool(_html.strip()))
chk("含设备型号", "MuMu" in _html)
chk("含逻辑尺寸", "600" in _html and "1067" in _html)
chk("含「本轮未做」", "本轮未做" in _html)
chk("未做的维度里包含配图内容核对", "配图内容核对" in _html)
chk("含环境提示折叠块", "环境提示（1 项）" in _html)
chk("标注模拟器", "模拟器" in _html)
chk("无 env 时返回空串（不污染旧报告）", _exp._render_env_block({}) == "")
chk("环境块不含 emoji",
    not re.search(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", _html))


print("=" * 68)
print("T11  /api/hardware-info 不引未定义常量、单条 adb 失败不拖垮整块")
print("=" * 68)
_hw_src = _read("web_server.py")
_ap_lines = [_l.strip() for _l in _hw_src.split("\n")
             if "APP_PACKAGE" in _l and not _l.strip().startswith("#")]
chk("不再引用裸 APP_PACKAGE（注释除外）", not _ap_lines, _ap_lines[:3])
chk("包名从 config 取并有兜底", '_pkg = getattr(getattr(config, "app", None), "package"' in _hw_src)
chk("_p 单条失败返回空串", "单条命令失败不应让整块信息全空" in _hw_src)
chk("emulator 在 try 外赋值（不受 adb 失败影响）",
    '_intended_serial() or config.device.serial' in _hw_src
    and 'info = {"serial": serial, "screen": "", "emulator":' in _hw_src)

try:
    os.environ["no_proxy"] = "127.0.0.1,localhost"
    import web_server as _wsv  # noqa: E402
    _c = _wsv.app.test_client()
    _rh = _c.get("/api/hardware-info")
    _jh = _rh.get_json() or {}
    chk("/api/hardware-info 返回 200", _rh.status_code == 200, str(_rh.status_code))
    chk("返回体含 emulator 字段（bool）", isinstance(_jh.get("emulator"), bool), str(_jh))
    chk("返回体含 serial 字段", "serial" in _jh)
    if _jh.get("screen"):
        chk("screen 形如 WxH", re.fullmatch(r"\d+x\d+", _jh["screen"]) is not None,
            _jh.get("screen"))
    print("     hardware:", {k: _jh.get(k) for k in
                             ("serial", "model", "screen", "density", "dp",
                              "app_version", "emulator")})
except Exception as _e:
    chk("/api/hardware-info 可调用", False, repr(_e))


print("=" * 68)
print("T12  真实自检可执行（当前无设备时不得抛异常）")
print("=" * 68)
ec._run = _orig_run
ec._online_serials = _orig_online
try:
    _real = ec.run_check("", remember=False)
    chk("run_check 可执行", isinstance(_real, dict))
    chk("返回 ok 字段", "ok" in _real)
    chk("返回 capabilities 字段", "capabilities" in _real)
    print("     当前环境：ok=%s blockers=%d warnings=%d"
          % (_real["ok"], len(_real["blockers"]), len(_real["warnings"])))
    for _ln in ec.format_lines(_real)[:4]:
        print("     ·", _ln[:100])
except Exception as e:
    chk("run_check 可执行", False, repr(e))

print()
print("=" * 68)
print(f"结果：{PASS} 通过 / {FAIL} 失败")
print("=" * 68)
sys.exit(1 if FAIL else 0)
