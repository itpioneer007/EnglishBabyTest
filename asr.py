"""
asr.py — 本地 Whisper / 云端 Whisper 双后端语音转文字
=====================================================
把听力音频(任意格式)转成文字，供「转写 ↔ 题干」比对、以及 LLM 反推答案使用。

双后端：
  ① local  （默认）：faster-whisper 本地推理，首次需联网下载模型权重
                    （tiny≈75MB / base≈140MB / small≈460MB），下载后离线可用。
                    ⚠ 国内若 hf-mirror 下载报 401，请设环境变量
                      HF_ENDPOINT=https://huggingface.co  或手动下载模型到缓存目录。
  ② cloud （推荐，规避 HF 401）：走 OpenAI 兼容的 /v1/audio/transcriptions 接口，
                    无需下载模型，只要有 ASR_API_KEY 即可。支持任意兼容端点
                    （含国内中转 / 自建 whisper 服务）。

依赖：
  - 本地后端：faster-whisper（CTranslate2，无需 torch）、imageio-ffmpeg、numpy
  - 云端后端：requests（项目已装；OpenAI 兼容接口用表单上传音频）

配置（写在 .env 或环境变量）：
  ASR_BACKEND      funasr | cloud | local（不填：优先级 funasr→cloud→local 自动选）
                     funasr = 本地 SenseVoice(FunASR)，模型自 modelscope.cn 下载，无需 key，国内可直连
                     cloud  = OpenAI 兼容 /v1/audio/transcriptions，需 ASR_API_KEY
                     local  = 本地 faster-whisper，首次需从 HuggingFace 下载模型（国内可能被墙）
  # 本地后端（faster-whisper）
  WHISPER_MODEL    tiny/base/small/medium/large，默认 base
  WHISPER_DEVICE   cpu（默认）；有 NVIDIA 显卡填 cuda
  WHISPER_COMPUTE  int8（默认，最快）/ int8_float16 / float16
  HF_ENDPOINT      HuggingFace 镜像（国内被墙时改 huggingface.co 或手动下载）
  # 本地后端（FunASR / SenseVoice，推荐国内用户）
  FUN_MODEL        iic/SenseVoiceSmall（默认，多语种含英文，CPU 可跑）
  # 云端后端
  ASR_API_BASE     OpenAI 兼容地址，默认 https://api.openai.com/v1
  ASR_API_KEY      API Key（必填，否则云端后端不可用）
  ASR_MODEL        whisper-1（默认）

对外接口（与原 NLS / 听力专项.py 完全兼容）：
  transcribe(audio_path, lang="en") -> str      # 返回转写文本（失败抛 ASRError）
  available() -> bool                            # 当前后端是否可用
  backend() -> str                               # "cloud" | "local"
"""
import io
import os
import subprocess
import wave

# 本地模型库改为懒加载：走云端 ASR 时不需要 import torch/faster-whisper/funasr，
# 避免触发 torch 段错误、transformers 版本警告等问题。
np = None  # numpy 同样按需加载

def _import_numpy():
    global np
    if np is None:
        try:
            import numpy as _np
            np = _np
        except Exception as e:
            raise ASRError(f"本地 ASR 需要 numpy: {e}")
    return np


def _import_whisper_model():
    """懒加载 faster-whisper 的 WhisperModel。"""
    try:
        from faster_whisper import WhisperModel
        return WhisperModel
    except Exception as e:
        raise ASRError(f"加载 faster-whisper 失败: {e}")


def _import_funasr_model():
    """懒加载 funasr 的 AutoModel。"""
    try:
        from funasr import AutoModel as _FunAutoModel
        return _FunAutoModel
    except Exception as e:
        raise ASRError(f"加载 funasr 失败: {e}")


class ASRError(Exception):
    pass


# ── .env 零依赖加载（项目未用 python-dotenv，这里自己读）──────
def _load_env_file():
    """从项目根 .env 读取 WHISPER_* / ASR_* 等配置到 os.environ（不覆盖已存在的变量）。"""
    candidates = []
    try:
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        candidates.append(os.path.join(root, ".env"))
    except Exception:
        pass
    candidates.append(os.path.join(os.getcwd(), ".env"))
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass
            break


_load_env_file()

# ── HuggingFace 镜像（仅本地后端用到；云端后端不经过此处）──────
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"


def _env(k, default=""):
    return os.environ.get(k, default).strip()


def _any_asr_key():
    """返回可用的 ASR key：优先 ASR_API_KEY，否则用 LLM_API_KEY（百炼/DashScope 通用）。"""
    return _env("ASR_API_KEY") or _env("LLM_API_KEY")


def _any_asr_base():
    """返回可用的 ASR base：优先 ASR_API_BASE，否则用 LLM_BASE_URL（百炼兼容接口）。"""
    return _env("ASR_API_BASE") or _env("LLM_BASE_URL") or "https://api.openai.com/v1"


def backend():
    """当前生效后端：funasr（本地 SenseVoice）/ cloud（云端 Whisper）/ local（faster-whisper）。"""
    b = _env("ASR_BACKEND", "").lower()
    if b == "cloud":
        return "cloud"
    if b == "funasr":
        return "funasr"
    if b == "local":
        return "local"
    # 自动：配置了 key 优先走云端（最稳，不依赖本地模型）
    if _any_asr_key():
        return "cloud"
    return "local"


def available():
    """后端是否可用（云端只需 key；本地/FunASR 需运行时 import 成功）。"""
    b = backend()
    if b == "cloud":
        return bool(_any_asr_key())
    if b == "funasr":
        try:
            _import_funasr_model()
            return True
        except Exception:
            return False
    # local
    try:
        _import_whisper_model()
        _import_numpy()
        return True
    except Exception:
        return False


# ── 本地模型（懒加载：首次 transcribe 时初始化并下载权重）──────
_MODEL = None
_MODEL_SIZE = None


def _get_model():
    global _MODEL, _MODEL_SIZE
    size = _env("WHISPER_MODEL", "base") or "base"
    device = _env("WHISPER_DEVICE", "cpu") or "cpu"
    compute = _env("WHISPER_COMPUTE", "int8") or "int8"
    if _MODEL is not None and _MODEL_SIZE == size:
        return _MODEL
    WhisperModel = _import_whisper_model()
    _import_numpy()
    try:
        _MODEL = WhisperModel(size, device=device, compute_type=compute)
        _MODEL_SIZE = size
    except Exception as e:
        # ★ 401 / 网络失败时给出可执行的修复提示，而不是笼统报错
        _hint = ""
        if "401" in str(e) or "ENOTFOUND" in str(e) or "Connection" in str(e):
            _hint = ("（HuggingFace 镜像下载被拒/超时；请尝试：① 设 ASR_BACKEND=cloud 并填 "
                     "ASR_API_KEY 走云端 Whisper，彻底规避模型下载；或 ② 设 "
                     "HF_ENDPOINT=https://huggingface.co 后重试；或 ③ 手动下载 "
                     "Systran/faster-whisper-%s 模型放到 CTranslate2 缓存目录）" % size)
        raise ASRError(f"加载 Whisper 模型[{size}]失败: {e}{_hint}")
    return _MODEL


# ── 音频读取（任意格式 → 16k 单声道 float32 numpy）──────
def _load_audio(audio_path):
    """用 imageio-ffmpeg 把音频解码成 16k 单声道 float32 numpy，供 Whisper 推理。"""
    np = _import_numpy()
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:
        raise ASRError(f"缺少 imageio-ffmpeg（无法解码音频）: {e}")
    try:
        proc = subprocess.run(
            [ff, "-i", audio_path, "-f", "wav", "-ar", "16000",
             "-ac", "1", "-acodec", "pcm_s16le", "-"],
            capture_output=True, check=True)
        raw = proc.stdout
    except Exception as e:
        raise ASRError(f"ffmpeg 解码音频失败: {e}")
    try:
        wf = wave.open(io.BytesIO(raw))
        n = wf.getnframes()
        data = wf.readframes(n)
        wf.close()
        arr = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        return arr
    except Exception as e:
        raise ASRError(f"解析 wav 失败: {e}")


# ── 云端 ASR：优先百炼 DashScope Qwen-ASR，回退 OpenAI 兼容接口 ──────
def _transcribe_cloud(audio_path, lang="en"):
    """云端转写：优先用阿里云百炼 DashScope 的 qwen3-asr-flash（本地文件直传），
    失败则回退到 OpenAI 兼容的 /v1/audio/transcriptions。

    配置：ASR_API_KEY 或 LLM_API_KEY；ASR_MODEL 可填 qwen3-asr-flash / whisper-1 等。
    """
    key = _any_asr_key()
    if not key:
        raise ASRError("云端 ASR 未配置：请设置 ASR_API_KEY 或 LLM_API_KEY")

    # 1) 优先 DashScope SDK（qwen3-asr-flash 支持本地文件，自动上传 OSS）
    model = _env("ASR_MODEL", "qwen3-asr-flash")
    if model in ("qwen3-asr-flash", "qwen-asr-flash", "qwen-asr"):
        try:
            return _transcribe_dashscope_qwen(audio_path, key, model, lang)
        except ASRError:
            raise
        except Exception as e:
            # SDK 失败则继续尝试 OpenAI 兼容接口
            pass

    # 2) 回退 OpenAI 兼容 /v1/audio/transcriptions
    return _transcribe_openai_compatible(audio_path, key, model, lang)


def _transcribe_dashscope_qwen(audio_path, key, model="qwen3-asr-flash", lang="en"):
    """DashScope 非实时语音识别（Qwen-ASR），支持本地文件上传。"""
    try:
        import dashscope
    except Exception as e:
        raise ASRError(f"DashScope ASR 需要 dashscope 库: {e}（pip install dashscope）")

    dashscope.api_key = key
    # Windows 路径转 file:// 协议：C:\a\b.wav -> file://C:/a/b.wav
    abs_path = os.path.abspath(audio_path)
    file_url = abs_path.replace("\\", "/")
    if not file_url.startswith("file://"):
        file_url = "file://" + file_url

    messages = [{"role": "user", "content": [{"audio": file_url}]}]
    asr_options = {"enable_itn": False}
    if lang:
        asr_options["language"] = lang

    try:
        resp = dashscope.MultiModalConversation.call(
            model=model,
            messages=messages,
            result_format="message",
            asr_options=asr_options,
        )
    except Exception as e:
        raise ASRError(f"DashScope ASR 调用失败: {e}")

    if resp.status_code != 200:
        raise ASRError(f"DashScope ASR 返回 {resp.status_code}: {getattr(resp, 'message', '')}")

    try:
        choices = resp.output.choices
        if choices and choices[0].message.content:
            text = choices[0].message.content[0].get("text", "")
        else:
            text = ""
    except Exception as e:
        raise ASRError(f"解析 DashScope ASR 响应失败: {e}")

    text = (text or "").strip()
    if not text:
        raise ASRError("DashScope ASR 未返回文字（音频可能为空 / 太短 / 无语音）")
    return text


def _transcribe_openai_compatible(audio_path, key, model="whisper-1", lang="en"):
    """OpenAI 兼容 /v1/audio/transcriptions 接口。"""
    try:
        import requests
    except Exception as e:
        raise ASRError(f"云端 ASR 需要 requests 库: {e}（pip install requests）")
    base = _env("ASR_API_BASE", "https://api.openai.com/v1") or "https://api.openai.com/v1"
    url = base.rstrip("/") + "/audio/transcriptions"
    try:
        with open(audio_path, "rb") as f:
            files = {"file": (os.path.basename(audio_path), f, "audio/wav")}
            data = {"model": model}
            if lang:
                data["language"] = lang
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {key}"},
                files=files, data=data, timeout=120)
        if resp.status_code != 200:
            raise ASRError(f"云端 ASR 返回 {resp.status_code}: {resp.text[:200]}")
        text = (resp.json().get("text") or "").strip()
    except ASRError:
        raise
    except Exception as e:
        raise ASRError(f"云端 ASR 调用失败: {e}")
    if not text:
        raise ASRError("云端 ASR 未返回文字（音频可能为空 / 太短 / 无语音）")
    return text


# ── 本地 SenseVoice（FunASR，国内可直连 modelscope，无需 key）──────
_FUN_MODEL = None


def _get_funasr_model():
    global _FUN_MODEL
    if _FUN_MODEL is not None:
        return _FUN_MODEL
    _FunAutoModel = _import_funasr_model()
    model_id = _env("FUN_MODEL", "iic/SenseVoiceSmall") or "iic/SenseVoiceSmall"
    try:
        _FUN_MODEL = _FunAutoModel(
            model=model_id,
            trust_remote_code=True,
            disable_update=True,
            device="cpu",
        )
    except Exception as e:
        _hint = ""
        if "401" in str(e) or "Connection" in str(e) or "ENOTFOUND" in str(e):
            _hint = ("（模型下载失败；SenseVoice 应自 modelscope.cn 下载，若仍被墙，请设 "
                     "MODELSCOPE_ENDPOINT=https://modelscope.cn 或手动下载）")
        raise ASRError(f"加载 SenseVoice 模型[{model_id}]失败: {e}{_hint}")
    return _FUN_MODEL


def _transcribe_funasr(audio_path, lang="en"):
    """本地 SenseVoice（FunASR）转写：直接吃 wav 文件，支持英文，无需 key。

    模型 iic/SenseVoiceSmall 多语种（中/英/日/韩/粤），自 modelscope.cn 下载，国内可直连。
    输出会带 <|en|><|NEUTRAL|> 这类标签，这里统一清掉只留正文。
    """
    import re as _re
    model = _get_funasr_model()
    # SenseVoice 语言参数：auto / zh / en / ja / ko / yue
    _lang_map = {"en": "en", "zh": "zh", "ja": "ja", "ko": "ko",
                 "yue": "yue", None: "auto", "": "auto"}
    sv_lang = _lang_map.get(lang, "auto")
    try:
        res = model.generate(
            input=audio_path,
            language=sv_lang,
            batch_size=1,
            sentence_timestamp=False,
        )
        text = ""
        if res and isinstance(res, list):
            item = res[0]
            text = item.get("text", "") if isinstance(item, dict) else str(item)
        # 清理 SenseVoice 的情绪/语言标签，如 <|en|><|NEUTRAL|><|Amused|>...
        text = _re.sub(r"<\|[^|]+\|>", "", text or "")
    except Exception as e:
        raise ASRError(f"SenseVoice 转写失败: {e}")
    text = (text or "").strip()
    if not text:
        raise ASRError("SenseVoice 未返回文字（音频可能为空 / 太短 / 无语音）")
    return text


# ── 转写主入口（按后端路由）──────
def transcribe(audio_path, lang="en"):
    """把音频文件转写成文字。

    lang: "en" 英文（默认，听力专项使用）/ "zh" 中文 / None 自动检测。
    返回转写文本字符串；任何失败抛 ASRError。
    """
    if not os.path.exists(audio_path):
        raise ASRError(f"音频文件不存在: {audio_path}")
    # 路由：funasr（本地 SenseVoice）→ cloud（云端 Whisper）→ local（faster-whisper）
    b = backend()
    if b == "funasr":
        return _transcribe_funasr(audio_path, lang)
    if b == "cloud" and _any_asr_key():
        return _transcribe_cloud(audio_path, lang)
    # 本地 faster-whisper 后端
    if b == "local" and not available():
        raise ASRError("本地 Whisper 不可用（faster-whisper / numpy 未安装）")
    try:
        audio = _load_audio(audio_path)
    except ASRError:
        raise
    if audio is None or len(audio) == 0:
        raise ASRError("音频内容为空")
    model = _get_model()
    try:
        kwargs = {"beam_size": 5}
        if lang:
            kwargs["language"] = lang
        segments, _info = model.transcribe(audio, **kwargs)
        text = "".join(seg.text for seg in segments)
    except Exception as e:
        raise ASRError(f"Whisper 转写失败: {e}")
    text = (text or "").strip()
    if not text:
        raise ASRError("Whisper 未返回任何文字（音频可能为空 / 太短 / 无语音）")
    return text


if __name__ == "__main__":
    import sys
    print("backend():", backend(), "| available():", available())
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        try:
            print(transcribe(sys.argv[1]))
        except ASRError as e:
            print("ASR 错误:", e)
    else:
        print("用法: python asr.py <audio.wav>")
