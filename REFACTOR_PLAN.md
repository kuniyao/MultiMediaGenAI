# `genai-processors` 重構計劃

**最後更新**: 2025-07-12

## 1. 重構目標 (The "Why")

*   **核心目標**: 完全用 `genai-processors` 框架替換掉您自定義的 `BaseProcessor` 和 `Pipeline` 執行器。
*   **預期收益**: 
    *   **性能**: 利用 `//` 運算符實現簡單高效的並行處理。
    *   **可讀性與靈活性**: 使用 `+` 和 `//` 聲明式地定義工作流。
    *   **內存效率**: 從傳遞單一巨大的 `PipelineContext` 對象，轉變為處理輕量級的 `ProcessorPart` 數據流。
    *   **可維護性**: 遵循一個標準化的、經過良好設計的框架。

## 2. 重構策略 (The "How")

*   **總體策略**: 採用結構性、由下至上的方法。
*   **分支策略**: 所有工作在 `refactor/genai-processors` 分支上進行。
*   **起點**: 從“單文件翻譯”工作流開始，建立一個可複製的重構模式。

## 3. 重構步驟與驗證標準 (The "What")

### 階段 0: 準備工作

*   [x] 創建 `refactor/genai-processors` 分支。
    *   **驗證**: `git branch` 顯示當前在該分支上。
*   [x] 將 `genai-processors` 添加到 `requirements.txt` 並安裝。
    *   **驗證**: 在激活的虛擬環境中，`pip show genai-processors` 能成功顯示庫信息。

### 階段 1: 核心抽象層重構

*   [x] 創建 `workflows/parts.py` 用於定義所有 `ProcessorPart` 子類。
    *   **驗證**: 文件被創建，並至少包含一個基礎的 `Part` 定義。
*   [x] 刪除舊的抽象：`processors/base_processor.py`, `workflows/pipeline.py`, `workflows/dto.py`。
    *   **驗證**: 相關文件已從文件系統中刪除。

### 階段 2: “單文件翻譯”工作流重構

*   [x] **重構數據源**: 修改 `data_sources/local_file_source.py`。
    *   **任務**: 創建一個 `LocalFileSource(Processor)`，它接收 `TranslationRequestPart`，讀取文件內容，並輸出一個新的、包含了文件內容的 `TranslationRequestPart`。
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
*   [x] **重構提示產生器**: 修改 `llm_utils/prompt_builder_processor.py`。
    *   **任務**: 創建一個 `PromptBuilderProcessor(Processor)`，它接收 `TranslationRequestPart`，並輸出 `ApiRequestPart`。
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
*   [x] **重構翻譯器**: 修改 `llm_utils/translator.py`。
    *   **任務**: 創建一個 `TranslatorProcessor(Processor)`，它接收 `ApiRequestPart`，輸出 `TranslatedTextPart`。
    *   **驗證**: 為這個新的處理���編寫單元測試並通過。
*   [x] **重構文件寫入器**: 修改 `processors/subtitle/file_write_processor.py`。
    *   **任務**: 創建一個 `FileWriterProcessor(Processor)`，它接收 `TranslatedTextPart`，並將內容寫入磁盤。
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
*   [x] **組裝管道**: 修改 `translate.py`。
    *   **任務**: 使用 `+` 運算符將上述處理器連接成一個完整的管道。
    *   **驗證**: 從命令行成功執行一次端到端的文件翻譯，生成正確的輸出文件。

### 階段 3: EPUB 工作流重構

*   [x] **建立 EPUB 工作流模組**: 創建 `workflows/book/` 目錄。
    *   **任務**: 在 `workflows/book/` 中建立 `parts.py` 和 `processors.py` 檔案。
    *   **驗證**: 目錄和檔案結構已建立。
*   [x] **定義 EPUB 相關的 `Parts`**: 在 `workflows/book/parts.py` 中定義 EPUB 工作流程所需的 `Part`，例如 `EpubBookPart`, `ChapterPart`, `TranslatedBookPart`。
    *   **驗證**: 新的 `Part` 已被定義，並包含必要的屬性。
*   [x] **重構 EPUB 剖析器**: 修改 `processors/book/epub_parsing_processor.py`。
    *   **任務**: 創建一個 `EpubParsingProcessor(Processor)`，它接收 `TranslationRequestPart`，剖析 EPUB 檔案，並輸出一個 `EpubBookPart`。
    *   **驗���**: 為這個新的處理器編寫單元測試並通過。
*   [x] **重構章節擷取器**: 修改 `processors/book/chapter_extraction_processor.py`。
    *   **任務**: 創建一個 `ChapterExtractionProcessor(Processor)`，它接收 `EpubBookPart`，並為書中的每一個章節，產生一個 `ChapterPart`。
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
*   [x] **創建 "適配器" 處理器**: 在 `workflows/book/processors.py` 中創建一個 `ChapterToTranslationRequestProcessor`。
    *   **任務**: 這個處理器的功能是將 `ChapterPart` 轉換為 `TranslationRequestPart`，以串聯現有的翻譯流程。
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
*   [x] **重構書籍建構器**: 修改 `processors/book/book_build_processor.py`。
    *   **任務**: 創建一個 `BookBuildProcessor(Processor)`，它接收 `TranslatedTextPart` (由 `TranslatorProcessor` 產生)，將所有翻譯完的章節組裝成一本完整的、翻譯後的書籍，並輸出一個 `TranslatedBookPart`。
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
*   [ ] **重構 EPUB 寫入器**: 修改 `processors/book/epub_writing_processor.py`。
    *   **任務**: 創建一個 `EpubWritingProcessor(Processor)`，它接收 `TranslatedBookPart`，並將其寫入為��個 `.epub` 檔案。
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
    *   **狀態**: **遇到阻礙**。`EpubWritingProcessor` 的單元測試持續失敗。在使用 `ebooklib` 建立 EPUB 時，章節順序和內容驗證出現問題。即使切換到手動建立 ZIP 檔案的方式，測試仍然無法通過。需要重新評估 EPUB 的生成和驗證策略。
*   [ ] **組裝 EPUB 管道**: 在 `translate.py` 中，為 `.epub` 檔案建立一個新的工作流程分支，並使用 `+` 和 `//` (如果適用) 來組裝所有 EPUB 相關的處理器。
    *   **驗證**: 從命令行成功執行一次端到端的 EPUB 翻譯，生成正確的輸出檔案。

### 階段 4: YouTube 工作流重構 (待辦)

*   [ ] ...
