from __future__ import annotations
from typing import List, Dict, TYPE_CHECKING, cast
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag
import copy

from format_converters import book_schema as schema

if TYPE_CHECKING:
    from format_converters.book_schema import Row, CellContent, AnyBlock


def _convert_rich_content_to_markup(items: List[schema.RichContentItem]) -> str:
    """将RichContentItem列表转换为带简化HTML标记的字符串。"""
    parts = []
    if not items:
        return ""
    for item in items:
        # 使用 isinstance 进行类型收窄，确保类型安全
        if isinstance(item, schema.TextItem):
            # ToDo: 考虑是否需要对内容进行HTML转义
            parts.append(item.content)
        elif isinstance(item, (schema.BoldItem, schema.ItalicItem)):
            tag = item.type[0]  # b or i
            parts.append(f"<{tag}>{_convert_rich_content_to_markup(item.content)}</{tag}>")
        elif isinstance(item, schema.SmallItem):
            parts.append(f"<small>{_convert_rich_content_to_markup(item.content)}</small>")
        elif isinstance(item, schema.HyperlinkItem):
            # 只翻译链接的可见文本
            parts.append(_convert_rich_content_to_markup(item.content))
        elif isinstance(item, schema.LineBreakItem):
            parts.append("<br/>")
        elif isinstance(item, schema.NoteReferenceItem):
            # 脚注引用标记，如 "[1]"，应保持原样
            parts.append(item.marker)
    return "".join(parts)

def _convert_list_block_to_markup(block: schema.ListBlock) -> str:
    """将ListBlock对象（包括嵌套列表）转换为带<ul>/<ol>和<li>标记的字符串。"""
    if not block.items_source:
        return ""
    
    items_markup = []
    for item in block.items_source:
        item_content_markup = _convert_rich_content_to_markup(item.content)
        
        nested_list_markup = ""
        if item.nested_list:
            nested_list_markup = _convert_list_block_to_markup(item.nested_list)
            
        items_markup.append(f"<li>{item_content_markup}{nested_list_markup}</li>")

    list_content = "".join(items_markup)
    tag = "ol" if block.ordered else "ul"
    return f"<{tag}>{list_content}</{tag}>"

def _convert_table_block_to_markup(block: schema.TableBlock) -> str:
    """将TableBlock对象转换为带<table>, <tr>, <th>, <td>标记的字符串。"""
    content = block.content_source
    if not content.headers and not content.rows:
        return ""
        
    header_markup = ""
    if content.headers:
        header_cells = []
        for cell_content in content.headers:
             header_cells.append(f"<th>{_convert_rich_content_to_markup(cell_content)}</th>")
        header_markup = f"<thead><tr>{''.join(header_cells)}</tr></thead>"

    rows_markup = []
    if content.rows:
        for row in content.rows:
            row_cells = []
            for cell_content in row:
                row_cells.append(f"<td>{_convert_rich_content_to_markup(cell_content)}</td>")
            rows_markup.append(f"<tr>{''.join(row_cells)}</tr>")
    
    body_markup = f"<tbody>{''.join(rows_markup)}</tbody>" if rows_markup else ""

    return f"<table>{header_markup}{body_markup}</table>"


def extract_translatable_blocks(book: schema.Book) -> List[Dict]:
    """
    从Book对象中提取所有可翻译的文本块，并将其转换为一个扁平的任务列表。

    对于列表块(ListBlock)，此函数会将其拆分为多个任务，每个列表项(ListItem)
    对应一个独立的翻译任务，并使用复合ID进行标识。
    """
    tasks = []
    # 延迟导入以避免循环依赖

    for chapter in book.chapters:
        # 为章节标题创建翻译任务
        if chapter.title and chapter.title.strip():
            tasks.append({
                "id": f"chapter::{chapter.id}::title",
                "type": "heading", # 将标题视为一种特殊的标题块
                "text_with_markup": chapter.title.strip()
            })

        # TODO: 在此处添加逻辑，以根据章节标题或epub_type跳过翻译
        for block in chapter.content:
            # 使用 isinstance 进行类型收窄，确保安全地访问属性
            if isinstance(block, schema.HeadingBlock) and block.content_source:
                tasks.append({
                    "id": block.id,
                    "type": block.type,
                    "text_with_markup": block.content_source.strip()
                })
            elif isinstance(block, schema.ParagraphBlock) and block.content_rich_source:
                text_with_markup = _convert_rich_content_to_markup(block.content_rich_source)
                if text_with_markup:
                    tasks.append({
                        "id": block.id,
                        "type": block.type,
                        "text_with_markup": text_with_markup.strip()
                    })
            elif isinstance(block, schema.ListBlock) and block.items_source:
                # 拆分列表块：为每个列表项创建一个独立的翻译任务
                for i, item in enumerate(block.items_source):
                    # 处理当前列表项的内容
                    item_markup = _convert_rich_content_to_markup(item.content)
                    if item_markup:
                        tasks.append({
                            # 使用复合ID来唯一标识这个列表项
                            "id": f"{block.id}::item::{i}",
                            "type": "list_item", # 使用特定类型来标识
                            "text_with_markup": item_markup.strip()
                        })
                    
                    # 递归处理嵌套列表
                    if item.nested_list:
                        # 嵌套列表也被视为一个独立的块进行处理
                        nested_list_markup = _convert_list_block_to_markup(item.nested_list)
                        if nested_list_markup:
                            # 注意：这里的处理方式可能需要根据嵌套列表的翻译策略进一步细化
                            # 目前我们暂时不将嵌套列表作为独立的可翻译单元，因为它已被其父列表的逻辑包含
                            # 如果需要对嵌套列表本身进行操作，需要设计更复杂的ID和写回机制
                            pass
            elif isinstance(block, schema.TableBlock):
                # 表格处理：将每个单元格拆分为一个任务
                # 修正表头处理逻辑
                if block.content_source.headers:
                    for c_idx, cell in enumerate(block.content_source.headers):
                        cell_markup = _convert_rich_content_to_markup(cell)
                        if cell_markup:
                            tasks.append({
                                "id": f"{block.id}::header::{0}::{c_idx}", # 假设只有一个表头行
                                "type": "table_cell",
                                "text_with_markup": cell_markup.strip()
                            })
                if block.content_source.rows:
                    for r_idx, row in enumerate(block.content_source.rows):
                        for c_idx, cell in enumerate(row):
                            cell_markup = _convert_rich_content_to_markup(cell)
                            if cell_markup:
                                tasks.append({
                                    "id": f"{block.id}::row::{r_idx}::{c_idx}",
                                    "type": "table_cell",
                                    "text_with_markup": cell_markup.strip()
                                })
            elif isinstance(block, schema.ImageBlock) and block.content_source:
                tasks.append({
                    "id": block.id,
                    "type": block.type,
                    "text_with_markup": block.content_source.strip()
                })

    return tasks

# ==============================================================================
# 阶段二: 内容更新模块
# ==============================================================================

def _convert_markup_to_rich_content(markup: str) -> List[schema.RichContentItem]:
    """
    将包含简化HTML标记的字符串，解析回 RichContentItem 对象列表。
    这是 _convert_rich_content_to_markup 的逆向操作。
    """
    # 延迟导入以避免循环依赖
    
    # 使用 'html.parser' 并将整个标记包裹在 body 中，以获得更一致的解析行为
    soup = BeautifulSoup(f"<body>{markup}</body>", 'html.parser')
    items = []
    
    # soup.body 可能为 None，进行检查
    if not soup.body:
        return items

    # 遍历 body 标签下的所有直接子节点
    for element in soup.body.children:
        if isinstance(element, NavigableString):
            # 如果是纯文本节点
            text = str(element)
            if text.strip(): # 避免添加只包含空格的文本节点
                items.append(schema.TextItem(content=text))
        
        elif isinstance(element, Tag):
            # 如果是HTML标签
            tag_name = element.name
            # 递归地处理标签内的内容
            inner_content = element.decode_contents()
            inner_items = _convert_markup_to_rich_content(inner_content)
            
            if tag_name in ['b', 'strong']:
                items.append(schema.BoldItem(content=inner_items))
            elif tag_name in ['i', 'em']:
                items.append(schema.ItalicItem(content=inner_items))
            elif tag_name == 'small':
                items.append(schema.SmallItem(content=inner_items))
            elif tag_name == 'br':
                items.append(schema.LineBreakItem())
            # Hyperlink 和 NoteReference 的反向转换比较复杂，暂时只处理内容
            else:
                # 对于无法识别的标签，只保留其文本内容，避免格式丢失
                items.extend(inner_items)
                
    return items

def _rebuild_list_from_markup(markup: str) -> List[schema.ListItem]:
    """将包含<ul>/<ol>和<li>标记的字符串解析回 ListItem 对象列表。"""
    
    soup = BeautifulSoup(markup, 'html.parser')
    list_items = []

    # 找到最外层的列表标签 (ul 或 ol)
    list_tag = soup.find(['ul', 'ol'])
    if not isinstance(list_tag, Tag):
        return []

    # 遍历所有直接的 li 子节点
    for li_element in list_tag.find_all('li', recursive=False):
        if not isinstance(li_element, Tag):
            continue
        
        # 提取 li 中的嵌套列表（如果有的话）
        nested_list_tag = li_element.find(['ul', 'ol'])
        nested_list_items = None
        if isinstance(nested_list_tag, Tag):
            # 在解析内容前，先将嵌套列表从 li 中移除，避免重复处理
            nested_list_markup = str(nested_list_tag.extract())
            nested_list_items = _rebuild_list_from_markup(nested_list_markup)
            
        # 解析 li 标签内剩余的内容（已排除嵌套列表）
        content_items = _convert_markup_to_rich_content(li_element.decode_contents())
        
        list_items.append(schema.ListItem(
            content=content_items,
            nested_list=schema.ListBlock(
                id="nested-list", # ID 在此场景下不重要
                ordered=nested_list_tag.name == 'ol' if isinstance(nested_list_tag, Tag) else False,
                items_source=nested_list_items or []
            ) if nested_list_items else None
        ))
    return list_items

def _rebuild_table_from_markup(markup: str) -> schema.TableContent:
    """将包含<table>标记的字符串解析回 TableContent 对象。"""

    soup = BeautifulSoup(markup, 'html.parser')
    headers: List[Row] = []
    rows: List[Row] = []

    # 解析表头
    thead = soup.find('thead')
    if isinstance(thead, Tag):
        header_row_tag = thead.find('tr')
        if isinstance(header_row_tag, Tag):
            header_cells: Row = [] # A Row is a List[CellContent]
            for th in header_row_tag.find_all('th'):
                if isinstance(th, Tag):
                    header_cells.append(_convert_markup_to_rich_content(th.decode_contents()))
            if header_cells:
                 headers.append(header_cells)
    
    # 解析表体
    tbody = soup.find('tbody')
    if isinstance(tbody, Tag):
        for tr in tbody.find_all('tr'):
            if not isinstance(tr, Tag): continue
            row_cells: Row = [] # A Row is List[CellContent]
            for td in tr.find_all('td'):
                if isinstance(td, Tag):
                    row_cells.append(_convert_markup_to_rich_content(td.decode_contents()))
            rows.append(row_cells)
            
    # 根据 TableContent 定义，headers 是 Row (List[CellContent])，而不是 List[Row]
    # 因此我们只取第一个（也是唯一一个）header row
    final_headers: Row = headers[0] if headers else []
    return schema.TableContent(headers=final_headers, rows=rows)

def update_book_with_translations(book: schema.Book, translated_blocks: List[Dict]):
    """
    根据翻译结果更新 Book 对象中的 `*_target` 字段。
    此函数能处理复合ID，将翻译结果精确写回到列表项或表格单元格。
    """
    # 延迟导入以避免循环依赖

    # 1. 创建一个从 ID到块对象和章节对象的快速查找映射
    block_map = {block.id: block for chapter in book.chapters for block in chapter.content}
    chapter_map = {chapter.id: chapter for chapter in book.chapters}

    # 2. 遍历翻译后的块
    for item in translated_blocks:
        composite_id = item.get("id")
        translated_markup = item.get("text_with_markup")

        if not composite_id or translated_markup is None:
            continue

        # 解析复合ID
        id_parts = composite_id.split('::')

        # --- 处理章节标题 ---
        if len(id_parts) == 3 and id_parts[0] == 'chapter' and id_parts[2] == 'title':
            chapter_id = id_parts[1]
            target_chapter = chapter_map.get(chapter_id)
            if target_chapter:
                target_chapter.title_target = translated_markup
            else:
                print(f"警告: 在Book对象中未找到ID为 '{chapter_id}' 的章节，无法更新标题。")
            continue # 处理完标题后继续下一个
        
        block_id = id_parts[0]

        target_block = block_map.get(block_id)
        if not target_block:
            print(f"警告: 在Book对象中未找到ID为 '{block_id}' 的块，跳过更新。")
            continue
        
        # 3. 根据ID结构和块类型，调用相应的更新逻辑
        # 使用 isinstance 进行类型收窄
        if len(id_parts) == 1:
            # --- 处理简单块 (非列表、非表格) ---
            if isinstance(target_block, schema.HeadingBlock):
                target_block.content_target = translated_markup
            elif isinstance(target_block, schema.ImageBlock):
                target_block.content_target = translated_markup
            elif isinstance(target_block, schema.ParagraphBlock):
                target_block.content_rich_target = _convert_markup_to_rich_content(translated_markup)
        
        elif id_parts[1] == 'item' and isinstance(target_block, schema.ListBlock):
            # --- 处理列表项 ---
            try:
                item_index = int(id_parts[2])
                # 确保目标列表有足够多的项
                if not target_block.items_target:
                    # 如果目标列表为空，用源列表的结构进行初始化
                    target_block.items_target = [
                        schema.ListItem(content=[], nested_list=copy.deepcopy(src.nested_list)) 
                        for src in target_block.items_source
                    ]
                
                if 0 <= item_index < len(target_block.items_target):
                    target_block.items_target[item_index].content = _convert_markup_to_rich_content(translated_markup)
                else:
                    print(f"警告: 列表项索引 {item_index} 超出范围 (块ID: {block_id})")
            except (ValueError, IndexError):
                print(f"警告: 无法解析列表项的复合ID '{composite_id}'")

        elif id_parts[1] in ['header', 'row'] and isinstance(target_block, schema.TableBlock):
            # --- 处理表格单元格 ---
            try:
                row_index = int(id_parts[2])
                col_index = int(id_parts[3])
                
                # 确保目标表格有结构
                if not target_block.content_target or (not target_block.content_target.headers and not target_block.content_target.rows):
                    # 深拷贝并清空内容
                    target_block.content_target = copy.deepcopy(target_block.content_source)
                    if target_block.content_target:
                        # Create empty shells matching the source structure
                        target_block.content_target.headers = [[] for _ in target_block.content_target.headers]
                        target_block.content_target.rows = [[[] for _ in cell_row] for cell_row in target_block.content_target.rows]

                if id_parts[1] == 'header' and target_block.content_target:
                    target_block.content_target.headers[col_index] = _convert_markup_to_rich_content(translated_markup)
                elif target_block.content_target: # row
                    target_block.content_target.rows[row_index][col_index] = _convert_markup_to_rich_content(translated_markup)

            except (ValueError, IndexError):
                print(f"警告: 无法解析表格单元格的复合ID '{composite_id}'")

        # 更新块的翻译状态
        if target_block:
            target_block.status = "translated" 