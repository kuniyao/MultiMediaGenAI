import sys
import os
import argparse
import logging
from tqdm import tqdm

# 将项目根目录添加到Python路径
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from format_converters.epub_parser import epub_to_book
from format_converters.epub_writer import book_to_epub
from llm_utils.book_processor import extract_translatable_blocks, update_book_with_translations
from llm_utils.translator import execute_translation # 使用封装好的高级函数

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """
    执行EPUB真实翻译端到端工作流的主函数。
    """
    parser = argparse.ArgumentParser(description="使用LLM翻译EPUB文件，并生成一个新的EPUB。")
    parser.add_argument("epub_path", type=str, help="要翻译的源EPUB文件的路径。")
    parser.add_argument("--target_lang", type=str, default="zh-CN", help="翻译的目标语言 (例如, zh-CN, ja, ko)。")
    args = parser.parse_args()

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

    # --- 2. 提取可翻译内容 ---
    logger.info("正在提取可翻译内容...")
    translatable_blocks = extract_translatable_blocks(book)
    if not translatable_blocks:
        logger.info("在此EPUB中未找到可翻译的内容。工作流终止。")
        return
    logger.info(f"提取了 {len(translatable_blocks)} 个可翻译的块。")

    # --- 3. 准备翻译任务 ---
    # 将我们的块格式转换为 `execute_translation` 期望的格式。
    # `llm_processing_id` 必须是唯一的，我们用 `id`。
    # `text_to_translate` 是要翻译的内容。
    # `source_data` 是原始块，以便之后能恢复所有信息。
    tasks_for_translator = [
        {
            "llm_processing_id": block["id"],
            "text_to_translate": block["text_with_markup"],
            "source_data": block
        }
        for block in translatable_blocks
    ]
    logger.info("已将块转换为翻译器所需的任务格式。")

    # --- 4. 执行翻译 ---
    # `execute_translation` 函数在内部处理批处理、Prompt构建和API调用。
    logger.info("正在调用高级翻译函数...")
    # 注意: source_lang_code 可以从 book.metadata.language_source 获取
    source_lang = book.metadata.language_source if book.metadata.language_source else "en"
    
    # 获取输出目录以保存原始LLM响应日志
    output_dir = os.path.dirname(os.path.abspath(source_path))

    translated_results = execute_translation(
        pre_translate_json_list=tasks_for_translator,
        source_lang_code=source_lang,
        target_lang=args.target_lang,
        video_specific_output_path=output_dir, # 用于保存日志
        logger=logger
    )

    if not translated_results:
        logger.error("翻译过程失败或未返回任何结果。工作流终止。")
        return

    logger.info(f"成功从翻译器接收到 {len(translated_results)} 个结果。")

    # --- 5. 格式化结果并更新 Book 对象 ---
    # 将翻译结果转换回 `update_book_with_translations` 期望的格式。
    update_payload = []
    for result in translated_results:
        original_block = result["source_data"]
        original_block["text_with_markup"] = result.get("translated_text", "")
        update_payload.append(original_block)

    logger.info("正在用翻译结果更新Book对象...")
    update_book_with_translations(book, update_payload)
    
    # 更新书籍元数据
    # 构建一个简单的目标标题
    if book.metadata.title_source:
         title_map = {"zh-CN": "【中文翻译】", "ja": "【日本語訳】"}
         prefix = title_map.get(args.target_lang, f"[{args.target_lang}] ")
         book.metadata.title_target = prefix + book.metadata.title_source
    book.metadata.language_target = args.target_lang
    logger.info("更新完成。")

    # --- 6. 生成新的 EPUB 文件 ---
    # 构建输出文件名
    source_p = os.path.abspath(source_path)
    dir_name = os.path.dirname(source_p)
    base_name = os.path.basename(source_p)
    file_name, file_ext = os.path.splitext(base_name)
    lang_suffix = args.target_lang.replace('-', '_')
    output_path = os.path.join(dir_name, f"{file_name}_{lang_suffix}{file_ext}")

    logger.info(f"正在将更新后的 Book 对象写入新的EPUB文件: {output_path}...")
    try:
        book_to_epub(book, output_path)
    except Exception as e:
        logger.error(f"生成新的EPUB文件时发生错误: {e}", exc_info=True)
        return
        
    logger.info("\n" + "="*50)
    logger.info("工作流执行成功！")
    logger.info(f"新的EPUB文件已保存至: {output_path}")
    logger.info("="*50)
    print("\n下一步: 请用EPUB阅读器打开生成的文件进行验证。")

if __name__ == "__main__":
    main() 