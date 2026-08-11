# ScreenGazer AI / 视觉小说翻译助手 🎮 (v1.0.0)

[English](#english) | [中文](#中文)

---

<a id="english"></a>
## English

**ScreenGazer AI** is an intelligent, real-time screen capture translation and language learning tool tailored for Visual Novels, games, and screen reading. It combines high-precision OCR (or Vision-Language models), multi-model LLM text correction & translation, interactive word/phrase lookup with word-boundary snapping, and sleek floating subtitle panels.

### Key Features (v1.0.0 Highlights)

- 📸 **Smart Window Binding & Occlusion-Free Capture**: Select your game window from a clean, filtered dropdown. Utilizes Windows `PrintWindow` handle capture so that other overlapping windows (like WeChat, Chrome, or translator panels) will **never obscure or interfere** with the capture.
- 🧱 **Independent Dual Floating Panels & Subtitle Bar**: Split English corrected text and Chinese translation into independent floating windows. Drag the Chinese panel to the bottom of your screen as a customizable long subtitle bar! Includes collapsible `📄 OCR Raw` text.
- 📖 **Direct Phrase Lookup & Word-Boundary Snapping**: Single-click any word or drag across a phrase to look up its contextual meaning (no `Ctrl` key needed!). Includes **Word-Boundary Snapping** that automatically completes incomplete head/tail words (e.g. dragging over "eat app" snaps to "eating apples").
- 👁 **Smart Anti-Spam Auto Monitor**: Ultra-fast frame-difference hashing and intelligent text deduplication with a configurable cooldown period (default 0.5s). Completely eliminates duplicate API calls caused by background game animations or visual effects.
- 🤖 **Multi-Model Profile Management**: Create and manage multiple AI provider profiles (DashScope, OpenAI, Ollama, DeepSeek, etc.) with independent main translation model & word lookup model selection.
- 🧠 **3-State Thinking Mode Control**: Per-profile 3-state Thinking mode control (Default / Force Off / Force On) to balance speed and reasoning.
- ⚡ **Full Asynchronous Non-Blocking Engine**: Multi-threaded `QThread` architecture ensures zero UI freezes during API requests, model connection testing, or OCR processing. Silenced PaddleOCR logger for a clean console.
- 📤 **Vocab Export**: Save clicked words to an in-app vocabulary list and export to `vocab.txt`.

### 💡 Recognition Modes Notice

> **Note**: You do **NOT** need to configure both Text and VL models simultaneously unless you plan to use both modes. Simply configure the model required for your selected mode:
> - **Mode 1: OCR + Text LLM (Default & Recommended)**: Uses OCR to extract text, then sends text to a Text LLM. **Requires ONLY a Text Model** (e.g., `qwen3.7-flash`). Fast response, low token consumption.
> - **Mode 2: VL Model Direct Recognition**: Sends the screenshot directly to a Vision-Language Model. **Requires ONLY a VL Model** (e.g., `qwen3.7-flash` / `qwen3.7-plus`). Excellent for stylized fonts, complex game layouts, or manga.

### Recommended AI Models

Recommended model configurations based on optimal speed, translation accuracy, and cost-effectiveness:

| Model Provider | Text Model | Vision (VL) Model | Recommendation & Use Cases |
| :--- | :--- | :--- | :--- |
| **DashScope (Alibaba)** | `qwen3.7-flash` | `qwen3.7-flash` / `qwen3.7-plus` | **Top Pick**: Ultra-fast response (~1s), low token cost, excellent EN-ZH visual novel translation quality. |
| **OpenAI Compatible** | `qwen3.7-flash` / `deepseek-v4-flash` | `qwen3.7-flash` / `qwen3.7-plus` | **Flexible Choice**: Highly stable JSON output, ideal for custom API proxies or DeepSeek compatible providers. |
| **Ollama (Local)** | `Hy-MT2-7B` / `Qwen3.5 9B` / `Qwen3 4B` / `Qwen3 1.7B` | N/A | **100% Offline & Free**: Zero API costs or network latency. `Hy-MT2-7B` is specifically fine-tuned for translation; Qwen3 series provides versatile multi-size lightweight local inference. |

### Quick Start

#### 1. Install Dependencies
Ensure you have [`uv`](https://github.com/astral-sh/uv) installed:
```bash
uv sync
```

#### 2. Launch Application
```bash
uv run main.py
```

#### 3. First-Time Setup
1. Click **⚙ Settings (设置)**.
2. Under **🤖 Model Settings**, configure your API Key and select your preferred Text or VL model based on your recognition mode.
3. Under **🔍 OCR**, choose between **PaddleOCR** (recommended) or **Tesseract**.
4. Select your target game window or drag to select a screen area.

---

<a id="中文"></a>
## 中文

**ScreenGazer AI (视觉小说翻译助手)** 是一款专为视觉小说 (Visual Novel)、生肉游戏及屏幕阅读设计的智能实时截图翻译与英语学习工具。结合高精度 OCR（或视觉大模型）、AI 文本自动矫正翻译、词界自动吸附划词讲解、以及独立长条字幕浮窗。

### 核心功能特性 (v1.0.0 重磅更新)

- 📸 **智能窗口绑定与抗遮挡截图**: 自动过滤掉无用的系统杂项窗口，提供干净的下拉选单。绑定游戏窗口后，采用 `PrintWindow` 句柄独占截图，**完全无视**覆盖在游戏上方的其他窗口（如浏览器、微信或翻译浮窗本身）。
- 🧱 **独立双浮窗 & 底部长条字幕框**: 支持将英文矫正原文与中文翻译拆分为独立浮窗。中文框可单独拖至屏幕底部拉成极简长条字幕框（Subtitle Bar）。内置可折叠 `📄 OCR原文` 展收查看。
- 📖 **免 Ctrl 直划查词 & 词界自动吸附**: 鼠标单击单词或直接拖拽划选短语即可实时召唤 AI 上下文讲解（无需按 `Ctrl`）。内置 **词界自动吸附 (Word-Boundary Snapping)**，划选到残缺单词时自动补全扩展至完整词界（如划到 "eat app" 自动补全为 "eating apples"）。
- 👁 **智能防刷屏自动监视**: 基于毫秒级图像帧差与文本去重算法，游戏对话文本静止后自动触发翻译。配合可调冷却期（默认 0.5s），彻底拦截重复 API 发包与背景动画干扰。
- 🤖 **多 Profile 模型配置管理**: 轻松新建、复制与管理多个 AI 模型配置（通义千问、OpenAI、Ollama、DeepSeek 等），支持独立指定主翻译模型与查词模型。
- 🧠 **三态 Thinking 深度思考控制**: 为每个模型独立设置 Thinking 模式（默认 / 强制关闭 / 强制开启），兼顾极速响应与复杂推理需求。
- ⚡ **全流程异步非阻塞架构**: 全多线程 `QThread` 架构，API 请求、连接测试、OCR 推理期间界面 0 卡顿 0 冻结；静默 PaddleOCR 终端 Warning 警告，保障控制台输出干净。
- 📤 **单词本导出**: 交互查词自动积累到收藏夹，支持一键导出为 `vocab.txt` 单词本。

### 💡 识别模式特别说明

> **提示**：您**无需**同时配置文本模型与视觉模型！根据您在【识别模式】中选择的模式配置对应模型即可：
> - **模式 1: OCR 识别 + 文本 LLM (默认推荐)**：先用 OCR 提取文字，再发送给文本大模型进行矫正与翻译。**仅需配置【文本模型】**（如 `qwen3.7-flash`）。响应极快、token 消耗少。
> - **模式 2: VL 视觉大模型直接识别**：将截图直接发送给多模态大模型进行识图翻译。**仅需配置【VL 视觉模型】**（如 `qwen3.7-flash` / `qwen3.7-plus`）。完美应对艺术字、复杂排版或花体字体。

### 推荐 AI 模型配置

基于测试与实际体验，推荐以下模型搭配方案：

| 提供商 (Provider) | 文本模型 (Text Model) | 视觉模型 (VL Model) | 推荐理由与适用场景 |
| :--- | :--- | :--- | :--- |
| **阿里 DashScope (通义)** | `qwen3.7-flash` | `qwen3.7-flash` / `qwen3.7-plus` | **首选推荐**：毫秒级响应（秒出）、Token 价格低廉，视觉小说中英翻译质量地道流畅。 |
| **OpenAI 兼容接口** | `qwen3.7-flash` / `deepseek-v4-flash` | `qwen3.7-flash` / `qwen3.7-plus` | **灵活中转**：JSON 结构化返回极稳定，适合使用 DeepSeek、通义兼容节点或第三方中转站。 |
| **Ollama (本地私有化)** | `Hy-MT2-7B` / `Qwen3.5 9B` / `Qwen3 4B` / `Qwen3 1.7B` | - | **100% 离线免费**：无网络依赖与计费。`Hy-MT2-7B` 为专用翻译微调模型；Qwen3 系列提供多尺寸轻量级高效本地推理。 |

### 快速开始

#### 1. 安装依赖
确保已安装 [`uv`](https://github.com/astral-sh/uv) 包管理器，在项目根目录运行：
```bash
uv sync
```

#### 2. 启动程序
```bash
uv run main.py
```

#### 3. 首次配置
1. 点击主界面上的 **⚙ 设置** 按钮。
2. 在 **🤖 模型配置** 中根据您选择的识别模式，填入 API Key 并指定【文本模型】或【VL 视觉模型】。
3. 在 **🔍 OCR** 标签页选择 OCR 引擎（推荐 PaddleOCR）。
4. 在主界面下拉框选择目标游戏窗口，点击 **▶ 开始监视** 或使用快捷键 `Ctrl+Shift+T`。

### 项目结构
```text
ScreenGazer-AI/
├── main.py               # 程序启动入口
├── pyproject.toml        # uv 依赖配置文件
├── config.json           # 默认与用户配置文件
└── src/
    ├── core/             # 核心逻辑（PrintWindow 截图/OCR/LLM 客户端/翻译协调/Watcher）
    ├── workers/          # QThread 异步任务（翻译Worker/监视Worker/查词Worker）
    ├── ui/               # PySide6 图形界面（主窗口/拆分浮窗/查词弹窗/设置对话框）
    └── utils/            # 通用工具（配置管理/全局快捷键/单词本导出）
```
