# 实时错题报告框架（方案 A）

> 本目录包含对「英语宝模块检测」Web 控制面板新增的 **实时错题报告** 功能代码。
> 在审查任务运行期间，每识别到一道错题，系统会自动增量生成一份格式化的 HTML 报告；
> 在前端「错题日志」面板点击 **📑 查看报告** 即可弹窗查看：题目来源 / 错误原因 / 修改建议 / 截图证据。

---

## 一、功能做了什么

| 能力 | 说明 |
|------|------|
| 自动收集错题 | 复用已有的 `_inspection_state["questions"]` 数据，不重复造轮子 |
| 实时增量报告 | 每判出一道不通过的题，自动重生成 `report_live.html`（带线程锁，支持并发写） |
| 前端弹窗查看 | 「错题日志」面板新增按钮 → 弹窗内 `<iframe>` 嵌入报告，单页点开即看 |
| LLM 自动给建议 | 审查智能体在「不通过」维度末尾追加「建议修改：」，系统自动解析抽取 |
| 可移植报告 | 报告内截图用相对路径拷贝到输出目录，文件可单独打开 / 分享 |

---

## 二、修改清单（共 5 个文件）

### 1. `web_server.py`（修改）
- 注册新路由：`from routes.error_log_routes import ...; _error_log_routes.register(app)`
- `_inspection_state` 扩展字段：`version` / `unit` / `stage` / `live_report_path`，新增线程锁 `_live_report_lock`
- 在 `api_inspect_question_result`（每题结果写回的**唯一写点**）中：该题不通过即触发实时报告重生成
- 在 `api_inspect_reset` 中：清空并重置空报告
- **修复启动 Bug ①**：ADB 路径原写死为同事电脑 `C:\Users\bunana\...`，改为自动查找（`shutil.which("adb")` → WinGet 默认路径 → `ANDROID_HOME`）
- **修复启动 Bug ②**：`io.TextIOWrapper(sys.stdout.buffer, ...)` 会破坏 `fileno()` 导致 Flask 启动崩溃，改为 `sys.stdout.reconfigure(encoding="utf-8")` 原地改编码

### 2. `src/review_agent.py`（修改）
- `CheckResult` 数据类新增 `suggestion: str` 字段，并经 `to_dict()` 输出
- 新增模块常量 `REVIEW_SUGGEST_SUFFIX`：要求审查智能体在「不通过」维度理由末尾用「建议修改：」接一句具体改法
- `_apply_verdict` 用正则 `建议修改[:：]\s*([^\n]{4,200})` 解析，写入 `suggestion` 并回写 `details[-1]`；通过的维度不写建议
- 6 个审查维度（题干 / 内容 / 配图×2 / 作答 / 音频 / 答错后）的 prompt 全部追加该后缀

### 3. `src/report_exporter.py`（修改）
- 新增 `export_html_live(self, questions, metadata)`：筛选 `overall_passed == False` 的错题，渲染可折叠 `<details>` 卡片（错误原因=红框、修改建议=绿框、附截图），截图拷贝到输出目录
- 新增 `_render_live_html()` / `_render_live_card()` 及配套 CSS `_HTML_LIVE_CSS` / 维度表 `_LIVE_DIMS`

### 4. `routes/error_log_routes.py`（**新增**）
- `GET /api/errors/live`：用 `send_file` 返回报告 HTML（供前端 iframe 预览）
- `GET /api/errors/live-status`：返回 `path / failed / total / ready`，供前端按钮与提示使用
- 使用延迟引用 `web_server` 模块，避免循环导入（模块顶层引用 `_inspection_state` 会因定义顺序报错）

### 5. `templates/index.html`（修改）
- 「错题日志」面板标题栏新增 **📑 查看报告** 按钮
- 新增弹窗遮罩 + `<iframe id="liveReportFrame">` + 下载按钮
- 新增 JS：`openLiveReport()` / `closeLiveReport()` / `refreshLiveReport()`

---

## 三、部署 / 运行步骤

```bat
cd <项目根目录>

:: 1) 确保虚拟环境依赖就绪（如 venv 失效，用 Python 3.13 重建并安装）
python -m venv uiautomator_venv
uiautomator_venv\Scripts\python.exe -m pip install pyyaml Pillow "Flask>=3.0.0"

:: 2) 启动服务
uiautomator_venv\Scripts\python.exe web_server.py
::    或（系统 Python 且 adb 已在 PATH 中）：python web_server.py

:: 3) 浏览器打开 http://localhost:5000
::    连手机（USB 调试 / WiFi 无线调试）→ 填版本/单元/阶段 + 上传脚本 docx → 点“开始审查”
::    审查过程中右侧“错题日志”实时刷新；点标题栏「📑 查看报告」弹窗查看报告
```

### 验收标准（4 条全过即完成）
1. 服务正常启动，无 `ImportError`、无 `I/O operation on closed file`
2. 主页右侧「错题日志」面板逐题刷新，红色即不通过
3. 点「📑 查看报告」→ 弹窗内每张错题含：来源（版本/单元/阶段/第几题）/ 红框错误原因 / 绿框修改建议 / 截图
4. 通过的题不出现在报告里；修改建议为 LLM 自动抽取的具体改法

---

## 四、提交注意（PR 前请确认）

1. **只提交这 5 个文件**，不要 `git add .`：
   - `uiautomator_venv/`、`outputs/`、`data/`、`__pycache__/` 均不应入库（如 `.gitignore` 未忽略，请只 add 下面 5 个）
   - `web_server.py`、`src/review_agent.py`、`src/report_exporter.py`、`routes/error_log_routes.py`、`templates/index.html`
2. **确认没有测试残留**：提交前不要存在 `data/inspection_state.json` 或 `outputs/reports/`
3. **`config.yaml` 本 PR 未改动**：其中 `serial` 仍写死为同事的手机序列号、`image_dir` 指向同事本地路径。队友拉下来跑需自行改为本机环境（或后续改为自动识别 —— 与 ADB 路径同样的思路）。

---

## 五、建议的 PR 标题与描述

**标题**
```
feat: 实时错题报告框架（方案 A）— 查看报告弹窗 + LLM 自动修改建议
```

**描述**
> 本次新增「实时错题报告」功能：审查过程中每判出一道错题，自动增量生成格式化 HTML 报告（题目来源 / 错误原因 / 修改建议 / 截图），前端「错题日志」面板新增「📑 查看报告」按钮，弹窗内以 iframe 展示。
>
> 主要改动：
> - 新增 `routes/error_log_routes.py`（2 个接口）
> - `web_server.py`：接入实时触发 + 来源信息，并修复 ADB 路径写死、stdout reconfigure 两个启动 Bug
> - `src/review_agent.py`：让 LLM 自动产出「建议修改」
> - `src/report_exporter.py`：新增 `export_html_live` 卡片渲染
> - `templates/index.html`：查看报告按钮 + 弹窗
>
> 注意：`config.yaml` 的 `serial`/`image_dir` 仍为同事本机路径，需使用者自行调整。
