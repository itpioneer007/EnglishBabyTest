#!/usr/bin/env python
"""
英语宝 自动化任务控制台
========================
从浏览器一键启动自动化任务，实时查看运行日志。

启动: python dashboard_server.py
访问: http://localhost:8866
"""

import sys
import os
import json
import time
import subprocess
import threading
from pathlib import Path

# 把 src 加入路径
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from flask import Flask, Response, request, jsonify, stream_with_context
import config_loader as cl

app = Flask(__name__, static_folder="outputs", static_url_path="/outputs")

# 任务状态存储
task_logs = {}     # task_id → list of log lines
task_status = {}   # task_id → "running" | "done" | "error"
task_counter = 0


def _background_task(task_id: str, script: str, args: str = ""):
    """后台运行自动化脚本，收集日志"""
    log = []
    task_status[task_id] = "running"
    task_logs[task_id] = log

    try:
        python = "C:/Users/19507/.workbuddy/binaries/python/versions/3.13.12/python.exe"
        script_path = os.path.join(PROJECT_ROOT, "scripts", script)
        cmd = [python, "-u", script_path]
        if args:
            cmd.append(args)

        proc = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        for line in iter(proc.stdout.readline, ""):
            line = line.rstrip()
            log.append(line)
            # 保持最多 200 行
            if len(log) > 200:
                log[:] = log[-200:]

        proc.wait()
        task_status[task_id] = "done" if proc.returncode == 0 else "error"
        log.append(f"\n>>> 进程结束，退出码: {proc.returncode}")

    except Exception as e:
        log.append(f"\n>>> 异常: {e}")
        task_status[task_id] = "error"


# ===== 页面 =====

@app.route("/")
def index():
    """控制台主页"""
    return RESPONSE_HTML

@app.route("/api/status")
def api_status():
    """获取所有任务状态"""
    result = {}
    for tid, status in task_status.items():
        result[tid] = {
            "status": status,
            "count": len(task_logs.get(tid, [])),
        }
    return jsonify(result)

@app.route("/api/log/<task_id>")
def api_log(task_id: str):
    """获取任务日志（SSE 流式推送）"""
    def generate():
        last_len = 0
        while task_status.get(task_id) == "running":
            lines = task_logs.get(task_id, [])
            if len(lines) > last_len:
                for line in lines[last_len:]:
                    yield f"data: {line}\n\n"
                last_len = len(lines)
            time.sleep(0.3)
        # 发送最后遗漏的行
        lines = task_logs.get(task_id, [])
        for line in lines[last_len:]:
            yield f"data: {line}\n\n"
        yield f"data: [[DONE]] {task_status.get(task_id, 'unknown')}\n\n"
    return Response(stream_with_context(generate()), mimetype="text/event-stream")

@app.route("/api/run", methods=["POST"])
def api_run():
    """启动一个任务"""
    global task_counter
    data = request.get_json() or {}
    script = data.get("script", "")
    args = data.get("args", "")
    label = data.get("label", script)

    task_counter += 1
    tid = f"task_{task_counter}"
    task_status[tid] = "starting"
    task_logs[tid] = [f"=== 启动任务: {label} ==="]

    t = threading.Thread(target=_background_task, args=(tid, script, args), daemon=True)
    t.start()
    return jsonify({"task_id": tid, "label": label, "status": "started"})

@app.route("/api/screenshots")
def api_screenshots():
    """列出截图目录中的截图"""
    shot_dir = os.path.join(PROJECT_ROOT, "screenshots")
    files = []
    if os.path.isdir(shot_dir):
        for f in sorted(os.listdir(shot_dir), reverse=True):
            if f.endswith(".png"):
                files.append({
                    "name": f,
                    "url": f"/outputs/../screenshots/{f}",
                    "size": os.path.getsize(os.path.join(shot_dir, f)),
                })
    return jsonify(files[:30])

@app.route("/screenshots/<path:filename>")
def serve_screenshot(filename):
    """提供截图静态文件"""
    from flask import send_from_directory
    return send_from_directory(os.path.join(PROJECT_ROOT, "screenshots"), filename)


# ===== HTML 页面 =====

RESPONSE_HTML = r"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>英语宝 · 自动化控制台</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Microsoft YaHei',sans-serif;background:#f0f2f5;color:#1a1a2e}
.header{background:linear-gradient(135deg,#1a73e8,#0d47a1);color:#fff;padding:24px 32px;display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:1.4rem}.header .badge{font-size:.8rem;opacity:.8}
.container{max-width:1100px;margin:0 auto;padding:20px 16px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:800px){.grid2{grid-template-columns:1fr}}

.card{background:#fff;border-radius:10px;padding:20px;margin-bottom:16px;box-shadow:0 1px 4px rgba(0,0,0,0.06)}
.card h2{font-size:1.1rem;margin-bottom:12px;color:#1a73e8}

.task-btns{display:flex;flex-wrap:wrap;gap:10px}
.task-btn{flex:1;min-width:160px;padding:14px 16px;border:none;border-radius:8px;font-size:.9rem;font-weight:600;cursor:pointer;color:#fff;transition:all .2s}
.task-btn.blue{background:#1a73e8}.task-btn.blue:hover{background:#1557b0}
.task-btn.green{background:#1e8e3e}.task-btn.green:hover{background:#166b2f}
.task-btn.orange{background:#e37400}.task-btn.orange:hover{background:#c25a00}
.task-btn.purple{background:#9334e6}.task-btn.purple:hover{background:#7726c0}
.task-btn:disabled{opacity:.4;cursor:not-allowed}
.task-btn .sub{font-size:.75rem;opacity:.85;font-weight:400;display:block;margin-top:2px}

.log-box{background:#1a1a2e;color:#c0caf5;border-radius:8px;padding:12px;height:460px;overflow-y:auto;font-family:'SF Mono','Fira Code',monospace;font-size:.8rem;line-height:1.5;white-space:pre-wrap}
.log-box .ok{color:#9ece6a}.log-box .err{color:#f7768e}.log-box .warn{color:#e0af68}.log-box .info{color:#7aa2f7}

.status-bar{display:flex;gap:16px;margin-top:8px;align-items:center}
.status-dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px}
.status-dot.running{background:#f9ab00;animation:pulse 1s infinite}
.status-dot.done{background:#1e8e3e}.status-dot.error{background:#e53e3e}
@keyframes pulse{50%{opacity:.4}}

.screenshots{display:flex;gap:10px;overflow-x:auto;padding:8px 0}
.screenshots img{height:120px;border-radius:6px;border:2px solid #e0e0e0;cursor:pointer}
.screenshots img:hover{border-color:#1a73e8}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>🤖 英语宝 · 自动化控制台</h1>
    <div class="badge">湘少版(2024审定) · 五年级上册 · ADB USB 连接</div>
  </div>
  <div style="text-align:right;font-size:.85rem">
    <div id="taskStatus">就绪</div>
    <div style="opacity:.7;font-size:.75rem" id="deviceId">设备: SKSCIF4T7PFMQS5X</div>
  </div>
</div>

<div class="container">

<div class="grid2">

<!-- 左侧：任务面板 -->
<div>

<!-- 快速任务 -->
<div class="card">
  <h2>🚀 快速任务</h2>
  <div class="task-btns">
    <button class="task-btn blue" onclick="runTask('run_inspect.py','切换至新湘少五年级上册的第六单元听力专项模块','单模块-U6听力专项')">
      单模块检测<span class="sub">U6 听力专项</span></button>
    <button class="task-btn green" onclick="runTask('batch_multi_module.py','','多模块批量(3模块×3单元)')">
      多模块批量<span class="sub">听力+口语+知识过关</span></button>
    <button class="task-btn orange" onclick="runTask('version_switch_step_by_step.py','人教版(PEP)(2024审定)','切人教版')">
      快速切版本<span class="sub">人教版六年级上册</span></button>
  </div>
</div>

<!-- 自定义任务 -->
<div class="card">
  <h2>✏️ 自定义指令</h2>
  <input id="customCmd" placeholder="输入自然语言指令，如：新湘少五年级上册U6-U8听力专项"
    style="width:100%;padding:10px;border:2px solid #e0e0e0;border-radius:8px;font-size:.9rem;margin-bottom:8px">
  <button class="task-btn purple" style="width:100%" onclick="customTask()">解析并执行</button>
  <div id="parseResult" style="margin-top:8px;font-size:.82rem;color:#666"></div>
</div>

<!-- 截图预览 -->
<div class="card">
  <h2>📸 最新截图 <button onclick="loadScreenshots()" style="font-size:.75rem;float:right;border:none;background:#e8f0fe;padding:4px 10px;border-radius:4px;cursor:pointer">刷新</button></h2>
  <div class="screenshots" id="screenshotList">暂无截图</div>
</div>

</div>

<!-- 右侧：运行日志 -->
<div class="card" style="display:flex;flex-direction:column">
  <h2>📋 运行日志 <span id="logStatus"></span></h2>
  <div class="log-box" id="logBox">点击左侧任务按钮开始…
等待指令中…</div>
  <div class="status-bar">
    <span id="dotArea"></span>
    <span style="font-size:.8rem;color:#666" id="logCount"></span>
    <button onclick="document.getElementById('logBox').textContent=''" style="margin-left:auto;font-size:.75rem;border:1px solid #ddd;background:#fff;padding:4px 12px;border-radius:4px;cursor:pointer">清空</button>
  </div>
</div>

</div>

</div>

<script>
let currentTask = null;
let eventSource = null;

function runTask(script, args, label) {
  if (eventSource) { eventSource.close(); eventSource = null; }
  document.getElementById('logBox').textContent = '启动中…\n';
  document.getElementById('taskStatus').textContent = '运行中…';
  
  fetch('/api/run', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({script, args, label})
  }).then(r => r.json()).then(data => {
    currentTask = data.task_id;
    streamLog(data.task_id);
  }).catch(e => {
    document.getElementById('logBox').textContent = '启动失败: ' + e;
  });
}

function streamLog(taskId) {
  if (eventSource) eventSource.close();
  eventSource = new EventSource('/api/log/' + taskId);
  const box = document.getElementById('logBox');
  const status = document.getElementById('dotArea');
  status.innerHTML = '<span class="status-dot running"></span>运行中';
  
  eventSource.onmessage = function(e) {
    if (e.data.startsWith('[[DONE]]')) {
      const st = e.data.split(' ')[1];
      status.innerHTML = st === 'done'
        ? '<span class="status-dot done"></span>完成'
        : '<span class="status-dot error"></span>出错';
      document.getElementById('taskStatus').textContent = st === 'done' ? '就绪' : '出错';
      eventSource.close();
      setTimeout(loadScreenshots, 1000);
      return;
    }
    let cls = '';
    if (e.data.includes('✅')) cls = 'ok';
    else if (e.data.includes('❌')) cls = 'err';
    else if (e.data.includes('⚠')) cls = 'warn';
    else if (e.data.includes('===') || e.data.includes('---')) cls = 'info';
    
    // 追加到日志框
    if (box.textContent === '启动中…\n') box.textContent = '';
    box.innerHTML += '<span class="' + cls + '">' + escapeHtml(e.data) + '</span>\n';
    box.scrollTop = box.scrollHeight;
    document.getElementById('logCount').textContent = box.children.length + ' 行';
  };
  
  eventSource.onerror = function() {
    status.innerHTML = '<span class="status-dot error"></span>断连';
  };
}

function customTask() {
  const cmd = document.getElementById('customCmd').value.trim();
  if (!cmd) return;
  fetch('/api/run', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({script:'run_inspect.py', args: cmd, label: cmd})
  }).then(r => r.json()).then(data => {
    document.getElementById('parseResult').textContent = '已提交任务: ' + cmd;
    streamLog(data.task_id);
  });
}

function loadScreenshots() {
  fetch('/api/screenshots').then(r => r.json()).then(files => {
    const div = document.getElementById('screenshotList');
    if (!files.length) { div.innerHTML = '暂无截图'; return; }
    div.innerHTML = files.slice(0,8).map(f => 
      '<img src="/screenshots/' + f.name + '" title="' + f.name + '" onclick="window.open(\'/screenshots/' + f.name + '\')">'
    ).join('');
  });
}

function escapeHtml(t) {
  return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// 初始加载
loadScreenshots();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("=" * 50)
    print("🤖 英语宝 · 自动化控制台")
    print("=" * 50)
    print(f"启动地址: http://localhost:8866")
    print(f"设备序列号: SKSCIF4T7PFMQS5X (USB)")
    print(f"项目目录: {PROJECT_ROOT}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=8866, debug=False, threaded=True)
