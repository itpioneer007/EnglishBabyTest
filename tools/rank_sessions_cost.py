"""全量会话花费排行

扫描 ~/.workbuddy/projects/*/*.jsonl，逐会话统计真实 usage 并折算金额，按花费排序。
用于定位"钱到底被哪一次对话烧掉了"。

用法：
  python tools/rank_sessions_cost.py [--peak] [--top N] [--since YYYY-MM-DD]
"""
import io
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = Path(os.path.expanduser("~")) / ".workbuddy" / "projects"
RATES = {"peak": (0.04, 2.0, 8.0), "offpeak": (0.02, 1.0, 4.0)}

MODEL_RE = re.compile(r'"model"\s*:\s*"([^"]{2,60})"')


def parse_session(path: Path):
    rows, models = [], {}
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if '"usage"' in ln:
            try:
                o = json.loads(ln)
            except Exception:
                o = None
            if isinstance(o, dict):
                u = ((o.get("providerData") or {}).get("usage")
                     or (o.get("message") or {}).get("usage") or {})
                inp = int(u.get("inputTokens") or u.get("input_tokens") or 0)
                out = int(u.get("outputTokens") or u.get("output_tokens") or 0)
                cached = int(u.get("cache_read_input_tokens") or 0)
                if not cached:
                    det = u.get("inputTokensDetails") or u.get("input_tokens_details") or []
                    if det:
                        cached = int((det[0] or {}).get("cached_tokens") or 0)
                if inp or out:
                    rows.append((inp, min(cached, inp), out))
        for m in MODEL_RE.findall(ln):
            if "deepseek" in m.lower() or "claude" in m.lower() or "glm" in m.lower() \
               or "kimi" in m.lower() or "gpt" in m.lower() or "hy" == m[:2]:
                models[m] = models.get(m, 0) + 1
    return rows, models


def cost_of(rows, mode="offpeak"):
    hit, miss, out = RATES[mode]
    t_in = sum(r[0] for r in rows)
    t_ca = sum(r[1] for r in rows)
    t_out = sum(r[2] for r in rows)
    return (t_ca * hit + (t_in - t_ca) * miss + t_out * out) / 1_000_000, t_in, t_ca, t_out


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    mode = "peak" if "--peak" in sys.argv else "offpeak"
    top = 25
    if "--top" in sys.argv:
        top = int(sys.argv[sys.argv.index("--top") + 1])
    since = None
    if "--since" in sys.argv:
        since = datetime.strptime(sys.argv[sys.argv.index("--since") + 1], "%Y-%m-%d")

    results = []
    for f in sorted(PROJECTS.glob("*/*.jsonl")):
        try:
            mt = datetime.fromtimestamp(f.stat().st_mtime)
        except Exception:
            continue
        if since and mt < since:
            continue
        rows, models = parse_session(f)
        if not rows:
            continue
        c, t_in, t_ca, t_out = cost_of(rows, mode)
        top_model = max(models, key=models.get) if models else "?"
        results.append({
            "ws": f.parent.name.replace("c-Users-19507-WorkBuddy-", ""),
            "file": f.name[:8],
            "mtime": mt, "reqs": len(rows), "cost": c,
            "in": t_in, "ca": t_ca, "out": t_out, "model": top_model,
        })

    results.sort(key=lambda r: r["cost"], reverse=True)
    total = sum(r["cost"] for r in results)
    print("=" * 110)
    print(f"会话花费排行（{'高峰' if mode == 'peak' else '空闲'}时段单价）"
          f"{'  自 ' + since.strftime('%Y-%m-%d') if since else ''}")
    print("=" * 110)
    print(f"{'工作区':<30} | {'结束时间':<16} | {'请求':>5} | {'输入':>13} | {'命中':>13} | {'输出':>10} | {'费用¥':>8} | 模型")
    for r in results[:top]:
        print(f"{r['ws'][:29]:<30} | {r['mtime']:%Y-%m-%d %H:%M} | {r['reqs']:>5} | "
              f"{r['in']:>13,} | {r['ca']:>13,} | {r['out']:>10,} | {r['cost']:>8.3f} | {r['model'][:20]}")
    print("-" * 120)
    print(f"共 {len(results)} 个会话，合计 ≈ ¥{total:.2f}")
    # 只看 deepseek 通道
    ds = [r for r in results if "deepseek" in r["model"].lower()]
    print(f"其中走 deepseek-* 模型的 {len(ds)} 个会话，合计 ≈ ¥{sum(r['cost'] for r in ds):.2f}")
    print("=" * 120)


if __name__ == "__main__":
    main()
