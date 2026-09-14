"""会话 transcript 花费分析器

会话记录（~/.workbuddy/projects/<workspace>/<conversationId>.jsonl）里，
每条助手消息都带真实 `usage` 字段（inputTokens / outputTokens / cached_tokens）。
本工具把它逐条读出来，按 DeepSeek 官方人民币单价折算成金额，
从而**精确回答"哪一次对话花了多少钱"**。

用法：
  python tools/analyze_session_cost.py <transcript.jsonl> [--peak|--offpeak]
  不指定时段时，两种都算一遍。
"""
import io
import json
import re
import sys
from pathlib import Path

# deepseek-flash（DeepSeek-V4.1-Flash）官方单价，元/百万 tokens
RATES = {  # (命中, 未命中, 输出)
    "peak":    (0.04, 2.0, 8.0),
    "offpeak": (0.02, 1.0, 4.0),
}

USAGE_RE = re.compile(r'"usage"\s*:\s*\{(.*?)\}', re.S)


def _num(blob: str, *names, default=0):
    for n in names:
        m = re.search(rf'"{n}"\s*:\s*(\d+)', blob)
        if m:
            return int(m.group(1))
    return default


def parse(path: Path):
    """逐行解析会话记录，返回 [(input, cached, output), ...]。

    ★ 关键：同一次请求的 usage **在一条记录里存了两份**——
        `.providerData.usage`（camelCase: inputTokens/outputTokens）
        `.message.usage`（snake_case: input_tokens/output_tokens）
      二者 token 数完全相同。若用正则 `"usage":{...}` 全局抓取会**翻倍计数**
      （实测 71 次请求被数成 142 次、费用虚高一倍）。故必须按 JSON 结构只取一份。
    """
    rows = []
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln or '"usage"' not in ln:
            continue
        try:
            o = json.loads(ln)
        except Exception:
            continue
        u = ((o.get("providerData") or {}).get("usage")
             or (o.get("message") or {}).get("usage")
             or {})
        inp = int(u.get("inputTokens") or u.get("input_tokens") or 0)
        out = int(u.get("outputTokens") or u.get("output_tokens") or 0)
        cached = int(u.get("cache_read_input_tokens") or 0)
        if not cached:
            det = u.get("inputTokensDetails") or u.get("input_tokens_details") or []
            if det:
                cached = int((det[0] or {}).get("cached_tokens") or 0)
        if inp or out:
            rows.append((inp, min(cached, inp), out))
    return rows


def cost(rows, mode: str):
    hit, miss, out = RATES[mode]
    t_in = sum(r[0] for r in rows)
    t_cached = sum(r[1] for r in rows)
    t_out = sum(r[2] for r in rows)
    t_fresh = t_in - t_cached
    c = (t_cached * hit + t_fresh * miss + t_out * out) / 1_000_000
    return c, t_in, t_cached, t_fresh, t_out


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    p = Path(sys.argv[1])
    rows = parse(p)
    print("=" * 78)
    print(f"会话: {p.name}")
    print(f"捕获到 {len(rows)} 次模型请求的真实 usage")
    print("=" * 78)
    if not rows:
        print("未解析到 usage。")
        return

    print(f"{'时段':<8}{'输入合计':>12}{'其中缓存命中':>14}{'未命中':>12}{'输出':>10}{'费用':>12}")
    for mode, label in (("offpeak", "空闲"), ("peak", "高峰")):
        c, t_in, t_cached, t_fresh, t_out = cost(rows, mode)
        print(f"{label:<8}{t_in:>12,}{t_cached:>14,}{t_fresh:>12,}{t_out:>10,}   ¥{c:>8.3f}")

    c_off, t_in, t_cached, t_fresh, t_out = cost(rows, "offpeak")
    c_pk, *_ = cost(rows, "peak")
    print("-" * 78)
    print(f"缓存命中率 {t_cached / t_in * 100:.1f}%   输出/输入比 {t_out / t_in * 100:.2f}%")

    # 单次明细 Top10
    print("\n最贵的 10 次请求（按空闲时段单价）：")
    hit, miss, out = RATES["offpeak"]
    scored = []
    for i, (inp, ca, o) in enumerate(rows, 1):
        c = (ca * hit + (inp - ca) * miss + o * out) / 1_000_000
        scored.append((c, i, inp, ca, o))
    scored.sort(reverse=True)
    print(f"  {'#':>5}{'输入':>10}{'命中':>10}{'输出':>8}{'费用':>11}")
    for c, i, inp, ca, o in scored[:10]:
        print(f"  {i:>5}{inp:>10,}{ca:>10,}{o:>8,}   ¥{c:.4f}")

    print("\n" + "=" * 78)
    print(f"结论：这次会话在【空闲时段】花费 ≈ ¥{c_off:.2f}，在【高峰时段】≈ ¥{c_pk:.2f}")
    print("=" * 78)


if __name__ == "__main__":
    main()
