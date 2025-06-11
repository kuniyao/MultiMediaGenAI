# MultiMediaGenAI 项目

一个利用大语言模型（LLM）实现多媒体内容（如 YouTube 视频、本地字幕文件）翻译和格式转换的工具集。

## 核心功能

- **YouTube 视频翻译**: 输入一个YouTube视频链接，自动获取官方或自动生成的字幕，并将其翻译成指定语言。
- **本地文件翻译**: 支持直接翻译本地的 `.srt` 字幕文件。
- **模块化与可扩展**: 项目遵循高内聚、低耦合的设计原则。核心功能（如日志记录、文件生成、数据获取与处理）都被封装在可重用的工具模块中。
- **统一的核心处理逻辑**:
  - **智能预处理**: 所有字幕（无论来源）都通过统一的 `merge_segments_intelligently` 函数进行预处理，该函数能将零散的片段智能地合并为完整的句子，极大地提升了翻译的上下文连贯性。
  - **高质量后处理**: 所有翻译完成的文本都通过统一的 `generate_post_processed_srt` 函数进行处理，以生成格式优美、易于阅读的SRT文件。
- **统一的日志系统**: 所有工作流均采用统一的日志记录器，为每次运行生成独立的、带时间戳的日志文件，便于追踪和调试。

## 架构与工作流

本项目的架构经过重构，实现了核心处理逻辑的统一。`workflows/` 目录下的脚本负责定义和编排任务，而具体的执行逻辑则由可复用的工具模块（如 `llm_utils`, `format_converters`）提供。

所有工作流共享一个统一的翻译入口 `llm_utils.translator.execute_translation`，以及统一的字幕预处理和后处理流程。

工作流的核心流程如下：
1. **数据获取**: 工作流脚本调用 `youtube_utils` 或 `format_converters` 获取原始字幕数据。
2. **智能预处理**: 调用 `format_converters.preprocessing.merge_segments_intelligently` 将原始片段合并为完整句子。
3. **格式适配**: 使用 `common_utils.json_handler` 将合并后的数据转换为统一的"富数据格式"。
4. **执行翻译**: 将适配后的数据交给 `execute_translation` 函数进行翻译。
5. **高质量后处理与生成**: 调用 `format_converters.postprocessing.generate_post_processed_srt` 将翻译结果重构为最终的 `.srt` 文件（或 `reconstruct_translated_markdown` 生成 `.md` 文件）。

```mermaid
graph TD;
    subgraph A[工作流1: YouTube视频]
        A1("YouTube 链接") --> A2["youtube_utils<br/>获取原始字幕"];
    end

    subgraph B[工作流2: 本地文件]
        B1("本地 .srt 文件") --> B2["format_converters<br/>加载原始字幕"];
    end

    A2 --> C;
    B2 --> C;

    subgraph C[统一预处理]
        direction LR
        C1["merge_segments_intelligently<br/>智能合并片段"];
    end
    
    C --> D["common_utils.json_handler<br/>适配为标准富数据"];

    subgraph E[核心翻译引擎]
        direction LR
        D --> E0["execute_translation<br/>统一翻译入口"];
        E0 --> E1["LLM<br/>(批处理,提示,API,解析)"];
    end

    subgraph F[统一后处理]
        direction LR
        E1 --> F1["generate_post_processed_srt<br/>优化并生成SRT"];
    end
```

## 项目结构说明

- `workflows/`: **核心工作流编排**。项目的入口，每个文件代表一个完整的端到端任务。
- `llm_utils/`: **大语言模型交互**。封装了与LLM API的通信逻辑。
- `youtube_utils/`: **YouTube数据获取**。封装了所有与YouTube相关的下载和处理逻辑。
- `format_converters/`: **数据转换与处理**。负责文件的解析、字幕的预处理、后处理和最终文件内容的生成。
  - `preprocessing.py`: 包含核心的智能片段合并逻辑 `merge_segments_intelligently`。
  - `postprocessing.py`: 包含核心的翻译后优化逻辑 `generate_post_processed_srt`。
  - `srt_handler.py`: 负责SRT格式的基础解析与生成。
- `common_utils/`: **通用工具库**。存放项目通用的辅助函数。
  - `json_handler.py`: 包含关键的数据适配器 `create_pre_translate_json_objects`。
  - `file_helpers.py`: 提供通用的文件操作函数，如 `save_to_file`。
  - `log_config.py`: 提供统一的任务日志记录器 `setup_task_logger`。


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
程序将在翻译模块初始化时自动加载此密钥。

### 3. 运行工作流

#### 翻译 YouTube 视频

```bash
python workflows/translate_youtube_video.py "YOUTUBE_VIDEO_URL_OR_ID" --target_lang "zh-CN"
```
- **`video_url_or_id`**: (必需) YouTube视频的完整URL或视频ID。
- **`--target_lang`**: (可选) 目标翻译语言，默认为 `zh-CN`。
- **`--log_level`**: (可选) 设置日志级别 (如 `DEBUG`, `INFO`)，默认为 `INFO`。

#### 翻译本地 SRT 文件

```bash
python workflows/translate_from_file.py "/path/to/your/subtitle.srt" --target_lang "zh-CN"
```
- **`file_path`**: (必需) 本地 `.srt` 字幕文件的完整路径。
- **`--target_lang`**: (可选) 目标翻译语言，默认为 `zh-CN`。
- **`--log_level`**: (可选) 设置日志级别 (如 `DEBUG`, `INFO`)，默认为 `INFO`。

所有生成的文件，包括日志和翻译结果，将被保存在项目目录外的一个名为 `GlobalWorkflowOutputs` 或 `outputs` 的文件夹中，并以视频标题或文件名分类存放。

## 已知问题与处理

### YouTube 字幕中的负时长 (Negative Duration)

- **问题现象**: 在处理某些YouTube视频时，日志中可能会出现关于"负时长" (`Negative duration detected`) 的警告。
- **根本原因**: 这是由于 YouTube 的自动语音识别 (ASR) 系统在生成字幕时，可能产生微小的时间戳误差，导致某个字幕片段的计算出的结束时间早于其开始时间。这属于上游数据源的固有问题。
- **处理策略**: 在 `youtube_utils/data_fetcher.py` 的 `preprocess_and_merge_segments` 函数中，我们不再丢弃这些片段，而是将它们的**时长修正为0**，并保留其文本内容。
- **结果**: 这样可以确保即使源数据存在微瑕，也不会丢失任何需要翻译的文本内容，保证了翻译的完整性。虽然在生成的SRT文件中，这些片段会成为"零时长"字幕（一闪而过），但这远优于丢失整句内容。
