# `genai-processors` 重構計劃

**最後更新**: 2025-07-13

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
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
*   [x] **重構提示產生器**: 修改 `llm_utils/prompt_builder_processor.py`。
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
*   [x] **重構翻譯器**: 修改 `llm_utils/translator.py`。
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
*   [x] **重構文件寫入器**: 修改 `processors/subtitle/file_write_processor.py`。
    *   **驗證**: 為這個新的處理器編寫單元測試並通過。
*   [x] **組裝管道**: 修改 `translate.py`。
    *   **驗證**: 從命令行成功執行一次端到端的文件翻譯，生成正確的輸出文件。

### 階段 3: EPUB 工作流重構 (新方案)

**核心思路**: 新的工作流將復用 `format_converters` 中成熟的 HTML 解析與構建邏輯。數據流將在結構化的 `Block` 對象和純文本之間轉換，從而避免讓 LLM 直接處理複雜的 HTML，根除 XML 格式錯誤。

*   [x] **建立 EPUB 工作流模組**: 創建 `workflows/book/` 目錄。
    *   **驗證**: 目錄和檔案結構已建立。
*   [x] **定義 EPUB 相關的 `Parts`**: 在 `workflows/book/parts.py` 中定義 `EpubBookPart`, `ChapterPart`, `TranslatedChapterPart`, `TranslatedBookPart`。
    *   **驗證**: 所有 `Part` 已被定義，並包含必要的屬性（例如 `ChapterPart` 包含一個結構化的 `Chapter` 對象）。
*   [x] **重構 EPUB 剖析器 (`EpubParsingProcessor`)**:
    *   **任務**: 確保處理器調用 `epub_parser.to_book()`，並輸出一個包含完整結構化 `Book` 對象的 `EpubBookPart`。
    *   **驗證**: 單元測試確認，給定一個 EPUB 路徑，處理器能輸出一個 `EpubBookPart`，且其 `book` 屬性是一個有效的 `Book` 對象。
*   [x] **重構章節擷取器 (`ChapterExtractionProcessor`)**:
    *   **任務**: 迭代 `EpubBookPart` 中的 `book.chapters` 列表，為每個 `Chapter` 對象產出一個 `ChapterPart`。
    *   **驗證**: 單元測試確認，處理器能為書中的每一章都產出一個 `ChapterPart`，且每個 `Part` 都包含原始的、未經修改的 `Chapter` 對象。
*   [x] **創建 HTML 序列化處理器 (`ChapterToHtmlProcessor`)**:
    *   **任務**: 創建一個新的 `PartProcessor`，它接收 `ChapterPart`，調用 `html_mapper` 將 `Chapter` 對象的內容轉換為一個乾淨的 HTML 字符串，並輸出 `TranslationRequestPart`。
    *   **驗證**: 單元測試確認，給定一個包含 `Chapter` 對象的 `ChapterPart`，處理器能輸出一個 `TranslationRequestPart`，其 `text_to_translate` 屬性是預期中的 HTML 字符串。
*   [x] **創建 HTML 反序列化處理器 (`HtmlToChapterProcessor`)**:
    *   **任務**: 它接收 `TranslatedTextPart`，先對 LLM 返回的原始字符串進行清理，然後調用 `html_mapper.html_to_blocks()` 將乾淨的 HTML 字符串解析回 `Block` 對象列表，最後輸出一個包含新的、已翻譯 `Chapter` 對象的 `TranslatedChapterPart`。
    *   **驗證**: 單元測試確認，給定一個包含模擬 LLM 輸出的 `TranslatedTextPart`，處理器能成功清理並解析，最終輸出一個包含正確 `Block` 結構的 `TranslatedChapterPart`。
*   [x] **重構書籍建構器 (`BookBuildProcessor`)**:
    *   **任務**: 修改為一個 `Processor`，它接收 `TranslatedChapterPart` 的數據流，從每個 `Part` 中提取出已翻譯的 `Chapter` 對象，在流結束時將它們組裝成一個完整的 `Book` 對象，並輸出單一的 `TranslatedBookPart`。
    *   **驗證**: 單元測試確認，在接收完一系列 `TranslatedChapterPart` 後，處理器能輸出一個 `TranslatedBookPart`，且其包含的 `Book` 對象中包含了所有預期的、已翻譯的章節。
*   [x] **重構 EPUB 寫入器 (`EpubWritingProcessor`)**:
    *   **任務**: 修改為一個 `Processor`，它接收 `TranslatedBookPart`，從中提取出 `Book` 對象，並直接將其傳遞給 `format_converters.epub_writer.book_to_epub()` 函數來生成最終的 `.epub` 文件。
    *   **驗證**: 單元測試確認，處理器在接收到 `TranslatedBookPart` 後，會使用正確的 `Book` 對象調用 `book_to_epub()` 函數。
*   [x] **組裝 EPUB 管道 (新)**:
    *   **任務**: 在 `translate.py` 中，按照新的邏輯組裝 EPUB 工作流。其核心將是 `(ChapterToHtmlProcessor + ... + HtmlToChapterProcessor).to_processor()` 的並行處理鏈。
    *   **驗證**: 從命令行成功執行一次端到端的 EPUB 翻譯 (`python translate.py ...`)。
    *   **當前狀態 (2025-07-13)**: 
        *   **重構完成**: EPUB工作流已成功遷移至 `genai-processors` 框架。
        *   **核心思想**: 新架構完美融合了 `genai-processors` 的流式、異步、模塊化能力，以及舊工作流中處理複雜場景的“智慧”。
        *   **智能預處理**: 創建了全新的 `ChapterPreparationProcessor`，它繼承了舊工作流中關於“智能切分長章節”和“自動打包短章節”的核心邏輯，將其無縫���入新框架。
        *   **健壯的翻譯**: `TranslatorProcessor` 被改造爲一個能響應多種任務類型（批處理、單塊）的、職責單一的翻譯服務中心。
        *   **端到端驗證**: 整個流程已成功通過端到端測試，能夠完整、準確地翻譯包含長章節的EPUB文件，且格式和內容均符合預期。所有已知的崩潰、內容丟失、格式錯誤問題均已解決。
        *   **文檔同步**: `01_workflow_epub_translation.md` 文檔已更新，詳細描述了新的、最終的工作流架構和數據流。

### 階段 4: YouTube 工作流重構 (待辦)

*   [ ] ...
