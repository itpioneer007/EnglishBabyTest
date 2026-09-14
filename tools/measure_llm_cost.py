"""LLM 花费实测工装（DeepSeek / deepseek-flash）

原理：
  在进程内劫持 `urllib.request.urlopen`，把每一次真实 HTTP 请求的
  响应体读出来解析 `usage` 字段，再按 DeepSeek 官方人民币单价折算成金额。
  —— 比"看余额差额"精确得多（余额只有 0.01 元分辨率），能看到**每一次调用**
  的 input / cache-hit / output 明细，从而定位钱花在哪一类调用上。

官方单价（deepseek-flash = DeepSeek-V4.1-Flash，元/百万 tokens）：
  | 项目            | 空闲时段 | 高峰时段 |
  | 输入·缓存命中   |   0.02   |   0.04   |
  | 输入·缓存未命中 |   1.0    |   2.0    |
  | 输出            |   4.0    |   8.0    |
  高峰 = 北京时间 周一至周五 09:00-12:00、14:00-18:00；其余为空闲。

用法：
  python tools/measure_llm_cost.py [调用次数]
"""
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PEAK_HIT, PEAK_MISS, PEAK_OUT = 0.04, 2.0, 8.0
OFF_HIT, OFF_MISS, OFF_OUT = 0.02, 1.0, 4.0


def is_peak(now: datetime | None = None) -> bool:
    """高峰时段：周一至周五 09:00-12:00、14:00-18:00（北京时间）。"""
    now = now or datetime.now()
    if now.weekday() >= 5:           # 周六/周日
        return False
    hm = now.hour * 60 + now.minute
    return (9 * 60 <= hm < 12 * 60) or (14 * 60 <= hm < 18 * 60)


def price(peak: bool):
    return (PEAK_HIT, PEAK_MISS, PEAK_OUT) if peak else (OFF_HIT, OFF_MISS, OFF_OUT)


# ---------------------------------------------------------------- 拦截层
RECORDS: list[dict] = []
_orig_urlopen = urllib.request.urlopen


class _FakeResp:
    """把真实响应的字节回放出来，让调用方无感知。"""

    def __init__(self, body: bytes, status: int, headers):
        self._body = body
        self.status = status
        self.headers = headers
        self._pos = 0

    def read(self, *a):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def getcode(self):
        return self.status


def _sniff(req, timeout):
    t0 = time.time()
    resp = _orig_urlopen(req, timeout=timeout)
    try:
        body = resp.read()
    finally:
        try:
            resp.close()
        except Exception:
            pass
    elapsed = time.time() - t0

    # 只关心真正的推理请求
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if "chat/completions" in url:
        try:
            payload = json.loads(body.decode("utf-8"))
            u = payload.get("usage") or {}
            model = payload.get("model", "?")
            hit = u.get("prompt_cache_hit_tokens", 0) or 0
            miss = u.get("prompt_cache_miss_tokens")
            if miss is None:
                miss = max((u.get("prompt_tokens", 0) or 0) - hit, 0)
            out = u.get("completion_tokens", 0) or 0
            rdet = (u.get("completion_tokens_details") or {})
            reason = rdet.get("reasoning_tokens", 0) or 0
            RECORDS.append({
                "model": model, "hit": hit, "miss": miss, "out": out,
                "reason": reason, "secs": elapsed,
            })
        except Exception as e:
            print(f"  [warn] usage 解析失败: {e}")
    return _FakeResp(body, getattr(resp, "status", 200), getattr(resp, "headers", {}))


def install_tap():
    def patched(url, *a, **kw):
        timeout = kw.pop("timeout", None) or (a[0] if a else None)
        return _sniff(url, timeout)
    urllib.request.urlopen = patched


# ---------------------------------------------------------------- 题目样本
SAMPLE_FALLBACK = [
    ("What's the weather like today? — It's ____.", ["sun", "sunny", "sunny day", "the sun"], "B", "湘少版", "六上"),
    ("I usually go to school ____ bike.", ["on", "by", "in", "with"], "B", "湘少版", "六上"),
    ("Look! The children ____ football on the playground.", ["play", "plays", "are playing", "played"], "C", "湘少版", "六上"),
    ("My father is a doctor. He ____ in a big hospital.", ["work", "works", "working", "worked"], "B", "湘少版", "六上"),
    ("There ____ some milk in the glass.", ["is", "are", "have", "has"], "A", "湘少版", "六上"),
]


def load_questions(n: int = 5):
    """优先用项目里真实采集过的题目，保证 prompt 规模贴近真实。"""
    p = ROOT / "data" / "inspection_state.json"
    qs = []
    if p.exists():
        try:
            d = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            for q in (d.get("questions") or []):
                stem = (q.get("stem") or q.get("title") or "").strip()
                if not stem:
                    continue
                qs.append((stem, q.get("options") or [], q.get("answer") or "", "湘少版", "六上"))
                if len(qs) >= n:
                    break
        except Exception:
            pass
    while len(qs) < n:
        qs.append(SAMPLE_FALLBACK[len(qs) % len(SAMPLE_FALLBACK)])
    return qs[:n]


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    from scripts.common.gen_script import KNOWLEDGE_PROMPT_TEMPLATE
    from src.reviewer_common import LLMClient

    peak = is_peak()
    ph, pm, po = price(peak)
    print("=" * 74)
    print(f"DeepSeek 花费实测  |  当前 {'高峰' if peak else '空闲'}时段"
          f"  单价: 命中 {ph}/M  未命中 {pm}/M  输出 {po}/M (元)")
    print("=" * 74)

    install_tap()
    llm = LLMClient.from_config()
    print(f"通道: {llm.model} @ {llm.base_url}\n")

    qs = load_questions(n)
    for i, (stem, opts, ans, ver, grade) in enumerate(qs, 1):
        prompt = KNOWLEDGE_PROMPT_TEMPLATE.format(
            g_grade=grade, g_version=ver, g_stem=stem,
            g_options=" ".join(opts) if opts else "（无文字选项）", g_answer=ans)
        before = len(RECORDS)
        t0 = time.time()
        out = llm.ask(prompt) or ""
        dur = time.time() - t0
        rec = RECORDS[before:] or [None]
        r = rec[0]
        if r:
            cost = (r["hit"] * ph + r["miss"] * pm + r["out"] * po) / 1_000_000
            print(f"[{i}] {dur:5.2f}s  in={r['hit'] + r['miss']:>6} "
                  f"(命中{r['hit']:>5}/未命中{r['miss']:>5})  out={r['out']:>5} "
                  f"(思考{r['reason']:>4})  ≈ ¥{cost:.5f}")
        else:
            print(f"[{i}] {dur:5.2f}s  未捕获 usage（可能未发出请求）")
        print(f"     → {out[:90].replace(chr(10), ' ')}")

    # ---------------- 汇总 ----------------
    if not RECORDS:
        print("\n没有任何请求被捕获。")
        return
    th = sum(r["hit"] for r in RECORDS)
    tm = sum(r["miss"] for r in RECORDS)
    to = sum(r["out"] for r in RECORDS)
    tr = sum(r["reason"] for r in RECORDS)
    total = (th * ph + tm * pm + to * po) / 1_000_000
    cnt = len(RECORDS)

    print("\n" + "=" * 74)
    print(f"{cnt} 次调用合计:  输入 {th + tm} tokens（命中 {th} / 未命中 {tm}）"
          f"   输出 {to} tokens（其中思考 {tr}）")
    print(f"花费合计 ≈ ¥{total:.4f}   单次均值 ≈ ¥{total / cnt:.5f}")
    print(f"输出占花费比例 ≈ {to * po / (th * ph + tm * pm + to * po) * 100:.1f}%"
          f"   ← 输出是最贵项（{po} 元/M，是未命中输入的 {po / pm:.0f} 倍）")
    print("=" * 74)

    # 外推到真实规模
    print("\n外推（按单次均值）：")
    for label, k in [("1 个单元 15 题", 15), ("1 个单元 86 题（巧记单词实测）", 86),
                     ("1 个单元 101 题（旧口径）", 101), ("10 个单元 ≈ 860 题", 860)]:
        print(f"  {label:<32} ≈ ¥{total / cnt * k:>7.3f}")


if __name__ == "__main__":
    main()
