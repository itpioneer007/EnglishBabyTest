
# src/ — C 同学：错误溯源与报告导出模块

> 本目录是「英语宝模块检测智能体」项目里 **C 同学** 负责的全部源码。
> 职责：把 A/B 同学跑完检测后产出的错题数据，转成**红框截图 + 错误文件夹 + 网页/CSV 报告 + 邮件**。

# 英语宝模块检测系统

基于 **ADB + uiautomator2** 的英语宝 APP 自动化检测工具。
自动完成 6 大模块的答题检测：听力专项、口语训练、单元自检、知识过关、巧记单词、语音评测。

## ✨ 特性

| 特性 | 说明 |
|------|------|
| **6 大模块自动化** | 听力专项/口语训练/单元自检/知识过关/巧记单词/语音评测 |
| **多题型支持** | 选择/判断/填空/排序/匹配/录音/连词成句/填字母 |
| **Web 控制面板** | 一键启动任一模块，日志实时显示 |
| **多分辨率适配** | 所有坐标按屏幕比例动态换算，任意手机可用 |
| **题型智能分流** | 按题目文字自动识别题型并调用对应处理逻辑 |


---

## 一、本目录有哪些文件

| 文件 | 分工 | 干什么 |
|---|---|---|
| `trace_engine.py` | **C1 + C2** | 溯源数据引擎（算错因/建议/坐标）+ 用 Pillow 画红框 |
| `error_collector.py` | **C3** | 遍历所有题，把错题整理成 `errors/{版本}_{单元}/{模块}/{题号}/` 分层文件夹 |
| `report_exporter.py` | **C4** | 生成网页报告（全貌 + 仅错误）和 CSV 汇总表 |
| `email_sender.py` | **C5** | 把报告通过邮件发给老师 |


> 另外还有 `routes/`（溯源 API、导出 API 蓝图）属于 C 同学，在上级目录 `英语宝模块检测/routes/`；本目录只放上面 4 个核心引擎。

- Python 3.10+
- ADB（Android Platform Tools，已加入 `PATH`）
- Android 手机（USB 调试已开启，数据线连接电脑）
- 手机已安装英语宝 APP

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
<<<<<<< HEAD
pip install pillow        # trace_engine / error_collector 用
=======
cd 英语宝模块检测
pip install -r requirements.txt
pip install uiautomator2
>>>>>>> 11ce51b981aa79e22a84830a9389d04342ca3b13
```
`email_sender.py` 只用 Python 标准库 `smtplib`，无需额外安装。

<<<<<<< HEAD
> ⚠️ 这些文件用 `from src.xxx import ...` 互相引用，所以运行时要保证**项目根目录**（`英语宝模块检测/`）在 Python 路径里。本地测试用根目录的 `run_report.py` 即可。

---

## 四、本地运行（测试用）

在项目根目录执行：
```bash
python run_report.py
=======
### 运行 Web 面板（推荐）

```bash
python web_server.py
# 浏览器打开 http://localhost:5000
```

面板上点按钮即可启动对应模块自动化检测。

### 命令行单模块运行

```bash
cd scripts
python modules/听力专项.py     # 听力专项
python modules/口语训练.py     # 口语训练
python modules/单元自检.py     # 单元自检
python modules/知识过关.py     # 知识过关
python modules/巧记单词.py     # 巧记单词
python modules/语音评测.py     # 语音评测
>>>>>>> 11ce51b981aa79e22a84830a9389d04342ca3b13
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
<<<<<<< HEAD
- `ai_*` 为 `False` → 该项不通过，记一条错误；`null` → 未检查（当通过）；`True` → 通过。
- qid 格式：`教材-模块-单元-题号`（模块可省略，省略时模块列留空）。
=======
英语宝模块检测/
├── web_server.py                 # Web 控制面板（Flask）
├── templates/index.html          # 前端页面
├── scripts/
│   ├── engine.py                 # ★ 核心引擎（题型处理/排序/匹配）
│   ├── config.py                 # 配置（模块/弹窗/年级）
│   ├── common/
│   │   └── tools.py              # ★ 工具函数（S() 坐标换算/广告关闭/年级切换）
│   └── modules/
│       ├── 听力专项.py           # 听力专项（练习+测试）
│       ├── 口语训练.py           # 口语训练（录音/小喇叭）
│       ├── 单元自检.py           # 单元自检（36题/单元）
│       ├── 知识过关.py           # 知识过关（重点词汇+重点句型）
│       ├── 巧记单词.py           # 巧记单词（单词同步闯关）
│       └── 语音评测.py           # 语音评测（题目未做好，仅进入）
├── docs/                         # 早期规划文档
└── outputs/                      # 截图/日志
```

---

## 🎮 Web 面板操作

1. 浏览器打开 **http://localhost:5000**
2. 点击模块按钮启动自动化：
   - 🎧 **听力专项** — 练习+测试（`/api/audio/run`）
   - 🗣 **口语训练** — 录音/小喇叭（`/api/oral/run`）
   - 📋 **单元自检** — 36题全题型（`/api/unit/run`）
   - ✅ **知识过关** — 重点词汇+句型（`/api/knowledge/run`）
   - 🎤 **语音评测** — 仅进入模块（`/api/voice/run`）
   - 🧠 **巧记单词** — 单词同步闯关（`/api/qiaoji/run`）
3. 右侧日志实时显示执行进度

---

## 🧩 六大模块说明

### 1. 听力专项 (`听力专项.py`)
- 入口：主页 → 专项突破 → 听力专项
- 练习部分（基础巩固→综合进阶→难点突破）+ 测试部分
- 题型：听力选择/判断/填空（FastInputIME 注入）

### 2. 口语训练 (`口语训练.py`)
- 入口：主页 → 专项突破 → 口语训练
- 4 大题 × 5 小题（朗读单词/句子/看图回答/阅读短文）
- 题型：录音（点录音→点结束）/ 小喇叭（先点喇叭再录音）

### 3. 单元自检 (`单元自检.py`)
- 入口：主页下滑 → 专项突破 → 单元自检
- 每单元 36 题
- 题型：选择/判断(TF)/匹配(点A-E)/排序(图片直点/句子激活+序号)/填空/阅读

### 4. 知识过关 (`知识过关.py`)
- 入口：主页 → 知识过关 → 单元 → 收到了 → 重点词汇/重点句型
- 重点词汇 108 题 + 重点句型 8 题
- 题型：选择/判断/录音/填字母（10个字母按钮）/连词成句（点方框+点单词）/系统键盘填空
- 答过模块按钮变「重新闯关」；最后一题检测后出「提交」

### 5. 巧记单词 (`巧记单词.py`)
- 入口：主页 → 教材精学 → 巧记单词 → 单词同步闯关
- 每单元 6 关（关卡 1-5 + boss 关），关卡序号跨单元递增（U1: 1-6 → U2: 7-12...）
- 每关 15 题：听力选释义/填字母/录音题/选择
- 答错：检查 → 重新答题 → 二次错 → 跳过；答对：检查 → 下一题
- 最后一题：检查 → 提交 → 报告页 → back 两次回地图

### 6. 语音评测 (`语音评测.py`)
- 入口：主页 → 教材精学 → 语音评测
- 题目未做好，目前仅进入模块

---

## 🔧 多分辨率适配（S 函数）

所有坐标以 **1080×2400** 为基准，通过 `common/tools.py` 的 `S()` 函数动态换算：

```python
from common.tools import S, S_swipe, S_h, S_w

# 坐标换算（d.click 硬编码 → 动态）
d.click(*S(d, 540, 1192))          # 原: d.click(540, 1192)

# 滑动换算
S_swipe(d, 540, 1800, 540, 600)   # 原: d.swipe(540,1800,540,600)

# 范围判断换算
if S_h(d, 700) < b[1] < S_h(d, 1900):   # 原: 700 < b[1] < 1900
```

**换手机后无需改代码**——S() 按当前屏幕比例自动缩放。

---

## 🎤 录音题处理（两种）

**知识过关/单元自检**（有"原音/点击录音/点击结束"）：
```
点原音 → 点点击录音 → 点点击结束 → 点检测 → 下一题
```

**口语训练**（麦克风图标）：
```
找"点击录音"文字上方的麦克风 → 点同一位置两次（录音+结束）
```

---

## 🧮 填空注入方案（FastInputIME）

uiautomator2 无法定位系统键盘（搜狗/百度），用 **FastInputIME 注入**：

```python
d.set_fastinput_ime(True)   # 切换专用输入法
d.send_keys("cat")          # 直接注入文本（绕过搜狗拦截）
d.press("back")             # 收起键盘
```

---

## ✅ 已验证

| 验证项 | 状态 |
|--------|------|
| ADB 设备连接 | ✅ PJB110H1 |
| 听力专项 | ✅ 练习+测试跑通 |
| 口语训练 | ✅ U1 20题跑通 |
| 单元自检 | ✅ 36题跑通（含填空/排序/匹配） |
| 知识过关 | ✅ 重点词汇108题+重点句型8题 |
| 巧记单词 | ✅ 关卡1-5+boss+下一单元循环 |
| 语音评测 | ✅ 进入模块 |
| 多分辨率 | ✅ S() 换算全部模块 |

---

*构建于 2026年8月 · WorkBuddy + ADB + uiautomator2*
>>>>>>> 11ce51b981aa79e22a84830a9389d04342ca3b13
