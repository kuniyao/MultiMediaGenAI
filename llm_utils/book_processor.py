from __future__ import annotations
from typing import List, Dict, TYPE_CHECKING
from bs4 import BeautifulSoup, NavigableString, Tag
import copy

if TYPE_CHECKING:
    from format_converters import book_schema as schema
    from format_converters.book_schema import Row, CellContent


def _convert_rich_content_to_markup(items: List[schema.RichContentItem]) -> str:
    """将RichContentItem列表转换为带简化HTML标记的字符串。"""
    parts = []
    if not items:
        return ""
    for item in items:
        if item.type == 'text':
            # ToDo: 考虑是否需要对内容进行HTML转义
            parts.append(item.content)
        elif item.type in ['bold', 'italic']:
            tag = item.type[0]  # b or i
            parts.append(f"<{tag}>{_convert_rich_content_to_markup(item.content)}</{tag}>")
        elif item.type == 'small':
            parts.append(f"<small>{_convert_rich_content_to_markup(item.content)}</small>")
        elif item.type == 'hyperlink':
            # 只翻译链接的可见文本
            parts.append(_convert_rich_content_to_markup(item.content))
        elif item.type == 'line_break':
            parts.append("<br/>")
        elif item.type == 'note_reference':
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
    from format_converters import book_schema as schema

    for chapter in book.chapters:
        # TODO: 在此处添加逻辑，以根据章节标题或epub_type跳过翻译
        for block in chapter.content:
            block_type = block.type
            
            if block_type == 'heading' and block.content_source:
                tasks.append({
                    "id": block.id,
                    "type": block_type,
                    "text_with_markup": block.content_source.strip()
                })
            elif block_type == 'paragraph' and block.content_rich_source:
                text_with_markup = _convert_rich_content_to_markup(block.content_rich_source)
                if text_with_markup:
                    tasks.append({
                        "id": block.id,
                        "type": block_type,
                        "text_with_markup": text_with_markup.strip()
                    })
            elif block_type == 'list' and block.items_source:
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
            elif block_type == 'table':
                # 表格处理：将每个单元格拆分为一个任务
                for r_idx, row in enumerate(block.content_source.headers):
                    for c_idx, cell in enumerate(row):
                        cell_markup = _convert_rich_content_to_markup(cell)
                        if cell_markup:
                            tasks.append({
                                "id": f"{block.id}::header::{r_idx}::{c_idx}",
                                "type": "table_cell",
                                "text_with_markup": cell_markup.strip()
                            })
                for r_idx, row in enumerate(block.content_source.rows):
                    for c_idx, cell in enumerate(row):
                        cell_markup = _convert_rich_content_to_markup(cell)
                        if cell_markup:
                            tasks.append({
                                "id": f"{block.id}::row::{r_idx}::{c_idx}",
                                "type": "table_cell",
                                "text_with_markup": cell_markup.strip()
                            })
            elif block_type == 'image' and block.content_source:
                tasks.append({
                    "id": block.id,
                    "type": block_type,
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
    from format_converters import book_schema as schema
    
    # 使用 'html.parser' 并将整个标记包裹在 body 中，以获得更一致的解析行为
    soup = BeautifulSoup(f"<body>{markup}</body>", 'html.parser')
    items = []

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
    from format_converters import book_schema as schema
    
    soup = BeautifulSoup(markup, 'html.parser')
    list_items = []

    # 找到最外层的列表标签 (ul 或 ol)
    list_tag = soup.find(['ul', 'ol'])
    if not list_tag:
        return []

    # 遍历所有直接的 li 子节点
    for li in list_tag.find_all('li', recursive=False):
        # 提取 li 中的嵌套列表（如果有的话）
        nested_list_tag = li.find(['ul', 'ol'])
        nested_list_items = None
        if nested_list_tag:
            # 在解析内容前，先将嵌套列表从 li 中移除，避免重复处理
            nested_list_markup = str(nested_list_tag.extract())
            nested_list_items = _rebuild_list_from_markup(nested_list_markup)
            
        # 解析 li 标签内剩余的内容（已排除嵌套列表）
        content_items = _convert_markup_to_rich_content(li.decode_contents())
        
        list_items.append(schema.ListItem(
            content=content_items,
            nested_list=schema.ListBlock(
                id="nested-list", # ID 在此场景下不重要
                ordered=nested_list_tag.name == 'ol' if nested_list_tag else False,
                items_source=nested_list_items or []
            ) if nested_list_items else None
        ))
    return list_items

def _rebuild_table_from_markup(markup: str) -> schema.TableContent:
    """将包含<table>标记的字符串解析回 TableContent 对象。"""
    from format_converters import book_schema as schema

    soup = BeautifulSoup(markup, 'html.parser')
    headers: List[Row] = []
    rows: List[Row] = []

    # 解析表头
    thead = soup.find('thead')
    if thead:
        header_row = thead.find('tr')
        if header_row:
            header_cells: CellContent = []
            for th in header_row.find_all('th'):
                header_cells.append(_convert_markup_to_rich_content(th.decode_contents()))
            headers.append(header_cells)
    
    # 解析表体
    tbody = soup.find('tbody')
    if tbody:
        for tr in tbody.find_all('tr'):
            row_cells: CellContent = []
            for td in tr.find_all('td'):
                row_cells.append(_convert_markup_to_rich_content(td.decode_contents()))
            rows.append(row_cells)
            
    return schema.TableContent(headers=headers[0] if headers else [], rows=rows)

def update_book_with_translations(book: schema.Book, translated_blocks: List[Dict]):
    """
    根据翻译结果更新 Book 对象中的 `*_target` 字段。
    此函数能处理复合ID，将翻译结果精确写回到列表项或表格单元格。
    """
    # 延迟导入以避免循环依赖
    from format_converters import book_schema as schema

    # 1. 创建一个从 ID到块对象的快速查找映射
    block_map = {block.id: block for chapter in book.chapters for block in chapter.content}

    # 2. 遍历翻译后的块
    for item in translated_blocks:
        composite_id = item.get("id")
        translated_markup = item.get("text_with_markup")

        if not composite_id or translated_markup is None:
            continue

        # 解析复合ID
        id_parts = composite_id.split('::')
        block_id = id_parts[0]

        target_block = block_map.get(block_id)
        if not target_block:
            print(f"警告: 在Book对象中未找到ID为 '{block_id}' 的块，跳过更新。")
            continue
        
        # 3. 根据ID结构和块类型，调用相应的更新逻辑
        if len(id_parts) == 1:
            # --- 处理简单块 (非列表、非表格) ---
            block_type = target_block.type
            if block_type == 'heading':
                target_block.content_target = translated_markup
            elif block_type == 'image':
                target_block.content_target = translated_markup
            elif block_type == 'paragraph':
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
                    target_block.content_target = copy.deepcopy(target_block.content_source)
                    # 清空内容，准备填充翻译
                    for r in target_block.content_target.headers:
                        for c_idx in range(len(r)): r[c_idx] = []
                    for r in target_block.content_target.rows:
                        for c_idx in range(len(r)): r[c_idx] = []

                if id_parts[1] == 'header':
                    target_block.content_target.headers[row_index][col_index] = _convert_markup_to_rich_content(translated_markup)
                else: # row
                    target_block.content_target.rows[row_index][col_index] = _convert_markup_to_rich_content(translated_markup)

            except (ValueError, IndexError):
                print(f"警告: 无法解析表格单元格的复合ID '{composite_id}'")

        # 更新块的翻译状态
        if target_block:
            target_block.status = "translated" 