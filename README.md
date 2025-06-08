# MultiMediaGenAI 项目

一个利用大语言模型（LLM）实现多媒体内容（如 YouTube 视频、本地字幕文件）翻译和格式转换的工具集。

## 核心功能

- **YouTube 视频翻译**: 输入一个YouTube视频链接，自动获取官方字幕或自动生成的字幕，并将其翻译成指定语言。
- **本地文件翻译**: 支持直接翻译本地的 `.srt` 字幕文件，同时保留原始时间轴信息。
- **模块化与可扩展**: 项目采用高内聚、低耦合的模块化设计，方便未来扩展新的功能和工作流。
- **高质量翻译策略**: 通过"预合并-翻译-后拆分"的智能处理流程，在保证时间轴基本准确的前提下，获得更连贯、更符合上下文的翻译质量。

## 架构与工作流

本项目的核心是 `llm_utils/Translator` 类，它是一个统一的翻译引擎。所有工作流（无论是处理YouTube字幕还是本地文件）都会先将自己的数据适配成一种标准的"富数据格式"，然后交由这个强大的翻译引擎处理。

```mermaid
graph TD;
    subgraph A[工作流1: YouTube视频]
        A1("YouTube 链接") --> A2["youtube_utils<br/>获取字幕数据"];
        A2 --> A3["common_utils.json_handler<br/><b>适配为标准富数据</b>"];
    end

    subgraph B[工作流2: 本地文件]
        B1("本地 .srt 文件") --> B2["format_converters<br/>解析字幕数据"];
        B2 --> B3["common_utils.json_handler<br/><b>适配为标准富数据</b>"];
    end

    subgraph C[核心翻译引擎]
        C1["llm_utils.batching<br/>智能批处理"];
        C2["llm_utils.prompt_builder<br/>构建提示词"];
        C3["llm_utils.Translator<br/><b>调用LLM API</b>"];
        C4["llm_utils.response_parser<br/>解析与验证响应"];
        C1 --> C2 --> C3 --> C4;
    end

    A3 --> C1;
    B3 --> C1;
    
    C4 --> D["format_converters<br/>后处理与生成<br/>(SRT, Markdown)"];
```

## 项目结构说明

- `workflows/`: **核心工作流编排**。项目的入口，每个文件代表一个完整的端到端任务。
- `llm_utils/`: **大语言模型交互**。封装了与LLM API的通信逻辑。
  - `translator.py`: 包含统一的 `Translator` 核心翻译类。
  - `prompt_builder.py`: 负责构建发送给LLM的详细指令。
  - `batching.py`: 负责将大量文本智能地拆分为适合API处理的批次。
  - `response_parser.py`: 负责解析和验证LLM返回的结果，确保数据质量。
- `youtube_utils/`: **YouTube数据获取**。封装了所有与YouTube相关的下载逻辑。
- `format_converters/`: **数据转换与处理**。负责文件的解析、字幕的预处理（合并）、后处理（拆分）和最终文件的生成。
- `common_utils/`: **通用工具库**。存放项目通用的辅助函数。
  - `json_handler.py`: **包含关键的数据适配器 `create_pre_translate_json_objects`**。


## 快速开始 (Quick Start)

### 1. 环境设置

首先，请确保您已安装 Python。然后，通过以下命令安装项目所需的依赖：

```bash
pip install -r requirements.txt
```
*(注意: 如果 `requirements.txt` 文件不存在或过时，您可以使用 `pip freeze > requirements.txt` 命令生成)*

### 2. 配置 API 密钥

在项目根目录创建一个名为 `.env` 的文件，并添加您的 Gemini API 密钥，格式如下：

```
GEMINI_API_KEY="your-gemini-api-key-here"
```

### 3. 运行工作流

#### 翻译 YouTube 视频

```bash
python workflows/translate_youtube_video.py "YOUTUBE_VIDEO_URL_OR_ID" --target_lang "zh-CN"
```
- **`video_url_or_id`**: (必需) YouTube视频的完整URL或视频ID。
- **`--target_lang`**: (可选) 目标翻译语言，默认为 `zh-CN`。

#### 翻译本地 SRT 文件

```bash
python workflows/translate_from_file.py "/path/to/your/subtitle.srt" --target_lang "zh-CN"
```
- **`file_path`**: (必需) 本地 `.srt` 字幕文件的完整路径。
- **`--target_lang`**: (可选) 目标翻译语言，默认为 `zh-CN`。


所有生成的文件，包括日志和翻译结果，将被保存在项目目录外的一个名为 `GlobalWorkflowOutputs` 的文件夹中，并以视频标题或文件名分类存放。