import sys
import os
import argparse
import logging
import json # <-- 確保導入 json
# from tqdm import tqdm # 如果有使用，需要替換為非同步版本或暫時移除
import asyncio # <--- 導入 asyncio

# 将项目根目录添加到Python路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from format_converters.epub_parser import epub_to_book
from format_converters.epub_writer import book_to_epub
from llm_utils.book_processor import extract_translatable_chapters, apply_translations_to_book
# 【關鍵】導入新的非同步函式
from llm_utils.translator import execute_translation_async

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 【修改點 1】將 main 函式變為 async def
async def main():
    """
    執行EPUB真實翻譯端到端工作流的主函式。
    """
    parser = argparse.ArgumentParser(description="使用LLM翻譯EPUB文件，並生成一個新的EPUB。")
    parser.add_argument("epub_path", type=str, help="要翻譯的源EPUB文件的路径。")
    parser.add_argument("--target_lang", type=str, default="zh-CN", help="翻译的目标语言 (例如, zh-CN, ja, ko)。")
    parser.add_argument("--concurrency", type=int, default=10, help="API請求的並發數限制。")
    parser.add_argument("--prompts", type=str, default="prompts.json", help="Path to a JSON file with prompt templates.")
    parser.add_argument("--glossary", type=str, default=None, help="Optional path to a JSON glossary file.")
    args = parser.parse_args()

    # --- 載入 Prompts 和詞彙表 ---
    prompts = {}
    if os.path.exists(args.prompts):
        logger.info(f"Loading prompts from {args.prompts}...")
        with open(args.prompts, 'r', encoding='utf-8') as f:
            prompts = json.load(f)
    else:
        logger.error(f"Prompts file not found at {args.prompts}. Aborting.")
        return

    glossary = None
    if args.glossary:
        if os.path.exists(args.glossary):
            logger.info(f"Loading glossary from {args.glossary}...")
            with open(args.glossary, 'r', encoding='utf-8') as f:
                glossary = json.load(f)
        else:
            logger.warning(f"Glossary file specified but not found at {args.glossary}. Proceeding without a glossary.")

    source_path = args.epub_path

    if not os.path.exists(source_path):
        logger.error(f"错误：文件未找到 - {source_path}")
        return

    # --- 1. 解析 EPUB ---
    logger.info(f"正在加载和解析EPUB文件: {source_path}...")
    try:
        book = epub_to_book(source_path)
    except Exception as e:
        logger.error(f"解析EPUB时发生错误: {e}", exc_info=True)
        return
    logger.info("解析完成。")

    # --- 2. 提取可翻译章节 (新) ---
    logger.info("正在提取可翻译章节...")
    translatable_chapters = extract_translatable_chapters(book, logger=logger)
    if not translatable_chapters:
        logger.info("在此EPUB中未找到可翻译的章节。工作流终止。")
        return
    logger.info(f"提取了 {len(translatable_chapters)} 个可翻译的章节任务。")

    # --- 3. 准备翻译任务 (新) ---
    logger.info("已将章节任务转换为翻译器所需的格式。")

    tasks_for_translator = [
        {
            "llm_processing_id": chapter_task["llm_processing_id"],
            "text_to_translate": chapter_task["text_to_translate"],
            "source_data": chapter_task["source_data"]
        }
        for chapter_task in translatable_chapters
    ]

    # --- 步骤二验证信息 ---
    print("\n--- 步骤二验证信息 ---")
    print(f"生成的总任务数: {len(tasks_for_translator)}")
    if tasks_for_translator:
        first_task = tasks_for_translator[0]
        print("第一个任务详情示例:")
        print(f"  ID: {first_task['llm_processing_id']}")
        print(f"  源数据类型: {type(first_task['source_data'])}")
        print(f"  HTML内容 (前300字符):")
        if first_task['source_data'].get('type') == 'json_batch':
             print(first_task['text_to_translate'][:300].strip())
        else:
             print(first_task['text_to_translate'][:300].strip())
    print("--- 验证信息结束 ---\n")
    # ----------------------

    # --- 4. 执行翻译 ---
    logger.info("正在調用高級非同步翻譯函數...")
    source_lang = book.metadata.language_source if book.metadata.language_source else "en"
    output_dir = os.path.dirname(os.path.abspath(source_path))

    # 【關鍵】使用 await 呼叫新的非同步函式
    translated_results = await execute_translation_async(
        pre_translate_json_list=tasks_for_translator,
        source_lang_code=source_lang,
        target_lang=args.target_lang,
        video_specific_output_path=output_dir, # 用於保存日誌
        logger=logger,
        concurrency=args.concurrency, # 傳入併發限制
        prompts=prompts,      # <-- 傳入 prompts
        glossary=glossary    # <-- 傳入 glossary
    )

    if not translated_results:
        logger.error("翻译过程失败或未返回任何结果。工作流终止。")
        return

    logger.info(f"成功从翻译器接收到 {len(translated_results)} 个结果。")

    # --- 5. 使用新的更新器，将翻译结果写回Book对象 (新) ---
    logger.info("Applying translations to create a new Book object...")
    translated_book = apply_translations_to_book(
        original_book=book,
        translated_results=translated_results,
        logger=logger
    )
    
    # 更新书籍元数据
    if translated_book.metadata.title_source:
         title_map = {"zh-CN": "【中文翻譯】", "ja": "【日本語訳】"}
         prefix = title_map.get(args.target_lang, f"[{args.target_lang}] ")
         translated_book.metadata.title_target = prefix + translated_book.metadata.title_source
    translated_book.metadata.language_target = args.target_lang
    logger.info("Metadata updated for the new book.")

    # --- 6. 生成新的 EPUB 文件 ---
    source_p = os.path.abspath(source_path)
    dir_name = os.path.dirname(source_p)
    base_name = os.path.basename(source_p)
    file_name, file_ext = os.path.splitext(base_name)
    lang_suffix = args.target_lang.replace('-', '_')
    output_path = os.path.join(dir_name, f"{file_name}_{lang_suffix}{file_ext}")

    logger.info(f"正在將更新後的 Book 物件寫入新的EPUB文件: {output_path}...")
    try:
        book_to_epub(translated_book, output_path)
    except Exception as e:
        logger.error(f"生成新的EPUB文件時發生錯誤: {e}", exc_info=True)
        return
        
    logger.info("\n" + "="*50)
    logger.info("工作流执行成功！")
    logger.info(f"新的EPUB文件已保存至: {output_path}")
    logger.info("="*50)
    print("\n下一步: 请用EPUB阅读器打开生成的文件进行验证。")

# 【修改點 2】修改主程式入口以運行非同步函式
if __name__ == "__main__":
    asyncio.run(main()) 