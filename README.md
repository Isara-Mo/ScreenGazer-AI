# VN 翻译助手 🎮

视觉小说英语学习翻译工具 — 实时截图识别 + AI 翻译 + 单词查询

## 功能特性

| 功能 | 说明 |
|------|------|
| 📸 区域截图 | 鼠标拖拽选定屏幕区域，支持选择目标游戏窗口 |
| 🔍 OCR 识别 | Tesseract（本地快速）或 PaddleOCR（可选精准） |
| 🤖 AI 翻译 | 矫正 OCR 错误 + 翻译为中文，JSON 格式结构化返回 |
| 🖼 VL 直接识别 | 截图直接发给视觉大模型识别+翻译（适合艺术字） |
| 📖 单词查词 | 单击英文单词即可查看在语境中的含义 |
| ⌨ 快捷键触发 | Ctrl+Shift+T 立即翻译（可自定义） |
| 👁 自动监视 | 0.5s 轮询检测画面变化，文本稳定后自动触发 |
| 🔌 多平台AI | DashScope（通义）、OpenAI 兼容、Ollama 本地 |

## 快速开始

### 1. 安装依赖

```bash
# 安装核心依赖
uv sync

# 安装 PaddleOCR（可选，体积约 2GB）
uv pip install paddlepaddle paddleocr
```

### 2. 启动程序

```bash
uv run main.py
```

### 3. 首次配置

1. 点击 **⚙ 设置** 按钮
2. 在 **🤖 模型** 标签页填写 API Key
3. 在 **🔍 OCR** 标签页确认 Tesseract 路径
4. 点击 **保存并应用**

### 4. 使用流程

1. 点击 **🖱 拖拽选择区域** 框选游戏对话框区域
2. 点击 **▶ 开始监视** 启动自动检测
3. 游戏出现新对话时自动触发翻译
4. 或按 **Ctrl+Shift+T** 手动触发
5. 在结果面板中**单击英文单词**查询语境含义

## AI 提供商配置

### DashScope（推荐，通义千问）

```
Base URL: https://dashscope.aliyuncs.com/api/v1
API Key: sk-xxxxxxxxxxxxxxxx
文本模型: qwen-turbo
VL 模型: qwen3.6-flash
```

如有自定义 workspace：
```
Base URL: https://[workspace-id].cn-beijing.maas.aliyuncs.com/api/v1
```

### Ollama（本地，免费）

```
Base URL: http://localhost:11434
文本模型: llama3.2
VL 模型: llava
```

## OCR 配置

已配置的 Tesseract：
- 路径: `E:/Tool/Tesseract/tesseract.exe`  
- 参数: `-l eng`

## 识别模式选择

| 模式 | 适用场景 | 速度 | 准确度 |
|------|---------|------|--------|
| OCR + LLM | 普通字体对话框 | 快 | 良好 |
| VL 大模型 | 艺术字、特殊排版 | 较慢 | 最佳 |

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Shift+T` | 立即触发翻译（默认，可自定义）|
| 单击英文单词 | 查询该词在语境中的含义 |
| `Ctrl` + 拖选 | 选择多个单词查询词组含义 |

## 项目结构

```
translate_game/
├── main.py               # 入口
├── pyproject.toml        # uv 项目配置
├── .python-version       # Python 版本锁定
└── src/
    ├── core/             # 核心逻辑
    │   ├── capture.py    # 屏幕捕获
    │   ├── ocr_engine.py # OCR 引擎
    │   ├── llm_client.py # AI 客户端
    │   ├── translator.py # 翻译协调
    │   └── watcher.py    # 变化检测
    ├── workers/          # QThread 异步任务
    ├── ui/               # PySide6 界面
    └── utils/            # 工具模块
```

## 注意事项

- **首次运行** PaddleOCR 会自动下载约 200MB 的模型文件
- 运行在 **Anaconda 环境**的用户：程序已处理 Qt DLL 冲突，使用 `uv run` 启动即可
- 快捷键需要程序在**前台或系统托盘**运行时才有效
