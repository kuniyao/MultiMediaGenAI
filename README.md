# MultiMediaGenAI: 智能多媒体翻译工具集

一个利用大语言模型（LLM）实现多媒体内容（如EPUB电子书、YouTube视频、本地字幕文件）翻译和格式转换的工具集。

## ✨ 核心功能

- **EPUB 电子书全自动翻译**:
  - **端到端工作流**: 输入一本EPUB电子书，输出一本完整翻译的、保留原格式的EPUB电子书。
  - **深度结构解析**: 精确保留并翻译元数据、多级目录、章节标题、图注、以及复杂的HTML结构。
  - **并发与异步**: 基于 `asyncio` 实现高并发翻译，可通过参数控制并发数，显著提升翻译速度。
  - **配置驱动**: 支持通过外部JSON文件自定义Prompts和术语表（Glossary），以适应不同领域和风格的翻译需求。

- **YouTube 视频翻译**: 
  - 输入一个YouTube视频链接，自动获取官方或自动生成的字幕，并将其翻译成指定语言，生成 `.srt` 文件。

- **本地文件翻译**: 
  - 支持直接翻译本地的 `.srt` 或 `.md` 格式文件。

- **智能文本处理**:
  - **片段智能合并**: 在翻译前将零散的字幕/文本片段合并为完整的句子，提升上下文连貫性。
  - **样式保真**: 在EPUB处理中，精确保留原始的CSS类和HTML标签，确保译文在视觉上与原书高度一致。

## 🚀 快速开始

### 1. 环境设置

首先，请确保您已安装 Python。然后，通过以下命令安装项目所需的依赖：

```bash
pip install -r requirements.txt
```

### 2. 配置 API 密钥

在项目根目录创建一个名为 `.env` 的文件，并添加您的 Gemini API 密钥，格式如下：

```
GEMINI_API_KEY="your-gemini-api-key-here"
```
程序将在翻译模块初始化时自动加载此密钥。

### 3. 运行工作流

#### 运行翻译工作流

所有翻译工作流现在都通过 `translate.py` 作为统一入口点。根据您提供的输入类型（YouTube URL、本地字幕文件或 EPUB 文件），脚本将自动选择并执行相应的工作流。

```bash
python translate.py "YOUR_INPUT_SOURCE" --target_lang "zh-CN" --output_dir "GlobalWorkflowOutputs" [其他可选参数]
```

-   **`YOUR_INPUT_SOURCE`**: (必需) 可以是：
    *   YouTube 视频的 URL (例如: `"https://www.youtube.com/watch?v=dQw4w9WgXcQ"`)
    *   本地 `.srt` 或 `.vtt` 字幕文件的完整路径 (例如: `"/path/to/your/subtitle.srt"`)
    *   本地 `.epub` 电子书文件的完整路径 (例如: `"/path/to/your/book.epub"`)
-   **`--target_lang`**: (可选) 目标翻译语言，默认为 `zh-CN`。
-   **`--output_dir`**: (可选) 所有翻译结果和日志文件的根目录。默认为 `GlobalWorkflowOutputs`。所有生成的文件将保存在此目录下，并按任务（视频标题或文件名）创建子目录。
-   **`--concurrency`**: (可选) 仅适用于 EPUB 翻译工作流。API 请求的并发数，默认为 `10`。
-   **`--prompts`**: (可选) 仅适用于 EPUB 翻译工作流。自定义 Prompts 的 JSON 文件路径。
-   **`--glossary`**: (可选) 仅适用于 EPUB 翻译工作流。自定义术语表的 JSON 文件路径。
-   **`--log_level`**: (可选) 日志级别，默认为 `INFO`。
-   **`--save_llm_logs`**: (可选) 一个布尔标志。如果设置，LLM 原始响应的 JSON 日志文件将在翻译任务**失败时**保存到任务的输出目录中，便于调试和问题排查。

所有生成的文件，包括翻译结果和任务日志，将被保存在 `--output_dir` 指定的目录下，并按视频标题或文件名创建子目录。

## 🔧 工作流详解

本项目的架构已经重构为基于"管道-处理器"的模式。`translate.py` 作为统一入口，根据输入类型动态组装一个 `Pipeline`（管道）。每个管道由一系列 `Processor`（处理器）组成，一个 `PipelineContext`（上下文）对象在处理器之间传递数据和状态。

### EPUB 翻译工作流

这是项目当前最完善和强大的工作流，其核心优势在于能够对EPUB进行"无损"翻译。

#### 数据流与核心数据结构

EPUB翻译工作流的核心是 `PipelineContext` 对象，它携带了 `format_converters.book_schema.Book` 对象在各个处理器之间流转。

-   **管道组装**: `translate.py` 识别出 `.epub` 输入，并组装一个包含以下处理器的管道：`EpubParsingProcessor`, `ChapterExtractionProcessor`, `BookTranslationProcessor`, `ValidationAndRepairProcessor`, `BookBuildProcessor`, `EpubWritingProcessor`。
-   **解析阶段 (`EpubParsingProcessor`)**: 解析EPUB文件，构建一个包含元数据、目录和章节内容的 `Book` 对象，并存入 `PipelineContext`。
-   **翻译与修复 (`BookTranslationProcessor`, `ValidationAndRepairProcessor`)**: 从 `Book` 对象中提取可翻译内容，调用LLM进行翻译。内置的验证和修复处理器会自动识别并修复潜在的"漏翻"内容。
-   **构建与生成 (`BookBuildProcessor`, `EpubWritingProcessor`)**: 将翻译和修复后的结果应用回 `Book` 对象，并最终将这个更新后的对象重新打包成一个新的EPUB文件。

#### 工作流图

```mermaid
graph TD;
    subgraph Input [输入]
        A[EPUB 文件]
    end

    subgraph Orchestration [统一协调]
        O1[translate.py]
        O2[workflows/pipeline.py]
    end

    subgraph ProcessingPipeline [处理管道: 一系列处理器]
        direction LR
        P1["<b>1. EpubParsingProcessor</b><br>解析EPUB，创建Book对象"]
        P2["<b>2. ChapterExtractionProcessor</b><br>从Book对象提取翻译任务"]
        P3["<b>3. BookTranslationProcessor</b><br>执行核心翻译"]
        P4["<b>4. ValidationAndRepairProcessor</b><br>验证翻译质量，创建修复任务"]
        P5["<b>5. BookBuildProcessor</b><br>将翻译结果应用回Book对象"]
        P6["<b>6. EpubWritingProcessor</b><br>将Book对象打包成新EPUB"]
    end

    subgraph Output [输出]
        E[翻译后的新 EPUB 文件]
    end

    A --> O1;
    O1 -- "组装EPUB处理器管道" --> O2;
    O2 -- "按顺序执行处理器" --> P1 --> P2 --> P3 --> P4 --> P5 --> P6;
    P6 --> E;
```

### 统一字幕翻译工作流

所有字幕类工作流（YouTube, 本地SRT文件）现在都通过 `translate.py` 统一入口，并由 `workflows/pipeline.py` 协调执行。

#### 数据流与核心数据结构

字幕翻译工作流的核心是 `PipelineContext` 对象，它携带了 `format_converters.book_schema.SubtitleTrack` 对象在各个处理器之间流转。

-   **数据源获取 (`DataFetchProcessor`)**: 根据输入（本地文件或YouTube URL）获取原始字幕片段。
-   **数据建模 (`ModelingProcessor`)**: 将原始片段构建成 `SubtitleTrack` 对象，存入 `PipelineContext`。
-   **翻译与重试 (`TranslationPrepProcessor`, `TranslationCoreProcessor`)**: 将 `SubtitleTrack` 转换为LLM任务，进行并发翻译。内置工作流层面的重试机制以提高成功率。
-   **后处理与生成 (`OutputGenProcessor`, `SubtitleFileWriteProcessor`)**: 将翻译结果更新回 `SubtitleTrack` 对象，并最终生成 `.srt` 和 `.md` 对照文件。

更详细的工作流说明请参阅 [统一字幕翻译工作流文档](docs/subtitle_translation_workflow.md)。

#### 工作流图

```mermaid
graph TD;
    subgraph Input [输入]
        A[本地 .srt 文件 或 YouTube 链接/ID]
    end

    subgraph Orchestration [统一协调]
        O1[translate.py]
        O2[workflows/pipeline.py]
    end

    subgraph ProcessingPipeline [处理管道: 一系列处理器]
        direction LR
        S1["<b>1. DataFetchProcessor</b><br>获取原始字幕片段"]
        S2["<b>2. ModelingProcessor</b><br>创建SubtitleTrack对象"]
        S3["<b>3. TranslationPrepProcessor</b><br>创建翻译任务"]
        S4["<b>4. TranslationCoreProcessor</b><br>执行核心翻译与重试"]
        S5["<b>5. OutputGenProcessor</b><br>生成SRT和MD文件内容"]
        S6["<b>6. SubtitleFileWriteProcessor</b><br>写入最终文件"]
    end

    subgraph Output [输出]
        H1[翻译后的 .srt 文件]
        H2[翻译后的 .md 对照文件]
    end
    
    A --> O1;
    O1 -- "组装字幕处理器管道" --> O2;
    O2 -- "按顺序执行处理器" --> S1 --> S2 --> S3 --> S4 --> S5 --> S6;
    S6 --> H1 & H2;
```

## 📂 项目结构

- `workflows/`: **核心工作流协调**。包含 `pipeline.py`（管道执行器）和 `dto.py`（数据传输对象）。
- `processors/`: **处理器集合**。包含所有独立的、可重用的处理步骤。
- `llm_utils/`: **大语言模型交互**。封装了与LLM API的通信、Prompt构建、并发控制等逻辑。
- `format_converters/`: **数据转换与处理**。负责文件的解析（EPUB, SRT）、文本的预处理和后处理。
- `youtube_utils/`: **YouTube数据获取**。封装了所有与YouTube相关的下载和处理逻辑。
- `common_utils/`: **通用工具库**。存放项目通用的辅助函数（如日志、文件操作），包括 `output_manager.py` 用于统一管理输出。
- `GlobalWorkflowOutputs/`: **默认输出目录**。所有翻译结果和任务日志的默认存放位置。
- `docs/`: **详细设计文档**。存放对主要工作流的详细设计和模块说明。

## ℹ️ 深入了解

本项目更详细的设计文档、模块功能说明和工作流原理保存在 `docs/` 目录下。推荐在进行二次开发或深入研究前阅读这些文档。