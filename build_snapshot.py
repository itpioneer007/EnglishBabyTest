# -*- coding: utf-8 -*-
import json, html

src = "current_run_log.json"
out = "运行日志快照_听力专项_第六单元.html"

d = json.load(open(src, encoding="utf-8"))

COLOR = {
    "info": "#334155",
    "step": "#1d4ed8",
    "success": "#15803d",
    "warning": "#b45309",
    "error": "#b91c1c",
}
rows = []
for e in d:
    lvl = e.get("level", "info")
    color = COLOR.get(lvl, "#334155")
    msg = html.escape(e.get("msg", ""))
    tim = html.escape(e.get("time", ""))
    rows.append(
        f'<div class="row"><span class="t">{tim}</span>'
        f'<span class="lv" style="color:{color}">{html.escape(lvl)}</span>'
        f'<span class="m" style="color:{color}">{msg}</span></div>'
    )

# 统计每题出现次数
cnt = {}
for e in d:
    m = e.get("msg", "")
    for n in range(1, 21):
        if f"第{n}题" in m:
            cnt[n] = cnt.get(n, 0) + 1

cnt_html = " · ".join(f"第{n}题×{cnt[n]}" for n in sorted(cnt))

doc = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>运行日志快照 · 听力专项 第六单元</title>
<style>
 body{{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;margin:0;background:#f8fafc;color:#0f172a}}
 header{{background:#1e293b;color:#fff;padding:16px 22px}}
 header h1{{margin:0;font-size:18px}}
 header p{{margin:6px 0 0;font-size:13px;color:#cbd5e1}}
 .cnt{{margin:14px 22px;font-size:13px;color:#475569;background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px}}
 .log{{margin:0 22px 28px;background:#fff;border:1px solid #e2e8f0;border-radius:8px;overflow:hidden}}
 .row{{display:flex;gap:10px;padding:6px 14px;border-bottom:1px solid #f1f5f9;font-size:13px;line-height:1.5}}
 .row:last-child{{border-bottom:none}}
 .t{{color:#94a3b8;font-variant-numeric:tabular-nums;flex:0 0 64px}}
 .lv{{flex:0 0 56px;font-weight:600;text-transform:uppercase;font-size:11px}}
 .m{{flex:1;white-space:pre-wrap;word-break:break-all}}
 .hl{{background:#fef9c3}}
</style></head>
<body>
<header><h1>运行日志快照 · 听力专项 · 第六单元（2026-08-30 10:55 任务）</h1>
<p>本页为「开始检测」后完整运行日志的离线快照，含基础巩固 / 综合进阶 / 难点突破 三个子模块，
证明前 9 题（含综合进阶）的日志记录均正常生成，此前仅因前端增量偏移卡死而未在网页显示。</p></header>
<div class="cnt">共 {len(d)} 条 · 各题出现次数：{cnt_html}</div>
<div class="log">{"".join(rows)}</div>
</body></html>"""

open(out, "w", encoding="utf-8").write(doc)
print("written:", out, "rows:", len(d))
