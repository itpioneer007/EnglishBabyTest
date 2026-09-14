"""余额探针：按固定间隔采样 DeepSeek 账户余额，记录每一次变化及其时间点。

用途：把"钱是什么时候被扣的"对齐到时间轴，从而定位是哪一步在花钱。
README(用法)：
    python tools/cost_probe.py watch [间隔秒] [持续秒]     # 持续采样
    python tools/cost_probe.py once                        # 采样一次
输出：logs/cost_watch.csv （ts, balance, delta, note）
"""
import csv
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
OUT_DIR = ROOT / "logs"
OUT_CSV = OUT_DIR / "cost_watch.csv"


def _api_key() -> str:
    k = os.environ.get("LLM_API_KEY")
    if k:
        return k
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("LLM_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("未找到 LLM_API_KEY（.env 或环境变量）")


def _balance(key: str) -> dict:
    req = urllib.request.Request(
        "https://api.deepseek.com/user/balance",
        headers={"Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def _balance_of(data: dict) -> float:
    for b in data.get("balance_infos") or []:
        if b.get("currency") == "CNY":
            return float(b.get("total_balance", 0))
    return 0.0


def _append(ts: str, bal: float, delta: float, note: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    new = not OUT_CSV.exists()
    with OUT_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts", "balance_cny", "delta", "note"])
        w.writerow([ts, f"{bal:.4f}", f"{delta:+.4f}", note])


def once(note: str = "") -> float:
    key = _api_key()
    data = _balance(key)
    bal = _balance_of(data)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _append(ts, bal, 0.0, note)
    print(f"[{ts}] 余额 {bal:.4f} 元  available={data.get('is_available')}")
    return bal


def watch(interval: int = 10, duration: int = 300, note: str = "") -> None:
    key = _api_key()
    print(f"开始采样：每 {interval}s 一次，持续 {duration}s  → {OUT_CSV}")
    print("（Ctrl+C 可提前结束；本探针只查余额，不产生任何模型费用）")
    t0 = time.time()
    prev = None
    while time.time() - t0 < duration:
        try:
            data = _balance(key)
            bal = _balance_of(data)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            delta = 0.0 if prev is None else bal - prev
            _append(ts, bal, delta, note if prev is None else "")
            flag = "" if abs(delta) < 1e-9 else f"   ★★ 变化 {delta:+.4f}"
            print(f"[{ts}] {bal:.4f}{flag}")
            prev = bal
        except Exception as e:  # 网络抖动不致命
            print(f"[{datetime.now():%H:%M:%S}] 采样失败: {type(e).__name__} {e}")
        time.sleep(interval)
    print(f"采样结束。明细见 {OUT_CSV}")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "once"
    if cmd == "watch":
        iv = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        du = int(sys.argv[3]) if len(sys.argv) > 3 else 300
        nt = sys.argv[4] if len(sys.argv) > 4 else ""
        watch(iv, du, nt)
    else:
        once(sys.argv[2] if len(sys.argv) > 2 else "")
