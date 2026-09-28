# -*- coding: utf-8 -*-
"""TTS → 虚拟声卡 音频注入工具（路线① 的核心组件）。

链路：
    Windows SAPI 合成 WAV  →  定向播放到「VB-Audio Virtual Cable(播放端)」
    →  虚拟线  →  「VB-Audio Virtual Cable(录音端)」  →  模拟器/App 的麦克风

为什么是这套：
  真机上我们验证过——外放 TTS 会被 App 的 AEC 滤掉、adb 又无法注入音频（2026-08-23）。
  而虚拟声卡是「设备级」注入：App 打开录音时拿到的就是 TTS 的 PCM，不经过任何声学路径，
  AEC 无回声可消、也不受环境噪音影响。

依赖：sounddevice + numpy（装在隔离 venv: .../envs/ttsinject）。
      WAV 合成走 PowerShell 的 System.Speech，不需要 pywin32。

用法：
    python tts_inject.py devices                     # 列设备（找 VB-Cable 索引）
    python tts_inject.py synth "apple" -o a.wav      # 只合成
    python tts_inject.py play a.wav                  # 播放到虚拟声卡
    python tts_inject.py inject "apple"              # 合成+播放
    python tts_inject.py loopback                    # ★ 自检：播进去再从录音端录回来
    python tts_inject.py loopback --text "apple"     # 自检并保留录音
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
import sounddevice as sd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = os.path.join(ROOT, "tmp_gen", "tts")
os.makedirs(TMP, exist_ok=True)

CABLE_KEY = "CABLE"          # 设备名关键词（VB-Audio Virtual Cable）


# ────────────────────────── 设备发现 ──────────────────────────

def find_devices(verbose=False, prefer=("MME", "DirectSound", "WASAPI")):
    """返回 (out_dev, in_dev, info)。out=播放端(声音进虚拟线)，in=录音端(声音从虚拟线出来)。

    为什么首选 MME 而不是 WASAPI（实测结论，反直觉但很重要）：
      本机装的是 VB-CABLE Driver Pack 43，它的 WASAPI 端点「能打开、全零输出」——
      播放流和录音流都开成功（采样率已对齐 48000/44100），但录音端采到的全是 0.0。
      MME 端点则实测可通（峰值 0.25）。MME 层自带采样率转换，兼容性最好，
      代价是延迟高（~100ms），而语音评测对这种延迟完全不敏感。
      → 需要换机器复现时，用 `probe` 子命令扫描全部组合，不要盲信优先级。
    """
    devs = sd.query_devices()
    apis = sd.query_hostapis()

    def api_name(d):
        try:
            return apis[d["hostapi"]]["name"]
        except Exception:
            return ""

    def best(pred):
        cands = []
        for i, d in enumerate(devs):
            if CABLE_KEY.lower() not in d["name"].lower():
                continue
            if not pred(d):
                continue
            rank = len(prefer)
            for k, p in enumerate(prefer):
                if p.lower() in api_name(d).lower():
                    rank = k
                    break
            cands.append((rank, i, d))
        cands.sort(key=lambda x: x[0])
        return (cands[0][1], cands[0][2]) if cands else (None, None)

    out_dev, out_d = best(lambda d: d["max_output_channels"] > 0)
    in_dev, in_d = best(lambda d: d["max_input_channels"] > 0)

    if verbose:
        print("=== 全部音频设备 ===")
        for i, d in enumerate(devs):
            mark = ""
            low = d["name"].lower()
            if CABLE_KEY.lower() in low and d["max_output_channels"] > 0:
                mark = " <== 虚拟线·播放端"
            if CABLE_KEY.lower() in low and d["max_input_channels"] > 0:
                mark += " <== 虚拟线·录音端"
            print("  [%2d] in=%-2d out=%-2d sr=%-7s %-28s %s%s" % (
                i, d["max_input_channels"], d["max_output_channels"],
                int(d["default_samplerate"]),
                "(" + api_name(d) + ")", d["name"][:52], mark))
        print("=> 选用 播放端=%s 录音端=%s" % (out_dev, in_dev))
        if out_d:
            print("   播放端: %s (%s)" % (out_d["name"], api_name(out_d)))
        if in_d:
            print("   录音端: %s (%s)" % (in_d["name"], api_name(in_d)))

    info = {}
    if out_d:
        info["out"] = out_d
    if in_d:
        info["in"] = in_d
    return out_dev, in_dev, info


# ────────────────────────── WAV 合成（SAPI）──────────────────────────

def synth_wav(text, out_path, voice=None, rate=0, volume=100):
    """用 Windows System.Speech 合成英文 WAV。默认优先英文女声 Zira。"""
    out_path = os.path.abspath(out_path)
    if os.path.exists(out_path):
        os.remove(out_path)
    # 单引号包裹，内部的单引号翻倍
    def q(s):
        return "'" + str(s).replace("'", "''") + "'"

    voice_line = ""
    if voice:
        voice_line = ("try { $s.SelectVoice(%s) } catch { }" % q(voice))
    else:
        # 自动挑英文语音
        voice_line = (
            "$v = $s.GetInstalledVoices() | Where-Object { "
            "$_.VoiceInfo.Culture.Name -like 'en*' } | Select-Object -First 1; "
            "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) }"
        )

    ps = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "%s; "
        "$s.Rate = %d; $s.Volume = %d; "
        "$s.SetOutputToWaveFile(%s); "
        "$s.Speak(%s); "
        "$s.Dispose(); "
        "Write-Output 'SYNTH_OK'"
    ) % (voice_line, int(rate), int(volume), q(out_path), q(text))

    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True, timeout=120, errors="replace")
    ok = os.path.exists(out_path) and os.path.getsize(out_path) > 1000
    return ok, (r.stdout or "").strip(), (r.stderr or "").strip(), out_path


def read_wav(path):
    """读 16bit PCM WAV → (numpy float32 [-1,1], samplerate, channels)。"""
    import wave
    with wave.open(path, "rb") as w:
        ch = w.getnchannels()
        sw = w.getsampwidth()
        sr = w.getframerate()
        n = w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 1:
        a = (np.frombuffer(raw, dtype="<u1").astype(np.float32) - 128) / 128.0
    elif sw == 4:
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError("不支持的位深: %d" % sw)
    if ch > 1:
        a = a.reshape(-1, ch)
    return a, sr, ch


def dev_sr(dev):
    """设备默认采样率。WASAPI 共享模式要求流采样率与设备一致（否则 PaError -9997）。"""
    return int(sd.query_devices(dev)["default_samplerate"])


def resample(x, sr_in, sr_out):
    """线性插值重采样。语音带宽窄，线性插值足够（22.05k↔44.1k 是整数倍，几乎无损）。"""
    x = np.asarray(x, dtype=np.float32)
    if sr_in == sr_out or x.size == 0:
        return x
    n_out = int(round(x.shape[0] * float(sr_out) / float(sr_in)))
    if n_out <= 0:
        return x
    src = np.arange(x.shape[0], dtype=np.float64)
    dst = np.linspace(0, x.shape[0] - 1, n_out)
    if x.ndim > 1:
        return np.stack([np.interp(dst, src, x[:, c]) for c in range(x.shape[1])],
                        axis=1).astype(np.float32)
    return np.interp(dst, src, x).astype(np.float32)


# ────────────────────────── 播放 ──────────────────────────

def play(path, out_dev=None, blocking=True):
    a, sr, ch = read_wav(path)
    if out_dev is None:
        out_dev, _, _ = find_devices()
    if out_dev is None:
        raise RuntimeError("找不到 VB-Cable 播放端，请确认驱动已安装")
    if a.ndim > 1:
        a = a.mean(axis=1)
    sr_out = dev_sr(out_dev)
    a = resample(a, sr, sr_out)
    sd.play(a, samplerate=sr_out, device=out_dev, blocking=blocking)
    if blocking:
        sd.stop()
    return {"device": out_dev, "sr_src": sr, "sr_out": sr_out,
            "frames": int(a.shape[0]),
            "duration": round(a.shape[0] / float(sr_out), 3),
            "peak": round(float(np.max(np.abs(a))) if a.size else 0.0, 4)}


# ────────────────────────── 自检（回环）──────────────────────────

def _frame_rms(x, sr, win_ms=50):
    """按 50ms 分帧算 RMS，用于区分「信号段」与「静音段」。"""
    n = max(1, int(sr * win_ms / 1000.0))
    k = x.shape[0] // n
    if k < 1:
        return np.array([float(np.sqrt(np.mean(x ** 2)))]) if x.size else np.array([0.0])
    f = x[:k * n].reshape(k, n)
    return np.sqrt(np.mean(f ** 2, axis=1))


def _write_wav(path, mono, sr):
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((np.clip(mono, -1, 1) * 32767).astype("<i2").tobytes())


def loopback(text="apple", out_dev=None, in_dev=None, keep=False, save_src=None):
    """★ 核心自检：把 TTS 播进虚拟线，同时从虚拟线的录音端录回来，比较能量。

    判定用「分帧 RMS 的 90 分位 / 10 分位」而不是「前 0.3s 当底噪」：
    虚拟线启动瞬间会有 pop，把 pop 当底噪会得出「链路不通」的假结论（实测踩过）。
    只看「有没有一段显著高于静音底噪的能量」才是通路是否成立的正确判据。
    """
    if out_dev is None or in_dev is None:
        o, i, _ = find_devices()
        out_dev = out_dev if out_dev is not None else o
        in_dev = in_dev if in_dev is not None else i
    if out_dev is None or in_dev is None:
        return {"ok": False, "stage": "device", "msg": "找不到 VB-Cable 端点"}

    wav = save_src or os.path.join(TMP, "_loopback_src.wav")
    ok, so, se, _ = synth_wav(text, wav)
    if not ok:
        return {"ok": False, "stage": "synth", "stdout": so, "stderr": se}
    a, sr_src, ch = read_wav(wav)
    if a.ndim > 1:
        a = a.mean(axis=1)

    # ★ 双向重采样：WASAPI 播放流要匹配播放设备采样率，录音流要匹配录音设备采样率，
    #   两者常常不同（实测 48000 vs 44100），不匹配直接 PaError -9997。
    sr_out = dev_sr(out_dev)
    sr_in = dev_sr(in_dev)
    a_out = resample(a, sr_src, sr_out)
    play_dur = a_out.shape[0] / float(sr_out)

    # ★ 用显式 InputStream/OutputStream，不用 sd.rec + sd.play
    #   sounddevice 的 sd.rec/sd.play 共用同一套全局流状态（_last_callback/_streams），
    #   同时调用会互相干扰（实测表现为录音端全 0 / 采到未初始化内存）。
    rec_chunks = []
    in_sr = dev_sr(in_dev)

    def _cb(indata, frames, tinfo, status):
        rec_chunks.append(indata.copy())

    out_stream = sd.OutputStream(samplerate=sr_out, channels=1,
                                 device=out_dev, dtype="float32")
    in_stream = sd.InputStream(samplerate=in_sr, channels=2, device=in_dev,
                               dtype="float32", callback=_cb)
    in_stream.start()
    time.sleep(0.5)                        # 让录音流先跑稳
    out_stream.start()
    out_stream.write(a_out.reshape(-1, 1).astype(np.float32))
    out_stream.stop()
    out_stream.close()
    time.sleep(1.0)
    in_stream.stop()
    in_stream.close()

    r = np.concatenate(rec_chunks, axis=0) if rec_chunks else np.zeros((0, 1), "float32")
    r = r.mean(axis=1) if r.ndim > 1 else r.reshape(-1)
    sr_in = in_sr
    fr = _frame_rms(r, sr_in, 50)
    sig = float(np.percentile(fr, 90))
    noise = float(np.percentile(fr, 10))
    peak = float(np.max(np.abs(r))) if r.size else 0.0
    snr = (sig / noise) if noise > 1e-9 else float("inf")

    rec_out = os.path.join(TMP, "_loopback_rec.wav")
    try:
        _write_wav(rec_out, r, sr_in)
    except Exception:
        rec_out = ""

    passed = bool(peak > 0.01 and snr > 3.0)
    return {
        "ok": True,
        "text": text,
        "out_dev": out_dev, "in_dev": in_dev,
        "sr_src": sr_src, "sr_out": sr_out, "sr_in": sr_in,
        "play_dur_s": round(play_dur, 3),
        "src_peak": round(float(np.max(np.abs(a))) if a.size else 0.0, 4),
        "rec_peak": round(peak, 4),
        "sig_rms_p90": round(sig, 6),
        "noise_rms_p10": round(noise, 6),
        "snr": (round(snr, 1) if snr != float("inf") else "inf"),
        "verdict": "✅ 虚拟线通路成立（录音端确实取到了 TTS 音频）" if passed
                   else "❌ 未检测到音频",
        "rec_wav": rec_out,
    }


def probe(text="apple"):
    """扫描所有 (播放端, 录音端) 宿主 API 组合，报告哪一组能通。

    为什么需要它：VB-Cable 的 WASAPI 端点在本机会开成功但录到全零，
    不同驱动版本/机器表现不同。与其猜优先级，不如全测一遍（约 4s × N 组）。
    """
    devs = sd.query_devices()
    apis = sd.query_hostapis()

    def api(i):
        try:
            return apis[devs[i]["hostapi"]]["name"]
        except Exception:
            return "?"

    outs = [i for i, d in enumerate(devs)
            if CABLE_KEY.lower() in d["name"].lower() and d["max_output_channels"] > 0]
    ins = [i for i, d in enumerate(devs)
           if CABLE_KEY.lower() in d["name"].lower() and d["max_input_channels"] > 0]
    print("候选播放端:", [(i, api(i)) for i in outs])
    print("候选录音端:", [(i, api(i)) for i in ins])

    src = os.path.join(TMP, "_probe_src.wav")
    ok, so, se, _ = synth_wav(text, src)
    if not ok:
        return {"ok": False, "stage": "synth", "stderr": se}

    rows = []
    for o in outs:
        for i in ins:
            try:
                r = loopback(text, o, i, save_src=src)
                rows.append({"play": o, "play_api": api(o),
                             "rec": i, "rec_api": api(i),
                             "rec_peak": r.get("rec_peak"),
                             "snr": r.get("snr"),
                             "pass": "✅" if r.get("verdict", "").startswith("✅") else "❌"})
            except Exception as e:
                rows.append({"play": o, "play_api": api(o),
                             "rec": i, "rec_api": api(i),
                             "rec_peak": None, "snr": None,
                             "pass": "ERR", "err": str(e)[:80]})
            print("  play=%s(%s) rec=%s(%s) -> %s peak=%s snr=%s"
                  % (o, api(o), i, api(i), rows[-1]["pass"],
                     rows[-1]["rec_peak"], rows[-1]["snr"]))
    good = [r for r in rows if r["pass"] == "✅"]
    print()
    print("可用组合 %d / %d" % (len(good), len(rows)))
    for g in good:
        print("  ✅ play=%s(%s) + rec=%s(%s)" % (g["play"], g["play_api"],
                                                 g["rec"], g["rec_api"]))
    return {"ok": True, "rows": rows, "good": good}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["devices", "synth", "play", "inject",
                                       "loopback", "probe"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("-o", "--out", default="")
    ap.add_argument("--text", default="apple")
    ap.add_argument("--out-dev", type=int, default=None)
    ap.add_argument("--in-dev", type=int, default=None)
    ap.add_argument("--voice", default=None)
    ap.add_argument("--rate", type=int, default=0)
    a = ap.parse_args()

    if a.action == "probe":
        text = a.args[0] if a.args else a.text
        res = probe(text)
        print(json.dumps({k: v for k, v in res.items() if k != "rows"},
                         ensure_ascii=False, indent=2))
        return

    if a.action == "devices":
        find_devices(verbose=True)
        return

    if a.action == "synth":
        text = a.args[0] if a.args else a.text
        out = a.out or os.path.join(TMP, "out.wav")
        ok, so, se, p = synth_wav(text, out, a.voice, a.rate)
        print("synth ok=%s -> %s (%d bytes)" % (ok, p, os.path.getsize(p) if os.path.exists(p) else 0))
        if so:
            print("stdout:", so[:300])
        if se:
            print("stderr:", se[:500])
        return

    if a.action == "play":
        p = a.args[0] if a.args else a.out
        info = play(p, a.out_dev)
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return

    if a.action == "inject":
        text = a.args[0] if a.args else a.text
        out = a.out or os.path.join(TMP, "_inject.wav")
        ok, so, se, p = synth_wav(text, out, a.voice, a.rate)
        if not ok:
            print("!! 合成失败:", se[:400])
            sys.exit(2)
        info = play(p, a.out_dev)
        info["text"] = text
        info["wav"] = p
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return

    if a.action == "loopback":
        text = a.args[0] if a.args else a.text
        res = loopback(text, a.out_dev, a.in_dev)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return


if __name__ == "__main__":
    main()
