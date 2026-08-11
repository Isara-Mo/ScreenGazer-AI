# Sceen Translation Assistant 🎮

[English](#english) | [中文](#中文)

---

<a id="english"></a>
## English (Default)

Visual Novel English learning and translation tool — Real-time screen capture + AI Translation + Interactive Word Lookup.

### Features
- 📸 **Smart Region Capture**: Drag to select a screen region. Supports binding to a specific game window so the capture box moves automatically when the window is moved.
- 🔍 **OCR Engine**: Tesseract (fast) or PaddleOCR (highly accurate, locked to stable v2.x for best performance).
- 🤖 **AI Translation**: Corrects OCR errors and translates to Chinese, with JSON structured output.
- 🖼 **VL Mode**: Sends screenshots directly to Vision-Language models (e.g., `qwen-vl-plus`) for direct extraction and translation (perfect for highly stylized fonts).
- 📖 **Interactive Word Lookup**: Click any English word in the result panel to see its contextual meaning. Drag to select phrases.
- ⌨ **Hotkeys**: Press `Ctrl+Shift+T` to instantly translate (customizable).
- 👁 **Auto Monitor**: Polls the screen every 0.5s and auto-translates when text stabilizes.
- 🧠 **Flexible Thinking Mode Control**: Supports 3-state Thinking mode selection (Default / Force Off / Force On) per model profile for optimal speed or deep reasoning.

### Quick Start

#### 1. Install Dependencies
Ensure you have [`uv`](https://github.com/astral-sh/uv) installed, then run:
```bash
# Install core dependencies (including PaddleOCR)
uv sync
```

#### 2. Run the Program
```bash
uv run main.py
```

#### 3. First-time Configuration
1. Click the **⚙ Settings (设置)** button.
2. In the **🤖 Model Settings (模型配置)** tab, create or edit your AI model profiles (e.g. DashScope, OpenAI, Ollama, DeepSeek).
3. In the **🔍 OCR** tab, select your preferred OCR engine.
4. Click **Save and Apply (保存并应用)**.

---

<a id="中文"></a>
## 中文

视觉小说英语学习翻译工具 — 实时截图识别 + AI 翻译 + 交互式单词查询。

### 功能特性
- 📸 **智能区域截图**: 鼠标拖拽选定屏幕区域，支持动态绑定目标游戏窗口。无论窗口如何移动或高 DPI 缩放，截图区域都能精准追踪。
- 🔍 **OCR 识别**: 支持 Tesseract（本地快速）或 PaddleOCR（极其精准，已锁定至无 Bug 的稳定 2.x 版本）。
- 🤖 **AI 翻译**: 自动矫正 OCR 错误并翻译为中文，要求模型使用 JSON 格式结构化返回，避免格式错乱。
- 🖼 **VL 直接识别**: 截图直接发给视觉大模型（如 `qwen-vl-plus`）识别+翻译（完美应对艺术字和特殊排版）。
- 📖 **交互式查词**: 在结果面板中**单击**任何英文单词，即可在弹窗中查看其在当前语境中的精确含义。支持拖选词组。
- ⌨ **快捷键触发**: 按 `Ctrl+Shift+T` 立即进行翻译（可自由自定义）。
- 👁 **自动监视**: 0.5s 轮询检测画面变化，当游戏对话文本输出完毕稳定后，自动触发翻译。
- 🧠 **灵活的三态 Thinking 控制**: 支持为每个模型独立设置 3 态深度思考模式（默认 / 强制关闭 / 强制开启），兼顾极速响应与复杂推理需求。

### 快速开始

#### 1. 安装依赖
请先安装 Python 环境包管理器 [`uv`](https://github.com/astral-sh/uv)，然后在项目目录下运行：
```bash
# 安装全部依赖（已内置最强精度的 PaddleOCR 引擎）
uv sync
```

#### 2. 启动程序
```bash
uv run main.py
```

#### 3. 首次配置
1. 点击主界面上的 **⚙ 设置** 按钮。
2. 在 **🤖 模型配置** 标签页新建或编辑 AI 模型配置（支持通义千问、OpenAI、Ollama、DeepSeek 等）。
3. 在 **🔍 OCR** 标签页选择 OCR 引擎（推荐 PaddleOCR）。
4. 点击 **保存并应用**。


### 项目结构
```text
translate_game/
├── main.py               # 启动入口
├── pyproject.toml        # uv 依赖配置文件（已修复 Paddle 兼容性）
├── .python-version       # 锁定 Python 运行版本
└── src/
    ├── core/             # 核心逻辑（截图/OCR/大模型/翻译调度）
    ├── workers/          # QThread 异步多线程任务
    ├── ui/               # PySide6 图形界面（悬浮窗/查词弹窗）
    └── utils/            # 通用工具模块
```
