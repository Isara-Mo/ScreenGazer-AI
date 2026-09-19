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
- 👁 **Text-Based Auto Monitor**: Periodically checks local OCR even when backgrounds animate or screenshots appear unchanged. Confirms stable text, normalizes layout differences, and skips unchanged text before calling the API. OCR results are reused for text translation.
- 🤖 **Multi-Model Profile Management**: Create and manage multiple AI provider profiles (DashScope, OpenAI, Ollama, DeepSeek, etc.) with independent main translation model & word lookup model selection.
- 🧠 **3-State Thinking Mode Control**: Per-profile 3-state Thinking mode control (Default / Force Off / Force On) to balance speed and reasoning.
- ⚡ **Full Asynchronous Non-Blocking Engine**: Multi-threaded `QThread` architecture ensures zero UI freezes during API requests, model connection testing, or OCR processing. Silenced PaddleOCR logger for a clean console.
- 📤 **Vocabulary Favorites**: Toggle favorites on or off, prevent duplicate entries, and export a copy without clearing your saved words.

### Monitoring and lookup controls

1. Select the game window, then crop just the dialogue/subtitle area where possible.
2. In **Settings → Trigger → Auto monitoring**, leave **Auto adapt** selected. It adjusts the waiting time using local OCR cost and text idle time; it does not identify the game or learn its fonts.
3. Choose **Fast subtitles** for rapidly replaced complete lines, or **Slow typing** if partial sentences are translated too early. **Manual tuning** reveals the original three controls and retains your values when switching presets. The image threshold is only an acceleration hint, never a prerequisite for OCR.
4. Drag the lookup window's title bar; resize using its bottom-right corner; use **A− / A+** for text size. **Pin** keeps the window at the same position for new lookups; **On top** controls visibility above other windows. Close it with **×** or Escape. Size, font and pin/top settings are remembered.

Automatic monitoring needs working local OCR in both recognition modes. Manual VL translation can still send an image when local OCR misses stylized text. OCR noise and long pauses within a typing animation can still affect detection; adjust the crop or preset in those cases. The status bar shows the current sampling wait and OCR time. Rapid translation/lookup requests retain only the newest queued request and discard superseded results; a request already sent to the provider cannot be recalled.

Floating panels retain the latest translation without flashing through per-sample OCR states. Monitoring details and elapsed times appear only in the main window; floating panels show a fixed translating message while a request is active, then the latest result or an error. An automatic result arriving after the observed text changes is held until its source matches again; a newly submitted sentence supersedes it. This prevents an old response from being presented as the new sentence while still tolerating a transient OCR error without another API request. Explicit manual translations remain available regardless of the automatic dialogue check.

**Auto adapt** uses a 0.30-second base sampling period. A new sentence needs at least two matching OCR samples and a final matching screenshot at least 0.65 seconds after the candidate first appeared. It checks text stability, so animated scenery need not stop. Capture and OCR runtime count toward the sampling period, with a short rest if processing overruns it. On an unchanged scene, idle OCR gradually backs off from 0.30 seconds to at most 0.90 seconds; inexpensive image checks continue, and image changes can prompt earlier OCR. These are bounded rules using OCR cost and idle time, not training that discovers optimal parameters for each game. Unchanged text is deduplicated before an API request.

The main window retains a compact breakdown after each translation: overall duration, text confirmation (capture/crop, accumulated OCR across samples, and waiting/checking), queue, request OCR or reuse, model, optional glossary correction, other processing/display, and any wait for dialogue to return. Text-stability time overlaps confirmation and is explicitly not added twice. Overall timing starts with the first capture observing that sentence, or the start of manual capture preparation, and ends when the application writes the result to its text widgets. A manual request made while monitoring excludes any wait for an already-running OCR cycle to finish before manual capture begins. It cannot measure the earlier interval between the game's actual text change and the first sample, nor the monitor's physical display latency. Request total excludes preceding monitoring and queue time.

Sampling frequency is retained. Only ordinary monitoring notices are coalesced to at most one update every two seconds; translation-stage elapsed time updates once per second, while start, completion and errors appear immediately. Floating panels stay steady. Fewer local checks would save processing but also delay discovery of new dialogue; repeated checks are not repeated API requests. Changing monitoring or game settings reuses the loaded OCR engine unless its configuration changes. The first local OCR load can still take several seconds. If complete sentences feel slow, try **Auto adapt** or **Fast subtitles**; **Slow typing** deliberately requires more confirmation. Model response time still depends on the provider.

### Genshin Impact profile

Select the running game in **Target window**, click **原神对白区域** (Genshin dialogue area), then **预览识别范围** (Preview capture). This enables the Genshin profile and captures a generous lower-window area that follows the window's size. A local colour-and-layout detector removes verified gold speaker/title rows while retaining the width and lower edge for multiline dialogue. Automatic monitoring only runs OCR and translation on confirmed dialogue or reply choices: it waits after a conversation ends instead of translating health bars, levels or key prompts, and resumes when dialogue returns. Manual translation retains the original pixels when detection is uncertain, including while monitoring. If text is already outside the capture, enlarge the selection; this cannot recover uncaptured text. Menus, replies using other icon designs, dialogue without a gold speaker, and very short or faded text may need manual translation.

Reply choices with the standard three-dot speech bubble are detected separately, including wrapped lines. A bound Genshin window automatically includes the lower/right reply area at runtime without overwriting the saved selection; unbound captures must include the choices and their bubble icons. NPC dialogue and all replies are translated together in one request, with explicit indices to prevent reordering. A draggable, resizable **回复选项** panel appears on the left with numbered Chinese/English pairs; use A−/A+ to adjust its font. Select the actual answer in the game. Repeated observations do not redraw cards, and a dismissed group stays hidden until the choices change or **显示全部浮窗** is used. Disappearing choices are hidden after a short confirmation delay; returning unchanged choices can reuse the previous translation. Invalid/missing model indices retain the source option and mark the missing translation. Each OCR sampling round includes all detected text blocks, so replies add local OCR work but are not separate API requests.

**Settings → 游戏适配** provides the dialogue-crop switch, glossary switch and optional `English = 中文` overrides. Generic mode retains its existing behaviour. The bundled offline glossary contains 6,454 source-backed mappings in the 2026-09-19 snapshot, including NPCs, places and organizations. It comes from the community [Genshin Dictionary open data](https://genshin-dictionary.com/en/opendata); provenance and filtering rules are recorded in `src/data/genshin_terms.SOURCES.md`.

The preview is a snapshot taken when opened. Its confirmation message indicates whether automatic dialogue detection passed. **保存捕获原图** (Save original capture) exports that snapshot at its original resolution; a screenshot of the scaled preview can lose the pixel details needed to diagnose missed detection.

The application keeps the original English and attaches only terms matched in the current dialogue to the translation prompt. Long names take precedence, word boundaries prevent substring replacements, and ordinary meanings of words such as Amber/Will remain subject to context. This improves terminology guidance without claiming identical official dialogue or guaranteed model compliance. Lookup explanations use the same game context. Missing or outdated names can be corrected in the custom list.

OCR mode still sends one translation request. VL mode uses available OCR hints on the first request; if vision reveals extra terms or misses an unambiguous expected translation, it can make **at most one additional request to the same VL model**. This also works with a VL-only configuration, at an increased latency/API cost. The local glossary is never fetched during translation. To refresh it manually, run `python scripts/update_genshin_glossary.py`, then restart the app. An offline rebuild is available via `--input path/to/words.json`.

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
- 👁 **基于文字的自动监视**: 持续检查本地 OCR，不再等待动态背景静止。连续确认文字稳定、消除换行等排版差异并去重后才调用 API；监视结果直接复用于文本翻译。
- 🤖 **多 Profile 模型配置管理**: 轻松新建、复制与管理多个 AI 模型配置（通义千问、OpenAI、Ollama、DeepSeek 等），支持独立指定主翻译模型与查词模型。
- 🧠 **三态 Thinking 深度思考控制**: 为每个模型独立设置 Thinking 模式（默认 / 强制关闭 / 强制开启），兼顾极速响应与复杂推理需求。
- ⚡ **全流程异步非阻塞架构**: 全多线程 `QThread` 架构，API 请求、连接测试、OCR 推理期间界面 0 卡顿 0 冻结；静默 PaddleOCR 终端 Warning 警告，保障控制台输出干净。
- 📤 **可取消的单词收藏**: 查词窗口点击收藏，再次点击取消；忽略大小写防止重复收藏，导出副本后保留收藏夹。

### 自动监视与查词窗口的使用方法

1. 先选择游戏窗口，再尽量只框选对话或字幕区域，避开其他界面文字。
2. **设置 → 触发 → 自动监视设置** 默认选择 **自动适应**：根据本地 OCR 耗时和文字空闲时长调整等待时间，无需先调三个数值。这是检测频率的自适应，不会自动识别游戏类型或训练字体。
3. 完整字幕切换很快时选 **快速字幕**；逐字显示的句子翻译过早时选 **慢速打字**。只有还需微调时再选 **手动微调**，原来的三个参数会保留。帧变化阈值仅提示加快检测，不再阻止周期 OCR。
4. 查词窗顶部可拖动，右下角可调整大小；**A− / A+** 调整字体。**固定** 表示后续查词继续显示在当前位置，**置顶** 控制是否显示在其他窗口上方。窗口持续显示，直到点击 **×** 或按 Escape；大小、字体和固定/置顶状态会保存。
5. **☆ 收藏 / ★ 已收藏** 可反复切换。导出单词本会保留已有收藏，不再自动清空。

两种模式的自动监视都需要可用的本地 OCR；如果本地 OCR 无法识别艺术字体，可以使用 **立即翻译** 手动调用 VL 识图。文字识别抖动、逐字显示过程中的长停顿仍可能影响检测，优先调整选区或切换监视方案。状态栏会显示当前采样等待和 OCR 耗时，首次模型加载可能较慢。快速连续翻译或查词时只保留最新的待处理请求，并忽略过时结果；已发送给模型提供商的请求无法撤回。

等待对白或确认新句时，浮窗保持最近一次译文，不随每轮 OCR 状态闪动。检测详情和等待秒数只在主窗口显示；浮窗仅在真正开始翻译时显示固定提示，完成后更新结果，失败时显示错误。新句已经被观察到时，上一句迟到的自动翻译会暂存；只有识别文本恢复一致才显示，新句提交后则淘汰旧结果。这能避免把旧响应当成新句答案，也不会因短暂 OCR 抖动重复调用 API。手动翻译不受这项自动显示检查限制。

**自动适应的规则**：以 **0.30 秒**为基础采样周期，新句需要至少 **2 次 OCR 一致**，且最后一张一致的截图距离候选文字首次出现至少 **0.65 秒**。判断的是文字稳定，无需等动态背景静止。周期内已花在截图和 OCR 上的时间会扣除，处理超时时只保留短暂休息；画面长期未变化时，本地 OCR 复查间隔逐步从 **0.30 秒放宽到最多 0.90 秒**，仍保留较快的图像检查，画面变化也可提前触发 OCR。这是根据识别耗时和空闲时长调整的规则，不会训练出各游戏的最优参数。同一句文字会先去重，不会因反复检测而重复调用 API。

每次翻译完成后，主窗口保留简洁的耗时汇总：**整体 → 确认文字（截图/裁切、累计 OCR 及次数、等待/判断）→ 排队 → 请求 OCR 或复用 → 模型 → 可选术语校正 → 其他处理/显示**；如旧结果曾暂存，还会列出等待对白恢复的耗时。“文字保持一致”与确认过程重叠，明确注明不再相加。整体从第一次采到这句文字的截图开始，手动翻译则从开始准备采集算起，到程序将结果写入文本框结束；监视中手动触发时，不包含采集前等待上一轮 OCR 结束的时间。整体也不包含无法测量的“游戏实际换句到首次采样”间隔，不代表显示器实际呈现的时延。“请求合计”仍单独保留，不包含此前监视和排队。

本次**保留实际采样频率，只合并界面提示**：普通监视状态最多每 **2 秒**刷新一次，翻译阶段计时每 **1 秒**刷新，开始、完成和错误立即显示；中文和英文浮窗保持稳定。减少本地检测虽能节省计算，也会增加发现新句的延迟，频繁检测本身不等于频繁请求 API。调整监视方案、选区或游戏设置时复用已加载的 OCR，只有 OCR 配置变更才重建；首次加载仍可能需要几秒。整句字幕感觉慢时先选 **自动适应** 或 **快速字幕**；**慢速打字** 会有意增加确认。模型返回速度仍取决于服务端。

### 原神专用适配

1. 主窗口 **目标窗口** 选择正在运行的原神，点击 **原神对白区域**。这会启用原神适配，并使用随窗口尺寸变化的底部宽选区，覆盖长短对白及可选称号。
2. 点击 **预览识别范围**，查看捕获原图与处理结果。程序联合检测金色标题和白色正文，动态排除人名、称号；横向与底部不缩窄，以保留多行文字。自动监视只识别已确认的对白或回复选项：对话结束后显示“等待原神对白”，暂停 OCR 和翻译，避免把血条、等级和按键提示送入模型；对白重新出现后自动恢复。定位不可靠时，**手动翻译**仍可使用完整原图，在监视期间也可手动触发。如果预览的原图已经漏字，应手动扩大选区，无法恢复框外文字。菜单、使用其他图标的选项、无金色人名、极短或淡入中的台词可能需要手动框选翻译。

原神右侧带标准三点气泡的回复选项现可独立识别，支持同一选项内的多行文字。绑定原神窗口时会在运行时补足下方及右侧范围，不覆盖已保存的选区；未绑定窗口时需把选项文字及气泡图标一起框入。角色台词与所有选项合并为一次翻译请求，并用明确编号匹配。新增左侧“回复选项”浮窗，按游戏中从上到下排列中英对照，可拖动、缩放和调字号；实际选择仍在游戏内操作。相同内容不重复刷新，手动隐藏后同组选项不再自动弹出，可用“显示全部浮窗”恢复。选项消失后短暂确认再隐藏；相同选项重新出现可复用上次译文。模型遗漏或返回异常编号时保留对应英文并标明缺少译文。每轮 OCR 包含对白及各选项的分块识别，因此增加本地识别工作，但不会为每个选项分别调用翻译 API。

3. **设置 → 游戏适配** 可分别关闭动态裁切或术语约束，也可切回通用模式。自定义译名每行填写 `English = 中文`，例如 `Pacal = 帕加尔`；可以补充或覆盖内置译名。重复、空值或无效格式会在保存前提示所在行。

预览是打开时的单张截图，顶部会明确标明是否通过自动对白判断。漏识别时可点击 **保存捕获原图**，导出同一次捕获的原始分辨率 PNG；直接截取缩小后的预览会改变字形像素，可能无法复现原来的漏检。

本次随附 **6,454 条中英对应**（2026-09-19 快照），包括人名、NPC、地点、组织等，来自 [Genshin Dictionary 社区开放数据](https://genshin-dictionary.com/en/opendata)。例如 `Odette → 奥黛塔`、`Pacal → 帕加尔`、`Children of Echoes → 回声之子`。来源、获取时间、原始数据摘要、过滤规则和条款链接见 `src/data/genshin_terms.SOURCES.md`。这是社区整理数据，可能有缺漏或版本滞后。

采用 **英文原文＋当前命中的术语约束**，不会先把英文句子改成中英混排，因此保留英文阅读和划词。匹配按完整词与长短语进行，不做近似拼写猜测；`Amber`、`Will` 等兼有普通英语含义的词会提示模型结合语境判断。查词也会使用同一游戏语境。这能加强专名一致性，但不保证复原官方整句台词，模型仍可能不遵守提示。

**OCR 模式仍为一次翻译请求**。VL 模式会先利用已有 OCR 命中词；若视觉识别发现新增术语或首轮译文遗漏明确译名，最多追加 **一次同 VL 模型校正请求**，无需额外配置文本模型，但会增加耗时和 API 用量。翻译过程中只查本地词表，不联网拉取。

手动更新词表（更新后重启程序）：

```powershell
python scripts/update_genshin_glossary.py
```

也支持 `--input 本地words.json路径` 离线重建；校验失败会保留旧词表。自定义译名保存在个人配置中，更新内置词表不会覆盖它们。

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
    ├── data/             # 内置原神术语与来源记录
    ├── workers/          # QThread 异步任务（翻译Worker/监视Worker/查词Worker）
    ├── ui/               # PySide6 图形界面（主窗口/拆分浮窗/查词弹窗/设置对话框）
    └── utils/            # 通用工具（配置管理/全局快捷键/单词本导出）
```

### 离线回归测试

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试使用临时单词本、内存配置、模拟 OCR/API 和无界面 Qt，覆盖文字监视、收藏切换、查词窗口、配置迁移、后台请求切换、原神动态裁切、词表匹配及翻译接入；不会使用个人 API Key 或修改现有单词本。
