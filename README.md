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
| **错题溯源与报告** | 每道错题溯源到 维度/原因/建议 + 红框截图 + 网页/CSV/邮件报告（同学C 模块） |

---

## 一、环境要求

- Python 3.10+
- ADB（Android Platform Tools，已加入 `PATH`）
- Android 手机（USB 调试已开启，数据线连接电脑）
- 手机已安装英语宝 APP

## 二、依赖

```bash
cd 英语宝模块检测
pip install -r requirements.txt
pip install uiautomator2
pip install pillow        # 同学C 的 trace_engine / error_collector 用（红框标注）
```

`email_sender.py` 只用 Python 标准库 `smtplib`，无需额外安装。

## 三、运行

### 运行 Web 面板（推荐）

```bash
python web_server.py
# 浏览器打开 http://localhost:5000
```

面板上点按钮即可启动对应模块自动化检测。页面分 3 个 Tab：
- **① 任务配置**：一句话/手动配置要测的模块
- **② 运行日志 · 手机画面**：左侧运行日志 + 右侧手机实时画面
- **③ 审查结果**：左侧六维审查 + 右侧错题日志（溯源/评分/红框截图）

### 命令行单模块运行

```bash
cd scripts
python modules/听力专项.py     # 听力专项
python modules/口语训练.py     # 口语训练
python modules/单元自检.py     # 单元自检
python modules/知识过关.py     # 知识过关
python modules/巧记单词.py     # 巧记单词
python modules/语音评测.py     # 语音评测
```

## 四、目录结构

```
英语宝模块检测/
├── web_server.py                 # Web 控制面板（Flask，唯一启动入口）
├── config.yaml                   # 配置（设备/APP）
├── templates/index.html          # 前端页面
├── scripts/
│   ├── engine.py                 # ★ 核心引擎（题型处理/排序/匹配/填空）
│   ├── scheduler.py              # ★ 多模块调度器（统一切年级+依次调模块）
│   ├── config.py                 # 配置（模块/弹窗/年级）
│   ├── common/
│   │   ├── logger.py             # ★ 全局日志通道（模块流程 → 前端）
│   │   ├── tools.py              # 工具函数（坐标换算/广告关闭/年级切换）
│   │   ├── device.py             # 设备管理（ANDROID_SERIAL 选择）
│   │   └── setup.py              # 版本/年级切换
│   └── modules/
│       ├── 听力专项.py           # 听力专项（练习+测试）
│       ├── 口语训练.py           # 口语训练（录音/小喇叭）
│       ├── 单元自检.py           # 单元自检（36题/单元）
│       ├── 知识过关.py           # 知识过关（重点词汇+重点句型）
│       ├── 巧记单词.py           # 巧记单词（单词同步闯关）
│       └── 语音评测.py           # 语音评测（题目未做好，仅进入）
├── trace_engine.py               # 同学C：溯源引擎 + 截图红框标注（C1/C2）
├── error_collector.py            # 同学C：错误输出文件夹（C3）
├── report_exporter.py            # 同学C：HTML/CSV 报告（C4）
├── email_sender.py               # 同学C：邮件发送（C5）
├── src/                          # 旧版批量检查引擎（web_server 部分引用）
├── routes/                       # Flask 路由（trace/export 蓝图，web_server 启动导入）
├── data/                         # 知识库/检查数据
├── docs/                         # 早期规划文档
├── outputs/                      # 输出（自动生成，已 gitignore）
├── screenshots/                  # 截图
├── uploads/                      # 上传文件
└── _archive/                     # 弃用文件归档（可删除）
```

## 五、Web 面板操作

1. 浏览器打开 **http://localhost:5000**
2. 点击模块按钮启动自动化：
   - 🎧 **听力专项** — 练习+测试（`/api/audio/run`）
   - 🗣 **口语训练** — 录音/小喇叭（`/api/oral/run`）
   - 📋 **单元自检** — 36题全题型（`/api/unit/run`）
   - ✅ **知识过关** — 重点词汇+句型（`/api/knowledge/run`）
   - 🎤 **语音评测** — 仅进入模块（`/api/voice/run`）
   - 🧠 **巧记单词** — 单词同步闯关（`/api/qiaoji/run`）
3. 右侧日志实时显示执行进度

## 六、六大模块说明

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

## 七、多分辨率适配（S 函数）

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

## 八、录音题处理（两种）

**知识过关/单元自检**（有"原音/点击录音/点击结束"）：
```
点原音 → 点点击录音 → 点点击结束 → 点检测 → 下一题
```

**口语训练**（麦克风图标）：
```
找"点击录音"文字上方的麦克风 → 点同一位置两次（录音+结束）
```

## 九、填空注入方案（FastInputIME）

uiautomator2 无法定位系统键盘（搜狗/百度），用 **FastInputIME 注入**：

```python
d.set_fastinput_ime(True)   # 切换专用输入法
d.send_keys("cat")          # 直接注入文本（绕过搜狗拦截）
d.press("back")             # 收起键盘
```

## 十、已验证

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

## 附：同学C · 错误溯源与报告导出模块

> 职责：把检测跑完后产出的错题数据，转成**红框截图 + 错误文件夹 + 网页/CSV 报告 + 邮件**。
> 前端「错题日志」（Tab ③ 右侧）已集成溯源结果：`/api/inspect/state` 对每道错题附加
> `_trace`（维度/原因/建议/严重度/坐标）、`_score`（透明评分明细）、`_marked`（红框标注图）。

### 1. 本模块文件

| 文件 | 分工 | 干什么 |
|---|---|---|
| `trace_engine.py` | **C1 + C2** | 溯源数据引擎（算错因/建议/坐标）+ 用 Pillow 画红框 |
| `error_collector.py` | **C3** | 遍历所有题，把错题整理成 `errors/{版本}_{单元}/{模块}/{题号}/` 分层文件夹 |
| `report_exporter.py` | **C4** | 生成网页报告（全貌 + 仅错误）和 CSV 汇总表 |
| `email_sender.py` | **C5** | 把报告通过邮件发给老师 |
| `routes/trace_routes.py` | 溯源 API 蓝图 | `/api/trace/<qid>`、`/api/trace/list`、`/api/trace/screenshot/...`（骨架） |
| `routes/export_routes.py` | 导出 API 蓝图 | `/api/export/html`、`/api/export/csv`、`/api/export/email` 等（骨架） |

### 2. 接口签名

```python
class TraceEngine:                                   # 单题溯源 + 红框
    def __init__(self, screenshots_dir: str = "screenshots")
    def generate(self, qid, question_data) -> dict  # C1：返回 checks（维度/原因/建议/severity/坐标）+ script_context
    def draw_mark(self, screenshot_name, checks, out_path) -> str  # C2：画红框

class ErrorCollector:                                # 遍历 + 归档
    def __init__(self, output_root: str = "outputs")
    def collect(self, questions, version, unit) -> dict  # 返回 {failed,total,output_dir}

class ReportExporter:                                # 报告生成
    def export_html_full(self, questions, metadata) -> str
    def export_html_errors(self, questions, metadata) -> str
    def export_csv(self, questions) -> str

class EmailSender:                                   # 邮件
    def send_report(self, to_email, subject, html_body="", attachments=None) -> dict
```

### 3. 数据格式（每道题）

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
- qid 兼容两种格式：契约「教材-模块-单元-题号」（`新湘鲁六上-模块A-U6-Q01`）与实际
  「版本-单元-阶段-题号」（`新湘鲁六上-U6-基础巩固-Q03`），`error_collector._parse_qid` 自动识别。
- **评分怎么来**（透明）：每个「已检查」的维度等权，`得分 = 通过维度数 / 已检查维度数 × 100`，
  未检查维度不计分。错题日志卡片会展示公式与每个未通过维度的原因。

### 4. 重要提醒

1. **红框坐标**：`trace_engine._compute_region()` 在数据无 `error_box` 时给占位坐标，
   真实坐标接入后把 `error_box` 写进题目数据即可。
2. **发邮件先配环境变量**：
   ```bash
   export EMAIL_USER="你的邮箱@qq.com"
   export EMAIL_PASSWORD="邮箱授权码"   # QQ/163 用授权码，不是登录密码
   ```
3. **`severity` 严重程度**硬编码在 `trace_engine.py` 顶部 `DIMENSIONS` 表
   （内容/图片/答案=high，音频/报告=low，题干=medium）。
4. **`outputs/` 是自动生成的**，已在 `.gitignore` 忽略，不要上传。

---

*构建于 2026年8月 · WorkBuddy + ADB + uiautomator2*
