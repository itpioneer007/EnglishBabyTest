# E英语宝模块检测系统

基于 ADB + uiautomator 的英语宝 APP 自动化检测工具。
通过 YAML 定义检测流程，自动完成登录、模块导航、内容校验、缺陷上报。

## ✨ 特性

| 特性 | 说明 |
|------|------|
| **全自动登录** | 勾协议 → 点登录 → 同意弹窗 → 关广告，一键完成 |
| **版本切换** | 自动检测所有教材版本，支持动态选择切换 |
| **模块检测** | 教材精学(4个) + 专项突破(8个)，一键逐个进入截图 |
| **双模式** | CLI 命令行 + Web 可视化面板，任意选择 |
| **YAML 流程** | 检测流程用 YAML 定义，可读可改 |
| **精确坐标** | uiautomator dump 获取像素级坐标，无需肉眼估算 |
| **适应轮播图** | 直接 tap 坐标绕过轮播图干扰 |

---

## 🚀 快速开始

### 环境要求

- Python 3.10+
- ADB（Android Platform Tools，已加入 `PATH`）
- Android 手机（已开启 USB 调试，通过数据线连接电脑）

### 安装

```bash
cd 英语宝模块检测
pip install -r requirements.txt
```

### 配置

编辑 `config.yaml`，填入设备序列号和账号：

```yaml
device:
  serial: "SKSCIF4T7PFMQS5X"    # adb devices 查看

account:
  username: "10010005"
  password: "123456"
```

### 运行

**方式 A：Web 面板（推荐）**
```bash
python web_server.py
# 浏览器打开 http://localhost:5000
```

面板上点按钮即可：**自动登录 → 刷新版本列表 → 选版本 → 勾模块 → 开始检测**

**方式 B：命令行**
```bash
# 一键登录
python main.py login

# 运行完整检测流程（版本切换 + 4个模块）
python -m src.flow_runner flows/version_and_module_test.yaml

# 查看设备
python main.py devices

# 调试：查看当前页面所有可点击元素
python main.py dump
```

---

## 📁 项目结构

```
英语宝模块检测/                    # ← 根目录
├── main.py                       # CLI 命令行入口
├── web_server.py                 # Web 控制面板服务器（Flask）
├── config.yaml                   # 全局配置（设备/账号）
├── requirements.txt              # Python 依赖
├── .gitignore
├── .vscode/
│   ├── launch.json               # VS Code 调试配置（F5）
│   └── settings.json
│
├── src/                          # 核心源码
│   ├── __init__.py
│   ├── adb_controller.py         # ★ ADB 智能控制器（核心）
│   ├── flow_runner.py            # YAML 流程执行引擎
│   └── config_loader.py          # 配置加载器
│
├── templates/                    # Web 前端
│   └── index.html                # Web 控制面板页面
│
├── flows/                        # YAML 检测流程定义
│   ├── login.yaml                # 自动登录流程
│   ├── close_popup.yaml          # 关闭弹窗流程
│   └── version_and_module_test.yaml  # 版本切换+模块测试
│
├── docs/                         # 项目文档
│   ├── 实施方案.md               # 原始需求分析与实施方案
│   ├── 操作日志.md               # 开发过程操作记录
│   ├── 检测流程规范.md            # 9步流程 + 6项检查标准
│   ├── 环境搭建指南.md            # ADB/设备/API 搭建步骤
│   └── 脚本数据格式.md            # 题库数据结构规范
│
├── outputs/                      # 运行结果（自动生成）
│   ├── screenshots/              # 模块截图
│   └── flow_log_*.json           # 操作日志
│
└── assets/
    └── report_template.html      # HTML 报告模板
```

---

## 🎮 使用说明

### Web 面板操作流程

1. 浏览器打开 **http://localhost:5000**
2. 确认左上角设备显示 **✅ 已连接**
3. 点击 **🔑 自动登录**（等待完成）
4. 点击 **📚 刷新版本列表**（自动检测所有可用版本）
5. **下拉选择目标版本**
6. **勾选要检测的模块**（教材精学/专项突破）
7. 点击 **▶ 开始检测**

面板会实时显示：
- 📋 执行进度条
- 📋 运行日志（每步操作）
- 📸 自动加载最新截图

### 编写新检测流程

在 `flows/` 下新建 `.yaml` 文件：

```yaml
name: "单词听写检测"
description: "进入单词听写模块逐题检查"
steps:
  - action: tap
    x: 919
    y: 2033          # 坐标: 单词听写

  - action: wait
    seconds: 3

  - action: screenshot
    name: "word_dictation"

  - action: press_back
```

### 支持的操作（action）

| action | 说明 | 关键参数 |
|--------|------|---------|
| `tap` | 坐标点击（推荐） | `x`, `y` |
| `click_element` | 智能点击（需 dump） | `text`, `resource_id`, `exact` |
| `swipe` | 滑动 | `x1,y1,x2,y2,duration` |
| `scroll_down` / `scroll_up` | 页面滚动 | `distance` |
| `wait_for_element` | 等待元素出现 | `text`, `timeout` |
| `wait` | 等待时间 | `seconds` |
| `screenshot` | 截图 | `name` |
| `press_back` / `press_home` | 按键 | — |
| `launch_app` | 启动APP | `package` |
| `list_clickable` | 列出可点击元素（调试） | — |

---

## 🧩 已验证的模块坐标

| 分组 | 模块 | 坐标 |
|------|------|------|
| 年级切换器 | 点击打开弹窗 | `(346, 275)` |
| 年级选择 | 一年级上/下, 二年级上/下, 三年级上/下, 四年级上/下, 五年级上 | 行1: `(180/540/900, 670)` 行2: `(180/540/900, 1172)` 行3: `(180/540/900, 1674)` |
| 教材精学 | 课本点读(左) / (中) / 巧记单词 / 语音评测 | `(203,1191)` `(540,1191)` `(876,1191)` `(203,1358)` |
| 专项突破(第一行) | 听课文 / 课文动画 / 基础训练 / 一课一练 | `(161,1792)` `(414,1792)` `(666,1792)` `(919,1792)` |
| 专项突破(第二行) | 课文配音 / 口语训练 / 复习回顾 / 全脑记词 | `(161,2033)` `(414,2033)` `(666,2033)` `(919,2033)` |
| 底部导航 | 英语 / 我 | `(108,2233)` `(972,2220)` |
| 设置图标 | ⚙️ (我页右上) | `(1000,170)` |
| 关闭广告 | × | `(540,1821)` |

---

## 🔄 已知版本列表

从英语宝版本选择页自动检测：

- `湘少版(2024审定)` — 四年级
- `湘鲁版(2024审定)` — 四年级（默认）
- `人教版(PEP)(2024审定)` — 四年级 下册
- `教科版(2024审定)` — 四年级 下册
- `教科版`

---

## 📦 输出文件

每次运行后，结果保存在 `outputs/`：

```
outputs/
├── screenshots/
│   ├── login_success.png          # 登录成功
│   ├── 01_version_select_page.png # 版本选择页
│   ├── 02_after_switch_renjiao.png# 切换后人教版
│   ├── 03_back_to_home.png       # 回到首页
│   ├── 04_module_kebendianfu.png  # 课本点读模块
│   ├── 05_module_qiaojidanci.png  # 巧记单词模块
│   ├── 06_module_tingkewen.png    # 听课文模块
│   └── ...更多模块
├── flow_log_*.json                # 操作日志
└── screenshot_*.png               # Web 面板截图
```

---

## 🛠️ 技术原理

```
浏览器 / 命令行
    │
    ▼
Web Server / Flow Runner
    │
    ▼
ADB Controller
    ├── uiautomator dump    ← 获取元素精确坐标
    ├── adb shell input tap ← 点击操作
    ├── adb shell swipe     ← 滑动操作
    └── adb shell screencap ← 截图
    │
    ▼
手机 英语宝APP
```

**核心优势**：
- `uiautomator dump` 提供像素级精准坐标
- ADB 直连手机操作系统，不受电脑桌面状态影响
- 直接 tap 坐标绕过轮播图/动画 idle state 限制

---

## 📚 文档

| 文档 | 内容 |
|------|------|
| [实施方案](docs/实施方案.md) | 原始需求分析与四阶段16步实施方案 |
| [操作日志](docs/操作日志.md) | 开发全过程操作记录（含踩坑经验） |
| [检测流程规范](docs/检测流程规范.md) | 9步流程 + 6项检查判定标准 |
| [环境搭建指南](docs/环境搭建指南.md) | ADB / 设备 / API 搭建步骤 |
| [脚本数据格式](docs/脚本数据格式.md) | 题库数据结构规范 |

---

## ✅ 已验证

| 验证项 | 状态 |
|--------|------|
| ADB 设备连接 | ✅ SKSCIF4T7PFMQS5X (OnePlus PJB110) |
| 全自动登录 | ✅ 54/54 通过 |
| 版本切换 | ✅ 5个版本可检测可切换 |
| 模块进入 | ✅ 4个模块全部正确进入 |
| 返回首页 | ✅ back / tap 英语 tab |
| Web 面板 | ✅ Flask 服务正常启动 |

---

*构建于 2026年7月 · WorkBuddy + ADB + uiautomator*
