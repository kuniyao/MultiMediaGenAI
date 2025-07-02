from __future__ import annotations
import pathlib
import uuid
from typing import Dict, List, Optional, Union
from bs4 import BeautifulSoup, Tag

from .book_schema import (
    AnyBlock, HeadingBlock, ParagraphBlock,
    ImageBlock, ListBlock, TableBlock, CodeBlock, MarkerBlock,
    NoteContentBlock, RichContentItem, TextItem, BoldItem, ItalicItem,
    HyperlinkItem, LineBreakItem, NoteReferenceItem, ListItem, TableContent,
    CellContent, Row, CodeLine, SmallItem, CodeContentItem, ImageResource
)


# --- Functions from EpubWriter ---

def map_block_to_html(block: AnyBlock, soup: BeautifulSoup) -> Optional[Tag]:
    """将一个AnyBlock对象转换为BeautifulSoup的Tag对象。作为分发器。"""
    if isinstance(block, HeadingBlock):
        return map_heading_to_html(block, soup)
    elif isinstance(block, ParagraphBlock):
        return map_paragraph_to_html(block, soup)
    elif isinstance(block, ImageBlock):
        return map_image_to_html(block, soup)
    elif isinstance(block, ListBlock):
        return map_list_to_html(block, soup)
    elif isinstance(block, TableBlock):
        return map_table_to_html(block, soup)
    elif isinstance(block, CodeBlock):
        return map_code_block_to_html(block, soup)
    elif isinstance(block, MarkerBlock):
        return map_marker_to_html(block, soup)
    elif isinstance(block, NoteContentBlock):
        return map_note_content_to_html(block, soup)
    return None

def add_custom_attributes(tag: Tag, block: AnyBlock):
    """将block中的css_classes和mmg_id添加到tag中。"""
    if hasattr(block, 'css_classes') and block.css_classes:
        tag['class'] = " ".join(block.css_classes)
    if hasattr(block, 'mmg_id') and block.mmg_id:
        tag['data-mmg-id'] = block.mmg_id

def map_heading_to_html(block: HeadingBlock, soup: BeautifulSoup) -> Tag:
    """将 HeadingBlock 转换为 <h1>, <h2> ... 标签。"""
    tag = soup.new_tag(f"h{block.level}")
    tag.string = block.content_target if block.content_target else block.content_source
    add_custom_attributes(tag, block)  # <--- 【修改】调用新函数
    return tag

def map_paragraph_to_html(block: ParagraphBlock, soup: BeautifulSoup) -> Tag:
    """将 ParagraphBlock 转换为 <p> 标签，并处理其内部的富文本。"""
    p_tag = soup.new_tag("p")
    add_custom_attributes(p_tag, block)
    content_to_map = block.content_rich_target if block.content_rich_target else block.content_rich_source
    map_rich_content_to_html(p_tag, content_to_map, soup)
    return p_tag

def map_image_to_html(block: ImageBlock, soup: BeautifulSoup) -> Tag:
    """将 ImageBlock 转换为 <img> 标签，可能包含在一个容器内。"""
    file_name = pathlib.Path(block.path).name
    relative_path = f"../images/{file_name}"
    alt_text = block.content_target if block.content_target else block.content_source
    img_tag = soup.new_tag("img", src=relative_path, alt=alt_text)
    if block.img_css_classes:
        img_tag['class'] = " ".join(block.img_css_classes)
    if block.container_tag:
        container_tag = soup.new_tag(block.container_tag)
        add_custom_attributes(container_tag, block)
        container_tag.append(img_tag)
        return container_tag
    else:
        add_custom_attributes(img_tag, block)
        return img_tag

# format_converters/html_mapper.py (修改后版本)

def map_list_to_html(block: ListBlock, soup: BeautifulSoup) -> Tag:
    """将 ListBlock 转换为 <ul> 或 <ol> 标签，并递归处理其项目。"""
    list_tag_name = "ol" if block.ordered else "ul"
    list_tag = soup.new_tag(list_tag_name)
    items_to_map = block.items_target if block.items_target else block.items_source
    
    # =======================================================================
    # 【改动 1: 注入 data-mmg-id】
    # 这是本次修改的核心目标。我们检查 block 对象上是否存在 mmg_id 字段，
    # 如果存在，就将其作为 data-mmg-id 属性写入到 <ul> 或 <ol> 标签中。
    # =======================================================================
    if hasattr(block, 'mmg_id') and block.mmg_id:
        list_tag['data-mmg-id'] = block.mmg_id

    # =======================================================================
    # 【改动 2: 更安全地处理 CSS Class】
    # 这部分逻辑与原始版本的目标一致，但写法更安全、更清晰。
    # =======================================================================
    is_pseudo_list = False
    
    # 步骤 2.1: 先复制一份 class 列表，而不是直接操作原始列表。
    # 这是一个好的编程习惯，可以防止我们无意中修改了原始 block 对象的状态。
    final_classes = block.css_classes.copy() if block.css_classes else []
    
    # 步骤 2.2: 检查并移除特殊标记。
    # 如果找到了 'pseudo-list-marker'，就从我们复制的列表中移除它。
    if 'pseudo-list-marker' in final_classes:
        is_pseudo_list = True
        final_classes.remove('pseudo-list-marker')
    
    # 步骤 2.3: 如果列表里还有其他 class，就将它们写入标签。
    if final_classes:
        list_tag['class'] = " ".join(final_classes)
        
    # =======================================================================
    # 【无改动部分】
    # 下面的循环逻辑与原始版本完全相同，负责创建 <li> 标签并填充内容。
    # =======================================================================
    for item in items_to_map:
        li_tag = soup.new_tag("li")
        map_rich_content_to_html(li_tag, item.content, soup)
        if item.nested_list:
            nested_list_tag = map_list_to_html(item.nested_list, soup)
            if nested_list_tag:
                li_tag.append(nested_list_tag)
        if is_pseudo_list:
            li_tag['class'] = 'pseudo-list-item'
        list_tag.append(li_tag)
        
    return list_tag

def map_table_to_html(block: TableBlock, soup: BeautifulSoup) -> Tag:
    """将 TableBlock 转换为 <table> 标签。"""
    table_tag = soup.new_tag("table")
    add_custom_attributes(table_tag, block)
    content_to_map = block.content_target if (block.content_target and (block.content_target.headers or block.content_target.rows)) else block.content_source
    if content_to_map.headers:
        thead = soup.new_tag("thead")
        tr = soup.new_tag("tr")
        for cell_content in content_to_map.headers:
            th = soup.new_tag("th")
            map_rich_content_to_html(th, cell_content, soup)
            tr.append(th)
        thead.append(tr)
        table_tag.append(thead)
    if content_to_map.rows:
        tbody = soup.new_tag("tbody")
        for row_data in content_to_map.rows:
            tr = soup.new_tag("tr")
            for cell_content in row_data:
                td = soup.new_tag("td")
                map_rich_content_to_html(td, cell_content, soup)
                tr.append(td)
            tbody.append(tr)
        table_tag.append(tbody)
    return table_tag

def map_code_block_to_html(block: CodeBlock, soup: BeautifulSoup) -> Tag:
    """将 CodeBlock 转换为 <pre><code>...</code></pre> 结构。"""
    pre_tag = soup.new_tag("pre")
    add_custom_attributes(pre_tag, block)
    code_tag = soup.new_tag("code")
    if block.language:
        code_tag['class'] = f"language-{block.language}"
    content_to_map = block.content_structured_target if block.content_structured_target else block.content_structured_source
    for line in content_to_map:
        if line.type == "code":
            code_tag.append(line.value)
            code_tag.append(soup.new_tag("br"))
        elif line.type == "comment":
            comment_span = soup.new_tag("span", attrs={"class": "comment"})
            comment_span.string = line.value
            code_tag.append(comment_span)
            code_tag.append(soup.new_tag("br"))
    return pre_tag

def map_marker_to_html(block: MarkerBlock, soup: BeautifulSoup) -> Optional[Tag]:
    """将 MarkerBlock 转换为对应的HTML标记，如 <hr/>。"""
    if block.role == "doc-pagebreak":
        hr_tag = soup.new_tag("hr")
        if block.title:
            hr_tag['title'] = block.title
        add_custom_attributes(hr_tag, block)
        return hr_tag
    return None

def map_note_content_to_html(block: NoteContentBlock, soup: BeautifulSoup) -> Tag:
    """将脚注/尾注内容块转换为HTML。"""
    note_div = soup.new_tag("div")
    add_custom_attributes(note_div, block)
    note_div['id'] = block.id
    content_to_map = block.content_target if block.content_target else block.content_source
    for inner_block in content_to_map:
        html_element = map_block_to_html(inner_block, soup)
        if html_element:
            note_div.append(html_element)
    return note_div

def map_rich_content_to_html(parent_tag: Tag, rich_content: List[RichContentItem], soup: BeautifulSoup):
    """将 RichContentItem 列表转换为HTML并追加到父标签中。"""
    for item in rich_content:
        if isinstance(item, TextItem):
            parent_tag.append(item.content)
        elif isinstance(item, BoldItem):
            b_tag = soup.new_tag("b")
            map_rich_content_to_html(b_tag, item.content, soup)
            parent_tag.append(b_tag)
        elif isinstance(item, ItalicItem):
            i_tag = soup.new_tag("i")
            map_rich_content_to_html(i_tag, item.content, soup)
            parent_tag.append(i_tag)
        elif isinstance(item, HyperlinkItem):
            a_tag = soup.new_tag("a", href=item.href)
            if item.title:
                a_tag['title'] = item.title
            map_rich_content_to_html(a_tag, item.content, soup)
            parent_tag.append(a_tag)
        elif isinstance(item, LineBreakItem):
            br_tag = soup.new_tag("br")
            parent_tag.append(br_tag)
        elif isinstance(item, NoteReferenceItem):
            a_tag = soup.new_tag("a", href=f"#{item.note_id}")
            a_tag['epub:type'] = 'noteref'
            a_tag.string = item.marker
            parent_tag.append(a_tag)
        elif isinstance(item, SmallItem):
            small_tag = soup.new_tag("small")
            map_rich_content_to_html(small_tag, item.content, soup)
            parent_tag.append(small_tag)


# --- Functions from EpubParser ---

def get_css_classes(tag: Tag) -> Optional[List[str]]:
    """从标签中提取CSS类名列表。"""
    classes = tag.get('class')
    if isinstance(classes, list):
        return [str(c) for c in classes]
    if isinstance(classes, str):
        return classes.split()
    return None

def get_mmg_id(tag: Tag) -> Optional[str]:
    """从标签中提取 data-mmg-id 属性。"""
    return tag.get('data-mmg-id')

def generate_id() -> str:
    """生成一个唯一的ID字符串。"""
    return uuid.uuid4().hex

def map_tag_to_block(tag: Tag, chapter_base_dir: pathlib.Path, content_dir: pathlib.Path, image_resources: Dict[str, ImageResource]) -> Optional[Union[AnyBlock, List[AnyBlock]]]:
    """
    将 BeautifulSoup 的 Tag 对象映射到我们定义的块模型。
    返回单个块，块列表（用于解包的div），或在不支持的标签时返回 None。
    """
    tag_name = tag.name
    
    # 优先级 1: 处理图片，无论是独立的 <img> 还是被其他标签包裹的
    if tag_name == 'img':
        return parse_image_block(tag, chapter_base_dir, content_dir, image_resources)
    
    img_tag = tag.find('img')
    if isinstance(img_tag, Tag):
        # 如果一个标签只作为图片的容器（没有其他文本），则将其整体视为一个图片块
        if not any(s.strip() for s in tag.strings if s.strip()):
            block = parse_image_block(img_tag, chapter_base_dir, content_dir, image_resources)
            if block:
                block.container_tag = tag_name
                block.css_classes = get_css_classes(tag)
            return block

    # 优先级 2: 处理其他明确的块级元素
    if tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
        return parse_heading_block(tag)

    if tag_name in ['ul', 'ol']:
        return parse_list_block(tag)

    if tag_name == 'p':
        # 注意：图片的<p>容器已在上面处理，这里可以安全地处理其他类型的<p>
        tag_text = tag.get_text(strip=True)
        children = list(tag.find_all(True, recursive=False))
        if len(children) == 1 and children[0].name in ['span', 'i']:
             child_classes = get_css_classes(children[0])
             if child_classes and 'bullet' in child_classes and not tag_text:
                 # 处理用 <p> 模拟的特殊列表项
                 return ListBlock(
                    id=generate_id(),
                    ordered=False,
                    items_source=[ListItem(content=[TextItem(content=children[0].get_text())])],
                    css_classes=['pseudo-list-generated', 'bullet']
                 )
        # 默认解析为普通段落
        return parse_paragraph_block(tag)
        
    if tag_name == 'table':
        return parse_table_block(tag)
    
    if tag_name == 'pre':
        return parse_code_block(tag)

    if tag_name == 'hr' and 'doc-pagebreak' in (tag.get('class') or []):
        title = tag.get('title')
        return MarkerBlock(
            id=generate_id(),
            role="doc-pagebreak",
            title=str(title) if title else None
        )
    
    return None

def parse_rich_content(tag: Tag) -> List[RichContentItem]:
    """
    将一个标签内的混合内容（文本、<b>、<i>、<a>等）递归解析为 RichContentItem 列表。
    """
    items: List[RichContentItem] = []
    for content in tag.contents:
        if isinstance(content, str):
            if content.strip():
                items.append(TextItem(content=content))
        elif isinstance(content, Tag):
            if content.name in ['b', 'strong']:
                items.append(BoldItem(content=parse_rich_content(content)))
            elif content.name in ['i', 'em']:
                items.append(ItalicItem(content=parse_rich_content(content)))
            elif content.name == 'small':
                items.append(SmallItem(content=parse_rich_content(content)))
            elif content.name == 'a':
                epub_type = content.get('epub:type')
                if epub_type and 'noteref' in str(epub_type):
                    href_attr = content.get('href', '#')
                    note_id = str(href_attr)[1:] if isinstance(href_attr, str) else ""
                    items.append(NoteReferenceItem(
                        marker=content.text,
                        note_id=note_id
                    ))
                else:
                    href = content.get('href', '')
                    title = content.get('title')
                    items.append(HyperlinkItem(
                        href=str(href) if href else '',
                        content=parse_rich_content(content),
                        title=str(title) if title else None
                    ))
            elif content.name == 'br':
                items.append(LineBreakItem())
            else:
                if content.text.strip():
                    items.append(TextItem(content=content.text))
    return items

def get_plain_text(tag: Tag) -> str:
    """获取标签内的纯文本表示。"""
    return tag.get_text(separator=" ", strip=True)

def parse_heading_block(tag: Tag) -> HeadingBlock:
    """解析标题标签 (<h1>, <h2>, etc.)。"""
    return HeadingBlock(
        id=generate_id(),
        mmg_id=get_mmg_id(tag),  # <--- 【新增】
        level=int(tag.name[1]),
        content_source=get_plain_text(tag),
        css_classes=get_css_classes(tag)
    )

def parse_paragraph_block(tag: Tag) -> ParagraphBlock:
    """解析段落标签 (<p>)。"""
    return ParagraphBlock(
        id=generate_id(),
        mmg_id=get_mmg_id(tag),  # <--- 【新增】
        content_rich_source=parse_rich_content(tag),
        content_source=get_plain_text(tag),
        css_classes=get_css_classes(tag)
    )

def parse_image_block(tag: Tag, chapter_base_dir: pathlib.Path, content_dir: pathlib.Path, image_resources: Dict[str, ImageResource]) -> Optional[ImageBlock]:
    """
    解析图片标签 (<img>)。
    此方法现在可以处理由于EPUB打包错误导致的 src 路径不正确的情况。
    它会首先尝试正常解析路径，如果失败，则会回退到在所有图片资源中搜索文件名。
    """
    src = tag.get('src')
    if not isinstance(src, str):
        return None
    final_path = None
    normalized_href = src
    try:
        absolute_path = (chapter_base_dir / src).resolve()
        normalized_href = absolute_path.relative_to(content_dir).as_posix()
        if normalized_href in image_resources:
            final_path = normalized_href
    except Exception:
        pass
    if not final_path:
        filename = pathlib.Path(src).name
        found_paths = [
            href for href in image_resources.keys()
            if href.endswith(f"/{filename}") or href == filename
        ]
        if len(found_paths) == 1:
            final_path = found_paths[0]
            print(f"警告: 图片 '{src}' 的路径不规范。已通过文件名匹配修正为 -> '{final_path}'")
        elif len(found_paths) > 1:
            print(f"警告: 图片 '{src}' 的路径不规范, 且在资源中找到多个同名文件: {found_paths}。将使用原始src。")
            final_path = src
        else:
            print(f"警告: 无法在图片资源中找到 '{src}'。将使用原始src。")
            final_path = src
    final_path_decision = final_path if final_path is not None else normalized_href
    alt_text = tag.get('alt', '')
    return ImageBlock(
        id=generate_id(),
        mmg_id=get_mmg_id(tag.parent if tag.parent and tag.parent.name != '[document]' else tag), # <--- 【新增】ID通常在容器上
        path=final_path_decision,
        content_source=str(alt_text) if alt_text else '',
        img_css_classes=get_css_classes(tag)
    )

def parse_list_block(tag: Tag) -> ListBlock:
    """解析列表标签 (<ul>, <ol>)。"""
    items: List[ListItem] = []
    for li in tag.find_all('li', recursive=False):
        if not isinstance(li, Tag): continue
        nested_list_tag = li.find(['ul', 'ol'])
        nested_list_block = None
        if isinstance(nested_list_tag, Tag):
            nested_list_tag.extract()
            nested_list_block = parse_list_block(nested_list_tag)
        items.append(ListItem(
            content=parse_rich_content(li),
            nested_list=nested_list_block
        ))
    return ListBlock(
        id=generate_id(),
        mmg_id=get_mmg_id(tag),  # <--- 【新增】
        ordered=tag.name == 'ol',
        items_source=items,
        css_classes=get_css_classes(tag)
    )

def parse_table_block(tag: Tag) -> TableBlock:
    """解析表格标签 (<table>)。"""
    def parse_row(tr_tag: Tag) -> Row:
        row_data: Row = []
        for cell_tag in tr_tag.find_all(['th', 'td']):
            if isinstance(cell_tag, Tag):
                cell_content: CellContent = parse_rich_content(cell_tag)
                row_data.append(cell_content)
        return row_data
    headers: List[Row] = []
    rows: List[Row] = []
    thead = tag.find('thead')
    if isinstance(thead, Tag):
        for tr in thead.find_all('tr'):
            if isinstance(tr, Tag):
                headers.append(parse_row(tr))
    tbody = tag.find('tbody')
    if not isinstance(tbody, Tag):
        tbody = tag
    for tr in tbody.find_all('tr'):
        if not isinstance(tr, Tag): continue
        if tr.parent and tr.parent.name == 'thead': continue
        if tr.find_parent('thead'): continue
        rows.append(parse_row(tr))
    if not headers and rows:
        first_tr = tbody.find('tr')
        if isinstance(first_tr, Tag):
            first_row_cells = first_tr.find_all(['th', 'td'])
            first_cell = first_row_cells[0] if first_row_cells else None
            if isinstance(first_cell, Tag) and first_cell.name == 'th':
                headers.append(rows.pop(0))
    final_headers: Row = []
    for header_row in headers:
        final_headers.extend(header_row)
    return TableBlock(
        id=generate_id(),
        content_source=TableContent(headers=final_headers, rows=rows),
        css_classes=get_css_classes(tag),
    )

def parse_code_block(tag: Tag) -> CodeBlock:
    """解析预格式化文本标签 (<pre>)，通常用于代码。"""
    code_tag = tag.find('code')
    target_tag = code_tag if isinstance(code_tag, Tag) else tag
    lang = None
    if isinstance(code_tag, Tag):
        classes = code_tag.get('class')
        if isinstance(classes, list):
            for c in classes:
                if str(c).startswith('language-'):
                    lang = str(c).replace('language-', '')
                    break
    lines = target_tag.get_text().split('\n')
    structured_lines: List[CodeContentItem] = [CodeLine(value=line) for line in lines]
    return CodeBlock(
        id=generate_id(),
        language=lang,
        content_structured_source=structured_lines,
        css_classes=get_css_classes(tag)
    )

def parse_pseudo_list_block(tags: List[Tag]) -> ListBlock:
    """
    将一系列 <p> 标签（例如 <p class="bullet">）转换为一个 ListBlock。
    """
    items = [
        ListItem(content=parse_rich_content(tag)) for tag in tags
    ]
    css_classes = get_css_classes(tags[0]) or []
    css_classes.append('pseudo-list-marker')
    return ListBlock(
        id=generate_id(),
        ordered=False,
        items_source=items,
        css_classes=css_classes
    )

def html_to_blocks(html_content: str, image_resources: dict, logger) -> list[AnyBlock]:
    """
    【核心】反序列化器：将HTML字符串解析回Block对象列表。
    这是 chapter_content_to_html 的逆向操作，并且能够处理图片。
    """
    if not html_content:
        return []

    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        content_to_parse = soup.body if soup.body else soup
        
        blocks = []
        for tag in content_to_parse.children:
            if isinstance(tag, Tag):
                # 调用本文件中已有的`map_tag_to_block`辅助函数并修正参数
                result = map_tag_to_block(tag, pathlib.Path('.'), pathlib.Path('.'), image_resources)
                if result:
                    if isinstance(result, list):
                        blocks.extend(result)
                    else:
                        blocks.append(result)
        return blocks
    except Exception as e:
        logger.error(f"反序列化HTML时发生未知错误: {e}", exc_info=True)
        return []
