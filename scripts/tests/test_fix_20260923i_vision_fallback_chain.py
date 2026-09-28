"""★ 2026-09-23 回归测试：视觉模型备用链改为三级，并把 qwen3.7-flash 放到第一位。

背景（用户需求）：
    "qwen3.7-flash 这个是识图模型的备用方案，假如识图模型的额度用完了，就换这个使用。"

为什么不能只是"把名字填进配置"：

  1) **跨系列才有意义**。原备用链是 qwen3.8-max → qwen3.8-flash，与主模型 qwen3.8-27b
     **同系列**。百炼免费额度按模型独立计，但同系列一起到期的概率高 —— 最典型的失败场景
     "qwen3.8 系列额度耗尽"下，原备用链会跟着一起失效，等于没有备用。
     qwen3.7-flash 是另一系列 → 独立额度，故放在 fallback1（最先尝试）。

  2) **它也是重度推理模型**。实测同一张 U7 截图：
        不关思维链：reasoning_tokens 2209~4614，18~37s/图（同批 qwen3.8-max 甚至 105s）
        关思维链  ：1.1s/图
     且 3 张真实截图的「喇叭图标 有/无」判定与关前**完全一致**（读屏文字/看图标是感知题，
     不需要思维链）→ 必须进 no-think 白名单，否则备用档比主模型还慢一个数量级。
     ⚠ 该白名单对**视觉调用同样生效**（_call_api 按模型名判定，不分文本/视觉）。

  3) **备用链要从两级扩到三级**，才能"新增而不丢弃"原有两级。

本测试锁定：
  A 三处配置同步（.env / llm_config.json / 代码兜底），且跨系列约束成立
  B LLMClient 参数连通性 + 老调用向后兼容（只给两级时不报错）
  C 请求体断言：qwen3.7-flash 必须带 enable_thinking=false；同系列 qwen3.8-* 不带
  D 回退链真实走位：主→fb1→fb2→fb3 顺序正确、非额度错误不切换、全失败降级纯文本

运行：python scripts/tests/test_fix_20260923i_vision_fallback_chain.py
"""
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from src import reviewer_common as RC  # noqa: E402

PASS = 0
FAIL = []

FB1 = "qwen3.7-flash"
FB2 = "qwen3.8-max"
FB3 = "qwen3.8-flash"
PRIMARY = "qwen3.8-27b"

# 任意一张真实截图（本测试不真的发图，仅作路径占位）
_IMG = os.path.join(ROOT, "outputs", "reports", "教科版(2024审定)",
                    "U7_全部_20260923", "screenshots", "auto_口语训练_b01q001_180105.png")
if not os.path.exists(_IMG):
    _IMG = os.path.join(ROOT, ".env")  # 兜底：任意存在文件即可


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
    with open(os.path.join(ROOT, ".env"), "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ============================================================
print("=" * 70)
print("A. 三处配置同步 + 跨系列约束")
print("=" * 70)
env = read_env_file()
chk(".env VISION_MODEL_FALLBACK == qwen3.7-flash",
    env.get("VISION_MODEL_FALLBACK") == FB1, f"实际={env.get('VISION_MODEL_FALLBACK')!r}")
chk(".env VISION_MODEL_FALLBACK2 == qwen3.8-max（原一级保留）",
    env.get("VISION_MODEL_FALLBACK2") == FB2, f"实际={env.get('VISION_MODEL_FALLBACK2')!r}")
chk(".env VISION_MODEL_FALLBACK3 == qwen3.8-flash（原二级保留）",
    env.get("VISION_MODEL_FALLBACK3") == FB3, f"实际={env.get('VISION_MODEL_FALLBACK3')!r}")
_nothink_env = [x.strip() for x in env.get("LLM_NO_THINK_MODELS", "").split(",")]
chk(".env LLM_NO_THINK_MODELS 含 qwen3.7-flash",
    FB1 in _nothink_env, f"实际={env.get('LLM_NO_THINK_MODELS')!r}")
chk(".env 主视觉模型未被误改", env.get("VISION_MODEL") == PRIMARY,
    f"实际={env.get('VISION_MODEL')!r}")
chk(".env 主视觉仍不是 OCR 模型（备用链只放真看图模型）",
    "ocr" not in env.get("VISION_MODEL", "").lower())

cfg = json.loads(open(os.path.join(ROOT, "llm_config.json"), encoding="utf-8").read())
chk("llm_config.json vision_model_fallback == qwen3.7-flash",
    cfg.get("vision_model_fallback") == FB1, f"实际={cfg.get('vision_model_fallback')!r}")
chk("llm_config.json vision_model_fallback2 == qwen3.8-max",
    cfg.get("vision_model_fallback2") == FB2)
chk("llm_config.json vision_model_fallback3 == qwen3.8-flash",
    cfg.get("vision_model_fallback3") == FB3)
chk("llm_config.json no_think_models 含 qwen3.7-flash",
    FB1 in [x.strip() for x in str(cfg.get("no_think_models", "")).split(",")],
    f"实际={cfg.get('no_think_models')!r}")
chk("代码侧 _NO_THINK_FALLBACK 含 qwen3.7-flash（.env 丢失时兜底）",
    FB1 in RC._NO_THINK_FALLBACK, f"实际={RC._NO_THINK_FALLBACK}")

# 跨系列：fallback1 与主模型必须不同系列（否则"同系列一起失效"等于没有备用）
_prim_fam = PRIMARY.split("-")[0]
_fb1_fam = FB1.split("-")[0]
chk(f"fallback1({FB1}) 与主模型({PRIMARY}) 不同系列（独立额度）",
    _prim_fam != _fb1_fam, f"家族 {_prim_fam!r} vs {_fb1_fam!r}")

# ============================================================
print()
print("=" * 70)
print("B. LLMClient 参数连通性 + 向后兼容")
print("=" * 70)
client = RC.LLMClient.from_config()
chk("from_config 主视觉", client.vision_model == PRIMARY, f"实际={client.vision_model!r}")
chk("from_config fallback1", client.vision_model_fallback == FB1)
chk("from_config fallback2", client.vision_model_fallback2 == FB2)
chk("from_config fallback3", client.vision_model_fallback3 == FB3,
    f"实际={getattr(client, 'vision_model_fallback3', '<无该属性>')!r}")

_kw = RC.LLMClient(vision_model_fallback3="X-model")
chk("构造参数 vision_model_fallback3 可关键字传入",
    _kw.vision_model_fallback3 == "X-model", f"实际={_kw.vision_model_fallback3!r}")
_old = RC.LLMClient(vision_model_fallback="A", vision_model_fallback2="B")
chk("老调用（只给两级）不报错且 fallback3 为空",
    _old.vision_model_fallback3 == "" and _old.vision_model_fallback == "A")

# ============================================================
print()
print("=" * 70)
print("C. 请求体断言：qwen3.7-flash 必须带 enable_thinking=false")
print("   （不依赖网络：拦截 urllib.request.urlopen 读请求体）")
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
    client._call_api("hi", model=FB1)
    b = _captured.get("body", {})
    chk("qwen3.7-flash 请求体 model 正确", b.get("model") == FB1, f"实际={b.get('model')!r}")
    chk("qwen3.7-flash 请求体 enable_thinking is False（否则 18~37s/图）",
        b.get("enable_thinking") is False, f"实际={b.get('enable_thinking')!r}")

    for _m in (PRIMARY, FB2, FB3):
        _captured.clear()
        client._call_api("hi", model=_m)
        b = _captured.get("body", {})
        chk(f"同系列 {_m} 不带 enable_thinking（白名单不泄漏）",
            "enable_thinking" not in b, f"实际={b.get('enable_thinking')!r}")
finally:
    urllib.request.urlopen = _orig_urlopen

# ============================================================
print()
print("=" * 70)
print("D. 回退链真实走位（mock _call_api 制造额度故障）")
print("=" * 70)
QUOTA_ERR = "HTTP Error 403: AllocationQuota.FreeTierOnly 免费额度耗尽"


def make_client(dead=(), text_dead=False):
    """dead=会抛"额度耗尽"的模型集合；其余模型返回 OK:<model>。"""
    c = RC.LLMClient(model="deepseek-v4.1-flash", vision_model=PRIMARY,
                     vision_api_key="k",
                     vision_model_fallback=FB1,
                     vision_model_fallback2=FB2,
                     vision_model_fallback3=FB3)
    calls = []

    def stub(prompt, image_paths=None, model=None, base_url=None,
             api_key=None, temperature=None):
        use = model or c.model
        calls.append((use, image_paths is not None))
        if use in dead or (text_dead and use == c.model):
            raise RuntimeError(QUOTA_ERR)
        return f"OK:{use}"

    c._call_api = stub
    return c, calls


# D1 主模型额度耗尽 → 应切到 fallback1
c, calls = make_client(dead={PRIMARY})
res = c.ask("p", image_paths=[_IMG])
chk("主模型额度耗尽 → 结果来自 fallback1(qwen3.7-flash)",
    res == f"OK:{FB1}", f"实际={res!r}")
chk("调用顺序 [主模型, fallback1]",
    [x[0] for x in calls] == [PRIMARY, FB1], f"实际={[x[0] for x in calls]}")
chk("两次调用都带图（未降级为纯文本）", all(x[1] for x in calls))

# D2 主 + fallback1 都耗尽 → 切到 fallback2
c, calls = make_client(dead={PRIMARY, FB1})
res = c.ask("p", image_paths=[_IMG])
chk("主+fb1 均额度耗尽 → 结果来自 fallback2(qwen3.8-max)",
    res == f"OK:{FB2}", f"实际={res!r}")
chk("调用顺序 [主, fb1, fb2]",
    [x[0] for x in calls] == [PRIMARY, FB1, FB2], f"实际={[x[0] for x in calls]}")

# D3 三级全耗尽 → 切到 fallback3（证明第三级真的接进了循环）
c, calls = make_client(dead={PRIMARY, FB1, FB2})
res = c.ask("p", image_paths=[_IMG])
chk("主+fb1+fb2 耗尽 → 结果来自新增的 fallback3(qwen3.8-flash)",
    res == f"OK:{FB3}", f"实际={res!r}")
chk("调用顺序 [主, fb1, fb2, fb3] —— 三级链完整",
    [x[0] for x in calls] == [PRIMARY, FB1, FB2, FB3], f"实际={[x[0] for x in calls]}")

# D4 非额度错误（网络/超时）→ 不切换备用，直接降级纯文本
c, calls = make_client()
def _stub_timeout(prompt, image_paths=None, model=None, base_url=None,
                  api_key=None, temperature=None):
    use = model or c.model
    calls.append((use, image_paths is not None))
    if image_paths is not None:
        raise RuntimeError("connect timeout / read timed out")
    return f"OK:{use}"
c._call_api = _stub_timeout
res = c.ask("p", image_paths=[_IMG])
chk("非额度错误 → 不切换备用（不浪费额度）",
    [x[0] for x in calls] == [PRIMARY, "deepseek-v4.1-flash"],
    f"实际={[x[0] for x in calls]}")
chk("非额度错误 → 降级为纯文本且保留原因",
    "降级为纯文本" in str(res), f"实际={str(res)[:120]!r}")

# D5 视觉三级 + 文本全挂 → 返回 [LLM 不可用]，绝不抛异常
c, calls = make_client(dead={PRIMARY, FB1, FB2, FB3}, text_dead=True)
res = c.ask("p", image_paths=[_IMG])
chk("全部不可用 → 返回 [LLM 不可用] 结构化提示（不抛异常）",
    str(res).startswith("[LLM 不可用]"), f"实际={str(res)[:120]!r}")
chk("全部不可用 → 依次尝试了四级模型",
    [x[0] for x in calls] == [PRIMARY, FB1, FB2, FB3, "deepseek-v4.1-flash"],
    f"实际={[x[0] for x in calls]}")

# D6 老配置（fallback3 为空）时不崩，走完 fb2 后正常降级
c_old, calls_old = make_client(dead={PRIMARY, FB1, FB2})
c_old.vision_model_fallback3 = ""
res = c_old.ask("p", image_paths=[_IMG])
chk("fallback3 为空（旧配置）时不崩溃",
    isinstance(res, str) and len(res) > 0, f"实际={str(res)[:100]!r}")

# ============================================================
print()
print("=" * 70)
print(f"结果：PASS {PASS} / FAIL {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print(f"  ✗ {f}")
print("=" * 70)
sys.exit(1 if FAIL else 0)
