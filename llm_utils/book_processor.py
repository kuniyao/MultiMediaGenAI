from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from format_converters import html_mapper
from format_converters.book_schema import Chapter, Book, AnyBlock
from typing import List, Dict


def chapter_content_to_html(chapter: Chapter) -> str:
    """
    【第一步核心函数】将单个Chapter对象的内容转换回其HTML内容的字符串。
    """
    # 创建一个临时的BeautifulSoup对象来构建HTML
    soup = BeautifulSoup('<body></body>', 'html.parser')
    body = soup.body

    for block in chapter.content:
        # 直接调用我们解耦出来的、可重用的HTML映射函数
        html_element = html_mapper.map_block_to_html(block, soup)
        if html_element:
            body.append(html_element)
    
    # 使用prettify()可以获得格式更美观的HTML，方便调试
    return body.prettify(formatter="html5")


def extract_translatable_chapters(book: Book, logger=None) -> list:
    """
    从Book对象中提取所有可翻译的章节，并将其内容序列化为HTML，
    最终生成一个以章节为单位的翻译任务列表。
    """
    if logger:
        logger.info("开始提取可翻译章节...")
    translatable_chapters = []
    
    for i, chapter in enumerate(book.chapters):
        # 我们可以加入一些过滤逻辑，跳过不想翻译的章节
        if chapter.epub_type and any(t in chapter.epub_type for t in ['toc', 'cover', 'titlepage', 'copyright']):
            if logger:
                logger.info(f"跳过章节 {i} (ID: {chapter.id}, Title: {chapter.title})，因为其类型为: {chapter.epub_type}")
            continue

        if not chapter.content:
            if logger:
                logger.info(f"跳过章节 {i} (ID: {chapter.id}, Title: {chapter.title})，因为该章节没有内容。")
            continue

        # 调用我们第一步实现的序列化函数
        html_content = chapter_content_to_html(chapter)
        
        if not html_content.strip():
            if logger:
                logger.info(f"跳过章节 {i} (ID: {chapter.id}, Title: {chapter.title})，因为序列化后的HTML内容为空。")
            continue
            
        if logger:
            logger.debug(f"成功序列化章节 {i} (ID: {chapter.id}) 为HTML。")
        # 创建一个任务字典
        chapter_task = {
            "id": f"chapter::{chapter.id}",
            "text_to_translate": html_content,
            "source_data": chapter,  # 直接传递 Chapter 对象的引用
        }
        translatable_chapters.append(chapter_task)

    if logger:
        logger.info(f"从 {len(book.chapters)} 个总章节中提取了 {len(translatable_chapters)} 个可翻译章节。")

    return translatable_chapters


def update_book_with_translated_html(book: Book, translated_results: List[Dict], logger):
    """
    【核心】更新器：使用翻译后的HTML结果来更新Book对象。
    """
    logger.info("开始将翻译结果写回Book对象...")
    
    # 创建一个从章节ID到翻译后HTML的映射，方便查找
    translation_map = {item['llm_processing_id']: item['translated_text'] for item in translated_results}

    # 遍历book中的所有章节
    for chapter in book.chapters:
        chapter_id_key = f"chapter::{chapter.id}"
        
        # 检查这个章节是否在我们的翻译结果里
        if chapter_id_key in translation_map:
            logger.info(f"正在更新章节: {chapter.id}")
            translated_html = translation_map[chapter_id_key]

            # 检查翻译是否失败，如果失败则跳过更新
            if "[TRANSLATION_FAILED]" in translated_html:
                logger.warning(f"章节 {chapter.id} 的翻译失败，跳过内容更新。")
                continue
            
            # 1. 反序列化：将翻译后的HTML重新解析为Block对象列表
            new_blocks = html_mapper.html_to_blocks(translated_html, book.image_resources, logger)
            
            # 2. 更新：直接替换掉章节的content
            chapter.content = new_blocks
            
            # 3. 尝试从翻译后的HTML中更新章节标题
            soup = BeautifulSoup(translated_html, 'html.parser')
            h_tags = soup.find(['h1', 'h2', 'h3', 'h4'])
            if h_tags and h_tags.text:
                new_title = h_tags.text.strip()
                logger.info(f"  - 从H标签中提取到新标题: '{new_title}'")
                chapter.title = new_title
                chapter.title_target = new_title # 同时更新目标标题字段
    
    logger.info("Book对象更新完成。")