# src/ — C 同学：错误溯源与报告导出模块

> 本目录是「英语宝模块检测智能体」项目里 **C 同学** 负责的全部源码。
> 职责：把 A/B 同学跑完检测后产出的错题数据，转成**红框截图 + 错误文件夹 + 网页/CSV 报告 + 邮件**。

---

## 一、本目录有哪些文件

| 文件 | 分工 | 干什么 |
|---|---|---|
| `trace_engine.py` | **C1 + C2** | 溯源数据引擎（算错因/建议/坐标）+ 用 Pillow 画红框 |
| `error_collector.py` | **C3** | 遍历所有题，把错题整理成 `errors/{版本}_{单元}/{模块}/{题号}/` 分层文件夹 |
| `report_exporter.py` | **C4** | 生成网页报告（全貌 + 仅错误）和 CSV 汇总表 |
| `email_sender.py` | **C5** | 把报告通过邮件发给老师 |

> 另外还有 `routes/`（溯源 API、导出 API 蓝图）属于 C 同学，在上级目录 `英语宝模块检测/routes/`；本目录只放上面 4 个核心引擎。

---

## 二、每个文件怎么用（接口签名）

### 1. `trace_engine.py` —— 单题处理引擎
```python
class TraceEngine:
    def __init__(self, screenshots_dir: str = "screenshots")
    def generate(self, qid: str, question_data: dict) -> dict   # C1：算一道题的错情
    def draw_mark(self, screenshot_name: str, checks: list, out_path: str) -> str  # C2：画红框
```
- `generate()` 只处理**一道题**（输入该题数据，返回 `checks` 错情列表 + 题干上下文）。
- 红框坐标：数据里带 `error_box` 就直接用；没有则用占位坐标（见下方「待办」）。

### 2. `error_collector.py` —— 遍历 + 归档
```python
class ErrorCollector:
    def __init__(self, output_root: str = "outputs")
    def collect(self, questions: dict, version: str, unit) -> dict
```
- 收到**全部题**的字典，循环挑出 `overall_passed == False` 的错题。
- 每道错题：复制原图 → 调 `TraceEngine` 溯源 → 画红框 → 写 `error.json`。
- 返回 `{"failed": 出错数, "total": 总数, "output_dir": 报告根目录}`。
- 输出目录带「时分」后缀（如 `U6_20260729_1535`），**每次运行独立文件夹，互不覆盖**。

### 3. `report_exporter.py` —— 报告生成
```python
class ReportExporter:
    def __init__(self, output_root: str = "outputs")
    def export_html_full(self, questions: dict, metadata: dict) -> str    # 全貌报告 report_full.html
    def export_html_errors(self, questions: dict, metadata: dict) -> str  # 仅错误报告 report_errors.html
    def export_csv(self, questions: dict) -> str                          # 汇总表 summary.csv
```
- 报告里已加「模块」列（从 qid 第 2 段或数据 `module` 字段读取）。

### 4. `email_sender.py` —— 邮件
```python
class EmailSender:
    def send_report(self, to_email: str, subject: str,
                    html_body: str = "", attachments: list = None) -> dict
```
- 返回 `{"success": True/False, "message": "..."}`。
- 账号密码从**环境变量**读取（不写死在代码里）。

---

## 三、依赖

```bash
pip install pillow        # trace_engine / error_collector 用
```
`email_sender.py` 只用 Python 标准库 `smtplib`，无需额外安装。

> ⚠️ 这些文件用 `from src.xxx import ...` 互相引用，所以运行时要保证**项目根目录**（`英语宝模块检测/`）在 Python 路径里。本地测试用根目录的 `run_report.py` 即可。

---

## 四、本地运行（测试用）

在项目根目录执行：
```bash
python run_report.py
```
会读取 `data/inspection_state.json`，生成报告到 `outputs/.../`。

---

## 五、重要提醒（上传 GitHub 前必读）

1. **只能改这些文件**：本目录 4 个 `.py` + `routes/` 下两个蓝图。
   **绝对不能碰** A 同学（`review_agent.py` / `post_error_check.py` / `report_check.py` / `script_generator.py`）和 B 同学（`batch_runner.py` / `progress_tracker.py` / `recovery_handler.py` / `routes/batch_routes.py` / `web_server.py`）的文件。
2. **红框坐标待接**：`trace_engine._compute_region()` 在数据无 `error_box` 时给占位坐标，需 A/B 把真实坐标写入 `inspection_state.json` 的题目数据里。
3. **发邮件先配环境变量**：
   ```bash
   export EMAIL_USER="你的邮箱@qq.com"
   export EMAIL_PASSWORD="邮箱授权码"   # QQ/163 用授权码，不是登录密码
   ```
4. **`severity` 严重程度**目前硬编码在 `trace_engine.py` 顶部的 `DIMENSIONS` 表里（内容/图片/答案=high，音频/报告=low，题干=medium）。
5. **`outputs/` 是自动生成的**，已在项目根 `.gitignore` 忽略，不要上传。

---

## 六、输入数据格式（来自 A/B 的 `data/inspection_state.json`）

```json
{
  "questions": {
    "新湘鲁六上-模块A-U6-Q03": {
      "qid": "新湘鲁六上-模块A-U6-Q03",
      "question_type": "听音选择词汇",
      "screenshot": "q03.png",
      "stem": "选出你听到的单词",
      "script_answer": "B",
      "ai_stem": false, "ai_content": false, "ai_image": true, "ai_answer": true,
      "ai_audio": null, "ai_post_error": null, "ai_report": null,
      "stem_reason": "[不通过] ...", "content_reason": "...",
      "overall_passed": false
    }
  }
}
```
- `ai_*` 为 `False` → 该项不通过，记一条错误；`null` → 未检查（当通过）；`True` → 通过。
- qid 格式：`教材-模块-单元-题号`（模块可省略，省略时模块列留空）。
