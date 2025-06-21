# MultiMediaGenAI 项目

一个利用大语言模型（LLM）实现多媒体内容（如 YouTube 视频、本地字幕文件）翻译和格式转换的工具集。

## 核心功能

- **YouTube 视频翻译**: 输入一个YouTube视频链接，自动获取官方或自动生成的字幕，并将其翻译成指定语言。
- **本地文件翻译**: 支持直接翻译本地的 `.srt` 字幕文件。
- **EPUB 文件处理**:
  - **全自动翻译**: 提供一个由大语言模型（LLM）驱动的端到端工作流 (`workflows/translate_epub.py`)，能够将整本EPUB文件从源语言翻译成目标语言。
  - **深度解析与重建**: 不仅仅是提取文本，而是深度解析EPUB的内部结构，包括元数据、资源清单、阅读顺序(Spine)、目录(NCX/NAV)等，并在翻译后精确重建。
  - **智能标题处理**:
    - **章节标题 (`<title>`)**: 自动提取并翻译每个XHTML章节文件中的`<title>`标签内容，确保在阅读器或浏览器标签页中显示正确的译文标题。
    - **导航目录 (`nav.xhtml`)**: 能够翻译 ePub 阅读器用于原生目录展示的 `nav.xhtml` 文件中的章节标题。
    - **内容页 (`Contents`)**: 对于书中生成的目录页（通常标题为 "Contents"），不仅翻译页面标题，还能精确翻译页面内指向各章节的链接条目。
  - **复杂结构保持**: 能够准确识别并重建复杂的HTML结构，如带容器的图片、嵌套列表、以及由普通`<p>`标签模拟的"伪列表"。
  - **样式保真**: 精确保留并应用原始的CSS类，同时能处理由HTML标签（如`<strong><small>...</small></strong>`）定义的复杂内联样式，确保转换后的文件在视觉上与原书高度一致。
- **模块化与可扩展**: 项目遵循高内聚、低耦合的设计原则。核心功能（如日志记录、文件生成、数据获取与处理）都被封装在可重用的工具模块中。
  - **灵活的Prompt与术语表**: 工作流中使用的 Prompt 和术语表已解耦，便于未来通过外部配置动态指定，以提高翻译的灵活性和准确性。
- **统一的核心处理逻辑**:
  - **智能预处理**: 所有字幕（无论来源）都通过统一的 `merge_segments_intelligently` 函数进行预处理，该函数能将零散的片段智能地合并为完整的句子，极大地提升了翻译的上下文连贯性。
  - **高质量后处理**: 所有翻译完成的文本都通过统一的 `generate_post_processed_srt` 函数进行处理，以生成格式优美、易于阅读的SRT文件。
- **统一的日志系统**: 所有工作流均采用统一的日志记录器，为每次运行生成独立的、带时间戳的日志文件，便于追踪和调试。

## 架构与工作流

本项目的架构经过重构，实现了核心处理逻辑的统一。`workflows/` 目录下的脚本负责定义和编排任务，而具体的执行逻辑则由可复用的工具模块（如 `llm_utils`, `format_converters`）提供。

### 字幕翻译工作流

所有字幕工作流共享一个统一的翻译入口 `llm_utils.translator.execute_translation`，以及统一的字幕预处理和后处理流程。

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

### EPUB 处理工作流

```mermaid
graph TD;
    subgraph Input [输入]
        A[EPUB 文件]
    end

    subgraph Parsing [1. 解析阶段 - EpubParser]
        direction LR
        B1["解压EPUB到临时目录"]
        B2["解析 container.xml<br>找到 .opf 文件"]
        B3["解析 .opf 文件<br>(元数据, manifest, spine)"]
        B4["解析 nav.xhtml/toc.ncx<br>获取目录和章节标题"]
        B5["逐一解析章节HTML<br>映射到内部数据模型(Book)"]
    end

    subgraph Processing [2. 处理与翻译]
        C0["智能注入章节标题<br>(用于翻译无头HTML)"]
        C1["提取Book对象中的文本内容"]
        C2["调用LLM进行批量翻译"]
        C3["将翻译结果<br>更新回Book对象"]
        C4["智能修正内容页目录<br>(ToC Page)的链接标题"]
    end

    subgraph Writing [3. 生成阶段 - EpubWriter]
        direction LR
        D1["创建EPUB文件结构"]
        D2["写入资源文件<br>(CSS, 图片)"]
        D3["根据更新后的Book对象<br>生成新的章节XHTML"]
        D4["根据翻译后的元数据<br>生成新的配置文件<br>(content.opf, nav.xhtml)"]
        D5["打包生成最终的EPUB文件"]
    end

    Input --> Parsing;
    A --> B1 --> B2 --> B3 --> B4 --> B5;
    Parsing --> Processing;
    B5 -- book_obj --> C0 --> C1 --> C2 --> C3 --> C4;
    Processing --> Writing;
    C4 -- updated_book_obj --> D1 --> D2 --> D3 --> D4 --> D5;
    subgraph Output [输出]
        E[翻译后的新 EPUB 文件]
    end
    D5 --> E;
```

## 项目结构说明

- `workflows/`: **核心工作流编排**。项目的入口，每个文件代表一个完整的端到端任务。
- `llm_utils/`: **大语言模型交互**。封装了与LLM API的通信逻辑。
- `youtube_utils/`: **YouTube数据获取**。封装了所有与YouTube相关的下载和处理逻辑。
- `format_converters/`: **数据转换与处理**。负责文件的解析、字幕的预处理、后处理和最终文件内容的生成。
  - `epub_parser.py`: 提供了强大的 `EpubParser` 类，用于深度解析EPUB文件。
  - `epub_writer.py`: 提供了 `EpubWriter` 类，用于根据内部数据模型重建EPUB文件。
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

#### 翻译 EPUB 电子书

```bash
python workflows/translate_epub.py "/path/to/your/book.epub" --target_lang "zh-CN"
```
- **`epub_path`**: (必需) 本地 `.epub` 文件的完整路径。
- **`--target_lang`**: (可选) 目标翻译语言，符合 BCP 47 标准 (例如, `zh-CN`, `ja`, `en`)，默认为 `zh-CN`。

所有生成的文件，包括日志和翻译结果，将被保存在与源文件相同的目录中。例如，翻译 `my_book.epub` 将生成 `my_book_zh_CN.epub`。

## 已知问题与处理

### YouTube 字幕中的负时长 (Negative Duration)

- **问题现象**: 在处理某些YouTube视频时，日志中可能会出现关于"负时长" (`Negative duration detected`) 的警告。
- **根本原因**: 这是由于 YouTube 的自动语音识别 (ASR) 系统在生成字幕时，可能产生微小的时间戳误差，导致某个字幕片段的计算出的结束时间早于其开始时间。这属于上游数据源的固有问题。
- **处理策略**: 在 `youtube_utils/data_fetcher.py` 的 `preprocess_and_merge_segments` 函数中，我们不再丢弃这些片段，而是将它们的**时长修正为0**，并保留其文本内容。
- **结果**: 这样可以确保即使源数据存在微瑕，也不会丢失任何需要翻译的文本内容，保证了翻译的完整性。虽然在生成的SRT文件中，这些片段会成为"零时长"字幕（一闪而过），但这远优于丢失整句内容。

## EPUB 翻译核心优势

当前工作流不仅能完成端到端的书籍翻译，还具备以下精细化处理能力，确保了高质量的输出：

- **完整的目录翻译**:
  - **导航目录 (`nav.xhtml`)**: 能翻译 ePub 阅读器用于原生目录展示的 `nav.xhtml` 文件中的章节标题，提升阅读器原生体验。
  - **内容页 (`Contents`)**: 对于书中生成的目录页，能同时翻译页面标题和页面内的所有章节条目链接，保证目录的完整性。

- **精确的章节标题翻译**:
  - 能够提取并翻译每一个独立的XHTML章节文件 `<head>` 部分中的 `<title>` 标签内容。这确保了在阅读器或浏览器标签页中显示的标题与内容语言一致。

- **智能化的"无头"内容处理**:
  - 对于部分章节XHTML文件可能没有 `<h1>/<h2>` 标签（即"无头内容"）的情况，工作流能够智能地从 `toc.ncx` 或 `nav.xhtml` 中获取其应有的标题，在翻译流程中临时注入该标题以获得上下文，翻译完成后再将其从正文中移除，最终将翻译后的标题应用到 `nav.xhtml` 和 `.opf` 元数据中。这一过程确保了即使在结构不规范的源文件中，章节标题也能被正确翻译和应用。

- **灵活的 Prompt 与术语表管理**:
  - 工作流中使用的 Prompt 和术语表是解耦的，为未来通过外部配置文件或命令行参数动态指定不同领域、不同风格的翻译指令提供了可能，极大地提高了项目的灵活性和可扩展性。