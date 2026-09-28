"""★ 2026-09-23 回归测试：文本主模型切换到 deepseek-v4.1-flash 的三处配置 + 缓存失效联动。

背景：
    原主模型 deepseek-v4-pro-0813 免费额度耗尽，稳定 403 AllocationQuota.FreeTierOnly，
    每次调用先失败一次再回落备用链（多一次往返，拖慢脚本审查）。
    用户指定换成 deepseek-v4.1-flash。

⚠ 本切换有一个**极易漏掉的坑**：
    deepseek-v4.1-flash 与 v4-pro-0813 同属**推理模型**。不关思维链时，实测
    200 max_tokens 会被 reasoning_content 全部吃光 ——
        usage: {"text_tokens": 0, "reasoning_tokens": 200}
        finish_reason: "length"
        content: ""            ← 正文完全为空，且**不报错**
    加 `enable_thinking: false` 后 1.43s 正常出文。
    所以"只改 model 名"是不够的，必须三处同步：
        .env 的 LLM_NO_THINK_MODELS / llm_config.json 的 no_think_models /
        代码侧 _NO_THINK_FALLBACK 兜底。

同时新增：**脚本审查缓存加入模型签名**。此前缓存只按 script_hash 判有效，
    换模型后旧单元会静默复用旧模型结论（表现为"换了模型，重跑结论一模一样"）。

本测试锁定：
  1) 三处配置都指向新模型，且新模型都在 no-think 白名单里
  2) 请求体真的带上了 enable_thinking=false（不靠网络，直接拦截请求体断言）
  3) 白名单不泄漏：非白名单模型不会被塞 enable_thinking
  4) 缓存签名真值表：换模型 → 不可复用；旧缓存（无签名）→ 不可复用
  5) _current_llm_signature() 形如 "<文本模型>|<视觉模型>"

运行：python scripts/tests/test_fix_20260923g_llm_model_switch.py
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import web_server as W  # noqa: E402
from src import reviewer_common as RC  # noqa: E402

PASS = 0
FAIL = []

NEW_MODEL = "deepseek-v4.1-flash"
OLD_MODEL = "deepseek-v4-pro-0813"


def chk(name, cond, extra=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL.append(name)
        print(f"  [FAIL] {name}  {extra}")


def read_env_file() -> dict:
    out = {}
    p = os.path.join(ROOT, ".env")
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ============================================================
print("=" * 70)
print("A. 配置文件三处同步")
print("=" * 70)
env = read_env_file()
chk(".env LLM_MODEL 已切到新模型",
    env.get("LLM_MODEL") == NEW_MODEL, f"实际={env.get('LLM_MODEL')!r}")
chk(".env LLM_NO_THINK_MODELS 含新模型",
    NEW_MODEL in [x.strip() for x in env.get("LLM_NO_THINK_MODELS", "").split(",")],
    f"实际={env.get('LLM_NO_THINK_MODELS')!r}")
chk(".env 仍保留旧模型在 no-think 白名单（切回时不会静默空输出）",
    OLD_MODEL in [x.strip() for x in env.get("LLM_NO_THINK_MODELS", "").split(",")])
chk(".env LLM_MODEL_FALLBACK 非空",
    bool(env.get("LLM_MODEL_FALLBACK", "").strip()))
chk(".env 视觉模型未被误改（仍是真看图模型）",
    "ocr" not in env.get("VISION_MODEL", "").lower() and bool(env.get("VISION_MODEL")))

cfg_path = os.path.join(ROOT, "llm_config.json")
cfg = json.loads(open(cfg_path, encoding="utf-8").read())
chk("llm_config.json model 已切到新模型",
    cfg.get("model") == NEW_MODEL, f"实际={cfg.get('model')!r}")
chk("llm_config.json no_think_models 含新模型",
    NEW_MODEL in [x.strip() for x in str(cfg.get("no_think_models", "")).split(",")],
    f"实际={cfg.get('no_think_models')!r}")
chk("llm_config.json model_fallback 非空", bool(str(cfg.get("model_fallback", "")).strip()))

# ============================================================
print()
print("=" * 70)
print("B. no-think 白名单（env 生效 + 代码兜底）")
print("=" * 70)
chk("no_think_models() 含新模型（.env 生效）", NEW_MODEL in RC.no_think_models(),
    f"实际={RC.no_think_models()}")
chk("代码侧 _NO_THINK_FALLBACK 含新模型（.env 丢失时的兜底）",
    NEW_MODEL in RC._NO_THINK_FALLBACK, f"实际={RC._NO_THINK_FALLBACK}")

_saved = os.environ.pop("LLM_NO_THINK_MODELS", None)
try:
    chk("清空 env 后仍含新模型（走代码兜底）", NEW_MODEL in RC.no_think_models(),
        f"实际={RC.no_think_models()}")
finally:
    if _saved is not None:
        os.environ["LLM_NO_THINK_MODELS"] = _saved

# ============================================================
print()
print("=" * 70)
print("C. LLMClient.from_config() 实际读到的配置")
print("=" * 70)
client = RC.LLMClient.from_config()
chk("from_config().model == 新模型", client.model == NEW_MODEL, f"实际={client.model!r}")
chk("新模型命中 no-think 白名单", client.model in RC.no_think_models())
chk("备用链非空", len(client.fallback_models()) >= 1, f"实际={client.fallback_models()}")
sig = W._current_llm_signature()
chk("_current_llm_signature() 形如 '<文本模型>|<视觉模型>'",
    sig.count("|") == 1 and sig.startswith(NEW_MODEL + "|"), f"实际={sig!r}")

# ============================================================
print()
print("=" * 70)
print("D. 请求体断言：推理模型必须真的带上 enable_thinking=false")
print("    （不依赖网络：拦截 urllib.request.urlopen 读请求体）")
print("=" * 70)
_captured = {}


class _FakeResp:
    def __init__(self, obj):
        self._b = json.dumps(obj).encode("utf-8")

    def read(self):
        return self._b


def _fake_urlopen(req, timeout=None):
    _captured["body"] = json.loads(req.data.decode("utf-8"))
    return _FakeResp({"choices": [{"message": {"content": "OK"}}]})


_orig_urlopen = urllib.request.urlopen
urllib.request.urlopen = _fake_urlopen
try:
    # D1 当前主模型（白名单内）→ 必须关思维链
    _captured.clear()
    client._call_api("hi")
    b = _captured.get("body", {})
    chk("主模型请求体 model 正确", b.get("model") == NEW_MODEL, f"实际={b.get('model')!r}")
    chk("主模型请求体 enable_thinking is False",
        b.get("enable_thinking") is False, f"实际={b.get('enable_thinking')!r}")

    # D2 非白名单模型 → 绝不能塞该参数（白名单不泄漏）
    _captured.clear()
    client._call_api("hi", model="qwen3.8-27b")
    b = _captured.get("body", {})
    chk("非白名单模型（视觉 qwen3.8-27b）不带 enable_thinking",
        "enable_thinking" not in b, f"实际={b.get('enable_thinking')!r}")

    # D3 旧推理模型仍是白名单成员 → 也要关（避免切回时静默空输出）
    _captured.clear()
    client._call_api("hi", model=OLD_MODEL)
    b = _captured.get("body", {})
    chk("旧推理模型仍被关思维链", b.get("enable_thinking") is False)

    # D4 备用链模型（deepseek-v4-flash，非推理）不受影响
    _captured.clear()
    fb = client.fallback_models()[0]
    client._call_api("hi", model=fb)
    b = _captured.get("body", {})
    chk(f"备用模型 {fb} 不带 enable_thinking", "enable_thinking" not in b)
finally:
    urllib.request.urlopen = _orig_urlopen

# ============================================================
print()
print("=" * 70)
print("E. 脚本审查缓存：模型签名参与失效判定")
print("=" * 70)
H = "hash_abc"
SIG = f"{NEW_MODEL}|qwen3.8-27b"
chk("done + 同脚本 + 同模型 → 可复用",
    W._script_cache_reusable(
        {"status": "done", "script_hash": H, "llm_signature": SIG}, H, SIG) is True)
chk("done + 同脚本 + **模型变了** → 不可复用（本条修复的核心）",
    W._script_cache_reusable(
        {"status": "done", "script_hash": H, "llm_signature": f"{OLD_MODEL}|qwen3.8-27b"},
        H, SIG) is False)
chk("done + 同脚本 + **旧缓存无签名** → 不可复用",
    W._script_cache_reusable({"status": "done", "script_hash": H}, H, SIG) is False)
chk("done + **脚本变了** → 不可复用",
    W._script_cache_reusable(
        {"status": "done", "script_hash": "other", "llm_signature": SIG}, H, SIG) is False)
chk("status 非 done → 不可复用",
    W._script_cache_reusable(
        {"status": "running", "script_hash": H, "llm_signature": SIG}, H, SIG) is False)
chk("空字典 → 不可复用", W._script_cache_reusable({}, H, SIG) is False)
chk("非 dict → 不可复用（防御坏索引）",
    W._script_cache_reusable(None, H, SIG) is False)

# ============================================================
print()
print("=" * 70)
print(f"结果：PASS {PASS} / FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
