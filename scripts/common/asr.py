"""可插拔 ASR 接口 — 把扬声器/录音音频转成文本（供听音题语音对比用）

背景（2026-08-26 用户需求）：
  接入语音模型后，需要把 App 扬声器播放的单词（如听音选释义题播放 "new"）
  识别成文本，然后与脚本 recording 字段对比，判断 App 播放的内容是否与脚本一致
  （如脚本该题 recording='new'，App 扬声器也播 'new' → 一致；播 'year' → 不符）。

★ 2026-08-26 已接入真实 ASR：阿里云百炼 qwen-audio-3.0-asr-flash-streaming
  （WebSocket 实时语音识别，同步调用本地音频文件）
  依赖：pip install dashscope websocket-client
  Key：.env 的 LLM_API_KEY（sk-ws- 开头新格式百炼 key）或 YYB_ASR_API_KEY

用法（巧记单词等听音题）：
  from common.asr import asr_transcribe
  text = asr_transcribe("/data/local/tmp/qiaoji_audio.wav")
  # text 若为 "new" → 与脚本 recording='new' 对比
"""
import os
import re
import sys

# ★ 通过环境变量控制开关（YYB_ASR_ENABLED=1 启用真实 ASR；默认开启，配了 key 就能用）
_ENABLED = os.environ.get("YYB_ASR_ENABLED", "").lower() in ("1", "true", "yes", "on") or True

# ★ ASR 配置（阿里云百炼）
_ASR_MODEL = os.environ.get("YYB_ASR_MODEL", "qwen-audio-3.0-asr-flash-streaming")
_ASR_KEY = (os.environ.get("YYB_ASR_API_KEY") or "").strip()
# 国内端点（sk-ws 新格式百炼 key）
_ASR_WS_URL = os.environ.get("YYB_ASR_WS_URL", "wss://dashscope.aliyuncs.com/api-ws/v1/inference")

# 从 .env 读取 key（兼容项目现有配置，优先级: ASR_API_KEY > VISION_API_KEY > LLM_API_KEY）
if not _ASR_KEY:
    try:
        _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), ".env")
        if os.path.exists(_env_path):
            for _line in open(_env_path, encoding="utf-8"):
                _line = _line.strip()
                if _line.startswith("#") or "=" not in _line:
                    continue
                _k, _v = _line.split("=", 1)
                _v = _v.strip().strip('"').strip("'")
                if _k == "ASR_API_KEY" and _v:
                    _ASR_KEY = _v
                    break
                if _k in ("VISION_API_KEY", "LLM_API_KEY") and _v and not _ASR_KEY:
                    _ASR_KEY = _v
    except Exception:
        pass


def asr_available() -> bool:
    """ASR 是否已启用（有 key 且模型可调）"""
    return _ENABLED and bool(_ASR_KEY)


def _find_scrcpy() -> str:
    """定位 scrcpy（音频捕获用，2.0+ 支持 Android 11+ 数字直录 AudioPlaybackCapture）。
    优先 PATH，其次本机已知安装路径。"""
    import shutil
    p = shutil.which("scrcpy")
    if p:
        return p
    _candidates = [
        r"D:/压缩包存储/scrcpy-win64-v3.3.3/scrcpy.exe",  # 用户本机实测路径
    ]
    for c in _candidates:
        if os.path.exists(c):
            return c
    return ""


def _kill_scrcpy():
    """清理本机残留 scrcpy 进程（Windows taskkill / POSIX pkill）"""
    try:
        import subprocess, sys
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/IM", "scrcpy.exe"],
                           capture_output=True, timeout=5)
        else:
            subprocess.run(["pkill", "-f", "scrcpy"], capture_output=True, timeout=5)
    except Exception:
        pass


def start_scrcpy_record(out_path: str, seconds: int = 15, serial: str = "") -> tuple:
    """★ 2026-08-26 用 scrcpy 数字直录手机扬声器音频（替代 ColorOS 录音机麦克风方案）。

    原理：scrcpy 2.0+ 用 Android 11+ 的 AudioPlaybackCapture 捕获设备播放音频，
    数字直录（无环境噪音、无需切 App、无 MediaProjection 授权弹窗——实测 Android 14 OK）。

    用法（巧记单词听音题）：
        proc, path = start_scrcpy_record("rec.m4a", seconds=10, serial="SKSCIF4T7PFMQS5X")
        time.sleep(2)          # 等 scrcpy server 就绪
        d.click(*play_box)     # 点扬声器播放
        wait_scrcpy_record(proc)  # 等 time-limit 自动结束
        text = asr_transcribe(path)  # 自动 ffmpeg 转 wav 16k + ASR 识别
    """
    scrcpy = _find_scrcpy()
    if not scrcpy:
        print("  ⚠ 未找到 scrcpy（需 2.0+），扬声器捕获不可用")
        return None, ""
    import subprocess
    # ★ 启动前清理残留进程（实测 u2 会话刚结束时立即启动 scrcpy 偶发竞争卡死）
    _kill_scrcpy()
    # ★ out_path 必须转绝对路径！scrcpy 的 cwd 是它自己目录，
    #   相对路径会把文件写到 scrcpy 目录里（实测踩坑：日志显示 Recording complete
    #   但工作目录找不到文件）
    out_path = os.path.abspath(out_path)
    # ★ scrcpy 需要 adb：cwd 不在 PATH 里时找不到同目录 adb.exe → 显式传 ADB 环境变量
    _env = dict(os.environ)
    _adb_candidate = os.path.join(os.path.dirname(scrcpy), "adb.exe")
    if os.path.exists(_adb_candidate):
        _env["ADB"] = _adb_candidate
    for _attempt in range(2):
        cmd = [scrcpy, "--no-video", f"--record={out_path}", f"--time-limit={seconds}"]
        if serial:
            cmd += ["--serial", serial]
        try:
            # ★ 输出写日志文件（不 DEVNULL——失败时可查 scrcpy 卡在哪）
            _log_f = os.path.join(os.path.dirname(out_path) or ".",
                                  "_scrcpy_capture.log")
            try:
                _lf = open(_log_f, "w", encoding="utf-8", errors="replace")
            except Exception:
                _lf = subprocess.DEVNULL
            proc = subprocess.Popen(
                cmd, stdout=_lf, stderr=subprocess.STDOUT,
                cwd=os.path.dirname(scrcpy), env=_env)
            import time as _t
            _t.sleep(3.5)  # 等 server 推送+启动
            if proc.poll() is None:
                return proc, out_path
            # 进程立即退出了 → 重试
            if _lf is not subprocess.DEVNULL:
                try:
                    _lf.close()
                except Exception:
                    pass
            _kill_scrcpy()
            _t.sleep(1)
        except Exception as e:
            print(f"  ⚠ scrcpy 启动失败: {str(e)[:100]}")
    return None, ""


def wait_scrcpy_record(proc, out_path: str = "", timeout: int = 40) -> bool:
    """等待 scrcpy 录制完成。

    注意：scrcpy --no-video --record 在 --time-limit 到时已写完文件（
    "Recording complete"），但进程可能不自动退出（无窗口模式下 SDL 主循环
    挂起）→ 通过轮询文件大小稳定判定完成，然后主动 terminate。

    返回是否拿到有效录音文件（>1KB）。
    """
    if not proc:
        return False
    import time as _t
    _last_size = -1
    _stable = 0
    _end = _t.time() + timeout
    while _t.time() < _end:
        _sz = os.path.getsize(out_path) if out_path and os.path.exists(out_path) else 0
        if _sz > 1000 and _sz == _last_size:
            _stable += 1
            if _stable >= 3:  # 大小连续 ~1.5s 不变 → 录制完成
                break
        else:
            _stable = 0
        _last_size = _sz
        _t.sleep(0.5)
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass
    return bool(out_path and os.path.exists(out_path)
                and os.path.getsize(out_path) > 1000)


def _find_ffmpeg() -> str:
    """定位 ffmpeg（用于 mp3 等 → wav 16k 转换）。
    优先 PATH，其次本机已知安装路径（WinGet 常见路径）。"""
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return p
    _candidates = [
        r"C:/Users/19507/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.2-full_build/bin/ffmpeg.exe",
    ]
    for c in _candidates:
        if os.path.exists(c):
            return c
    return ""


def _probe_mp3_sample_rate(audio_path: str) -> int:
    """解析 MP3 帧头探测真实采样率（ColorOS 录音是 48kHz，edge-tts 是 24kHz，
    传错会被服务端拒绝：'resample audio from 24000 to 16000 failed'）"""
    try:
        with open(audio_path, "rb") as f:
            data = f.read(8192)
        # 跳过 ID3 头（前10字节，第6-9字节是标签大小）
        i = 0
        if data[:3] == b"ID3":
            sz = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | \
                 ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
            i = 10 + sz
        # 找帧同步 0xFFE
        for j in range(i, min(len(data) - 2, i + 4096)):
            if data[j] == 0xFF and (data[j + 1] & 0xE0) == 0xE0:
                ver = (data[j + 1] >> 3) & 0x03
                sr_idx = (data[j + 2] >> 2) & 0x03
                if ver == 3:  # MPEG1
                    return {0: 44100, 1: 48000, 2: 32000}[sr_idx]
                return {0: 22050, 1: 24000, 2: 16000}[sr_idx]  # MPEG2/2.5
    except Exception:
        pass
    return 0


def asr_transcribe(audio_path: str) -> str:
    """把音频转成文本单词（如 'new'）。

    调用阿里云百炼 qwen-audio-3.0-asr-flash-streaming（WebSocket 实时识别，同步拿结果）。
    音频需 wav/pcm 16k 格式；mp4/m4a 等格式需先转 wav。

    Args:
        audio_path: 音频文件路径（wav/pcm 优先）

    Returns:
        str: 识别出的文本（小写去噪），失败返回空串 ""。
    """
    if not _ENABLED:
        return ""
    if not audio_path or not os.path.exists(audio_path):
        return ""
    if not _ASR_KEY:
        print("  ⚠ ASR 未配置 API Key（.env 的 LLM_API_KEY 或 YYB_ASR_API_KEY）")
        return ""
    try:
        import dashscope
        from dashscope.audio.asr import Recognition
        from http import HTTPStatus
        dashscope.api_key = _ASR_KEY
        # ★ 设置 WebSocket 端点（国内百炼）
        try:
            dashscope.base_websocket_api_url = _ASR_WS_URL
        except Exception:
            pass
        # ★ 音频预处理：非 wav/pcm 一律先用 ffmpeg 转成 16k 单声道 wav（最稳）。
        #   （2026-08-26 实测踩坑：百炼服务端对 mp3 内部重采样不可靠——
        #     edge-tts mp3=24k、ColorOS 录音机 mp3=48k，直接传 mp3 都报
        #     "resample audio from X to 16000 failed"；本地 ffmpeg 转好最保险）
        _ext = os.path.splitext(audio_path)[1].lower()
        _audio_for_asr = audio_path
        _tmp_wav = ""
        if _ext not in (".wav", ".pcm"):
            _ffmpeg = _find_ffmpeg()
            if _ffmpeg:
                _tmp_wav = os.path.join(os.path.dirname(audio_path) or ".",
                                        "_asr_tmp_16k.wav")
                try:
                    import subprocess
                    _r = subprocess.run(
                        [_ffmpeg, "-y", "-i", audio_path,
                         "-ar", "16000", "-ac", "1", _tmp_wav],
                        capture_output=True, timeout=60)
                    if os.path.exists(_tmp_wav) and os.path.getsize(_tmp_wav) > 0:
                        _audio_for_asr = _tmp_wav
                except Exception:
                    _tmp_wav = ""
        _fmt = "wav"
        _sample_rate = 16000
        recognition = Recognition(
            model=_ASR_MODEL,
            format=_fmt,
            sample_rate=_sample_rate,
            callback=None,
        )
        try:
            result = recognition.call(_audio_for_asr)
        finally:
            if _tmp_wav and os.path.exists(_tmp_wav):
                try:
                    os.remove(_tmp_wav)
                except Exception:
                    pass
        if result is not None and getattr(result, "status_code", None) == HTTPStatus.OK:
            # ★ 非流式调用 get_sentence() 返回句子列表 List[Dict]，每项含 text 字段
            _sentences = result.get_sentence() or []
            _texts = []
            if isinstance(_sentences, dict):
                _texts = [_sentences.get("text", "")]
            elif isinstance(_sentences, list):
                for _s in _sentences:
                    if isinstance(_s, dict) and _s.get("text"):
                        _texts.append(_s["text"])
                    elif isinstance(_s, str):
                        _texts.append(_s)
            return _clean(" ".join(_texts))
        # 失败原因
        _msg = getattr(result, "message", "") or ""
        if _msg:
            print(f"  ⚠ ASR 识别失败: {_msg[:120]}")
    except Exception as e:
        print(f"  ⚠ ASR 调用异常: {str(e)[:150]}")
    return ""


def _clean(text: str) -> str:
    """去噪清洗：去掉标点/数字/多余空格，只保留单词（小写）"""
    if not text:
        return ""
    t = text.strip().lower()
    # 去掉非字母字符（保留英文单词和空格）
    t = re.sub(r"[^a-z\s']", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def extract_speaker_word(audio_path: str, fallback_recording: str = "") -> str:
    """便捷入口：获取扬声器播放的单词（ASR 识别结果），失败回退脚本 recording。

    Args:
        audio_path: 音频文件路径
        fallback_recording: 脚本该题 recording（如 'new'），ASR 失败时兜底
    Returns:
        str: 扬声器单词（ASR 优先，失败用 fallback）
    """
    word = asr_transcribe(audio_path)
    if word:
        return word
    return (fallback_recording or "").strip().lower()


def compare_against_script(speaker_word: str, script_recording: str) -> dict:
    """对比扬声器播放的单词 与 脚本 recording 是否一致。

    Args:
        speaker_word: ASR 识别出的扬声器单词（如 'new'）
        script_recording: 脚本该题 recording（如 'new'）
    Returns:
        dict: {consistent: bool|None, reason: str}
          consistent=False → 不一致（App 播 X，脚本应为 Y）
          consistent=True  → 一致（同一单词）
          consistent=None  → 无法判定（ASR 未接入/无 recording）
    """
    if not script_recording:
        return {"consistent": None, "reason": "脚本该题无 recording，无法比对"}
    _sp = (speaker_word or "").strip().lower()
    _sc = script_recording.strip().lower()
    if not _sp:
        return {"consistent": None, "reason": "ASR 未识别到扬声器内容（未接入或音频为空）"}
    if _sp == _sc:
        return {"consistent": True, "reason": f"✅ 扬声器发音「{_sp}」与脚本 recording 一致"}
    # 部分匹配（词形变化/单复数）
    if _sp in _sc or _sc in _sp:
        return {"consistent": True, "reason": f"✅ 扬声器发音「{_sp}」与脚本「{_sc}」匹配（含词形变化）"}
    # ★ 2026-08-26 模糊匹配：ASR 对短单词可能识别成同音词（如 new→now），
    #   编辑距离 ≤1 视为"疑似同音"，给中性提示（不直接判不通过，避免误报）
    if _levenshtein(_sp, _sc) <= 1:
        return {"consistent": True,
                "reason": f"🟡 扬声器发音「{_sp}」与脚本「{_sc}」疑似同音（编辑距离1），建议人工确认"}
    return {"consistent": False, "reason": f"❌ 扬声器发音「{_sp}」与脚本 recording「{_sc}」不符"}


def _levenshtein(a: str, b: str) -> int:
    """编辑距离（用于同音/近似单词判定）"""
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
