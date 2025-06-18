from __future__ import annotations
import zipfile
import tempfile
import pathlib
import uuid
from typing import Dict, List, Optional, Tuple, Union, cast
from bs4 import BeautifulSoup, Tag
import base64
import mimetypes

from .book_schema import (
    Book, BookMetadata, Chapter, ImageResource, CSSResource,
    AnyBlock, HeadingBlock, ParagraphBlock, ImageBlock, ListBlock,
    TableBlock, NoteContentBlock, MarkerBlock, CodeBlock,
    RichContentItem, TextItem, BoldItem, ItalicItem, HyperlinkItem,
    LineBreakItem, NoteReferenceItem, ListItem, TableContent,
    CellContent, Row, CodeLine, SmallItem, CodeContentItem
)


class EpubParser:
    """
    将EPUB文件解析并将其内容转换为基于 book_schema 的 Book 对象。
    """

    def __init__(self, epub_path: str):
        """
        初始化解析器，解压EPUB文件并找到 .opf 文件。
        """
        self.epub_path = pathlib.Path(epub_path)
        if not self.epub_path.is_file():
            raise FileNotFoundError(f"EPUB 文件未找到: {self.epub_path}")

        # 创建一个临时目录来存放解压后的文件
        self.temp_dir = tempfile.TemporaryDirectory()
        self.unzip_dir = pathlib.Path(self.temp_dir.name)
        self._unzip_epub()

        # 定位核心的 .opf 文件路径
        self.opf_path = self._find_opf_path()
        self.content_dir = self.opf_path.parent

        # 初始化一个空的 Book 对象，后续将填充内容
        self.book = Book(
            metadata=BookMetadata(title_source="", language_source="", language_target=""),
            chapters=[]
        )
        # 用于存储 ID 和文件路径的映射
        self.manifest_items: Dict[str, Dict] = {}
        # 用于存储 href 和章节标题的映射
        self.nav_map: Dict[str, str] = {}
        # 用于存储 href 和 epub:type 的映射
        self.type_map: Dict[str, str] = {}
        # 新增：用于从 href 直接查找 manifest 条目
        self.href_to_manifest_item: Dict[str, Dict] = {}

    def _unzip_epub(self):
        """将EPUB文件解压到临时目录。"""
        with zipfile.ZipFile(self.epub_path, 'r') as zip_ref:
            zip_ref.extractall(self.unzip_dir)
        print(f"已将EPUB解压至: {self.unzip_dir}")

    def _find_opf_path(self) -> pathlib.Path:
        """
        通过 container.xml 找到 .opf 文件的路径。
        .opf 文件是定义书籍结构的"主文件"。
        """
        container_xml_path = self.unzip_dir / 'META-INF' / 'container.xml'
        if not container_xml_path.exists():
            raise FileNotFoundError("EPUB中未找到 META-INF/container.xml。")

        with open(container_xml_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'xml')

        rootfile = soup.find('rootfile')
        if not isinstance(rootfile, Tag):
            raise ValueError("在 container.xml 中无法找到 <rootfile> 标签。")

        full_path_attr = rootfile.get('full-path')
        if not isinstance(full_path_attr, str):
             raise ValueError("在 container.xml 的 <rootfile> 标签中找不到 'full-path' 属性。")

        opf_path = self.unzip_dir / full_path_attr
        if not opf_path.exists():
            raise FileNotFoundError(f"在 container.xml 指定的路径中未找到OPF文件: {opf_path}")

        return opf_path

    def parse(self) -> Book:
        """
        执行EPUB文件解析的主方法。
        
        返回:
            一个代表EPUB内容的 Book 对象。
        """
        # 第二阶段: 解析 .opf 文件，获取元数据、资源清单和阅读顺序
        print("正在解析 OPF 文件...")
        self._parse_opf()

        # 第三阶段: 解析每个章节文件，将HTML内容映射到我们的数据模型
        print("正在解析章节内容...")
        self._parse_chapters()

        print("解析完成。")
        return self.book

    def _parse_opf(self):
        """解析 .opf 文件以填充元数据、资源和章节顺序。"""
        with open(self.opf_path, 'r', encoding='utf-8') as f:
            opf_soup = BeautifulSoup(f, 'xml')

        # 1. 解析元数据 <metadata>
        metadata_tag = opf_soup.find('metadata')
        if isinstance(metadata_tag, Tag):
            self.book.metadata.title_source = self._get_tag_text(metadata_tag, 'dc:title')
            self.book.metadata.language_source = self._get_tag_text(metadata_tag, 'dc:language')
            self.book.metadata.publisher_source = self._get_tag_text(metadata_tag, 'dc:publisher')
            
            authors = metadata_tag.find_all('dc:creator')
            self.book.metadata.author_source = [author.text.strip() for author in authors if author.text]

            isbn_tag = metadata_tag.find('dc:identifier', {'id': 'pub-identifier'})
            if isinstance(isbn_tag, Tag) and isbn_tag.text:
                 self.book.metadata.isbn = isbn_tag.text.strip()
            else:
                isbn_tag = metadata_tag.find('dc:identifier', string=lambda t: bool(t and 'urn:isbn:' in t))
                if isinstance(isbn_tag, Tag) and isbn_tag.text:
                    self.book.metadata.isbn = isbn_tag.text.strip().split(':')[-1]
        
        # 2. 解析资源清单 <manifest>
        manifest_tag = opf_soup.find('manifest')
        cover_image_id = None
        if isinstance(metadata_tag, Tag):
            cover_image_id = self._get_cover_image_id(metadata_tag)

        if isinstance(manifest_tag, Tag):
            for item in manifest_tag.find_all('item'):
                if not isinstance(item, Tag):
                    continue
                item_id = item.get('id')
                href = item.get('href')
                media_type = item.get('media-type')

                if not (isinstance(item_id, str) and isinstance(href, str) and isinstance(media_type, str)):
                    continue
                
                full_path = self.content_dir / href
                if not full_path.exists():
                    print(f"警告: 在manifest中声明的文件未找到: {full_path}")
                    continue

                self.manifest_items[item_id] = { "path": full_path, "media_type": media_type, "href": href }

                if item_id == cover_image_id:
                    self.book.metadata.cover_image = href

                if media_type == "text/css":
                    with open(full_path, 'r', encoding='utf-8') as css_file:
                        self.book.css_resources[href] = CSSResource(content=css_file.read())
                elif media_type.startswith("image/"):
                    with open(full_path, 'rb') as img_file:
                        self.book.image_resources[href] = ImageResource(
                            content=img_file.read(),
                            media_type=media_type
                        )
        
        # 创建 href 到 manifest 条目的反向映射，方便后续查找
        self.href_to_manifest_item = {v['href']: v for v in self.manifest_items.values() if 'href' in v}

        # 4. 解析导航文件以获取章节标题和类型
        if isinstance(manifest_tag, Tag):
            self._parse_nav(opf_soup, manifest_tag)
        else:
            print("警告: 在 OPF 文件中未找到 <manifest> 标签，无法解析导航。")

        # 3. 解析阅读顺序 <spine>
        spine_tag = opf_soup.find('spine')
        if isinstance(spine_tag, Tag):
            for itemref in spine_tag.find_all('itemref'):
                if not isinstance(itemref, Tag):
                    continue
                idref = itemref.get('idref')
                if isinstance(idref, str) and idref in self.manifest_items:
                    item_info = self.manifest_items[idref]
                    raw_href = item_info.get("href")
                    if raw_href:
                        lookup_href = (self.content_dir / raw_href).resolve().relative_to(self.content_dir).as_posix()
                        
                        new_chapter = Chapter(
                            id=raw_href,
                            title=self.nav_map.get(lookup_href),
                            epub_type=self.type_map.get(lookup_href),
                            content=[]
                        )
                        self.book.chapters.append(new_chapter)

    def _get_tag_text(self, parent_tag: Tag, tag_name: str) -> str:
        """安全地从父标签中获取子标签的文本内容。"""
        tag = parent_tag.find(tag_name)
        return tag.text.strip() if isinstance(tag, Tag) and tag.text else ""

    def _get_cover_image_id(self, metadata_tag: Tag) -> Optional[str]:
        """从元数据中找到封面图片的ID。"""
        cover_meta = metadata_tag.find('meta', {'name': 'cover'})
        if isinstance(cover_meta, Tag):
            content = cover_meta.get('content')
            if isinstance(content, list):
                return str(content[0]) if content else None
            if isinstance(content, str):
                return content
        return None

    def _parse_nav(self, opf_soup: BeautifulSoup, manifest_tag: Tag):
        """
        解析导航文件 (nav.xhtml 或 toc.ncx) 来获取章节标题和语义类型。
        此方法现在更具鲁棒性，可以处理两种常见的目录格式。
        """
        nav_item = manifest_tag.find('item', {'properties': 'nav'})
        if not isinstance(nav_item, Tag):
            nav_item = manifest_tag.find('item', {'media-type': 'application/x-dtbncx+xml'})
        
        if not isinstance(nav_item, Tag):
            print("警告: 未在 manifest 中找到导航文件 (nav.xhtml 或 toc.ncx)。")
            return

        nav_href = nav_item.get('href')
        if not isinstance(nav_href, str):
            print(f"警告: 导航文件 item 缺少有效的 href 属性。")
            return
            
        nav_path = self.content_dir / nav_href
        if not nav_path.exists():
            print(f"警告: 导航文件 '{nav_path}' 不存在。")
            return
        
        nav_dir = nav_path.parent
        with open(nav_path, 'r', encoding='utf-8') as f:
            nav_soup = BeautifulSoup(f, 'xml')

        if nav_path.suffix == '.ncx':
            for nav_point in nav_soup.find_all('navPoint'):
                if not isinstance(nav_point, Tag): continue
                nav_label = nav_point.find('navLabel')
                content_tag = nav_point.find('content')
                if isinstance(nav_label, Tag) and isinstance(content_tag, Tag):
                    src_attr = content_tag.get('src')
                    title_tag = nav_label.find('text')
                    if isinstance(src_attr, str) and isinstance(title_tag, Tag) and title_tag.text:
                        title = title_tag.text.strip()
                        absolute_path = (nav_dir / src_attr).resolve()
                        key_href = absolute_path.relative_to(self.content_dir).as_posix()
                        clean_href = key_href.split('#')[0]
                        self.nav_map[clean_href] = title
        else:
            nav_element = nav_soup.find('nav', {'epub:type': 'toc'})
            if not isinstance(nav_element, Tag):
                nav_element = nav_soup.find('nav')

            if isinstance(nav_element, Tag):
                for a_tag in nav_element.find_all('a'):
                    if not isinstance(a_tag, Tag): continue
                    href = a_tag.get('href')
                    if isinstance(href, str) and a_tag.string:
                        absolute_path = (nav_dir / href).resolve()
                        key_href = absolute_path.relative_to(self.content_dir).as_posix()
                        clean_href = key_href.split('#')[0]
                        self.nav_map[clean_href] = a_tag.string.strip()
            
            for nav_element in nav_soup.find_all('nav'):
                if not isinstance(nav_element, Tag): continue
                epub_type = nav_element.get('epub:type')
                if not epub_type: continue

                for a_tag in nav_element.find_all('a'):
                    if not isinstance(a_tag, Tag): continue
                    href_attr = a_tag.get('href')
                    if isinstance(href_attr, str):
                        absolute_path = (nav_dir / href_attr).resolve()
                        key_href = absolute_path.relative_to(self.content_dir).as_posix()
                        clean_href = key_href.split('#')[0]
                        self.type_map[clean_href] = " ".join(epub_type) if isinstance(epub_type, list) else str(epub_type)

    def _parse_chapters(self):
        """
        遍历所有已识别的章节，解析其HTML内容。
        """
        for chapter in self.book.chapters:
            chapter_href = chapter.id
            if chapter_href not in self.href_to_manifest_item:
                print(f"警告: 无法在 manifest 中找到章节 href '{chapter_href}' 对应的文件。")
                continue

            chapter_info = self.href_to_manifest_item[chapter_href]
            chapter_path_any = chapter_info.get("path")

            if not isinstance(chapter_path_any, pathlib.Path) or not chapter_path_any.exists():
                print(f"警告: 章节文件路径无效或文件不存在: {chapter_path_any}")
                continue
            
            chapter_path = chapter_path_any
            chapter_base_dir = chapter_path.parent
            with open(chapter_path, 'r', encoding='utf-8') as f:
                chapter_soup = BeautifulSoup(f, 'html.parser')

            style_tag = chapter_soup.find('style')
            if isinstance(style_tag, Tag) and style_tag.string:
                chapter.internal_css = str(style_tag.string)

            body = chapter_soup.find('body')
            if not isinstance(body, Tag):
                continue

            blocks: List[AnyBlock] = []
            
            tags_to_process = list(body.children)
            current_tag_index = 0
            
            while current_tag_index < len(tags_to_process):
                tag = tags_to_process[current_tag_index]
                current_tag_index += 1

                if not isinstance(tag, Tag):
                    continue
                
                if tag.name in ['section', 'div']:
                    tags_to_process[current_tag_index:current_tag_index] = list(tag.children)
                    continue

                if tag.name == 'p':
                    if 'bullet' in (tag.get('class') or []):
                        pseudo_list_tags = [tag]
                        
                        while current_tag_index < len(tags_to_process):
                            next_tag = tags_to_process[current_tag_index]
                            
                            if not isinstance(next_tag, Tag):
                                current_tag_index += 1
                                continue
                            
                            if next_tag.name == 'p' and 'bullet' in (next_tag.get('class') or []):
                                pseudo_list_tags.append(next_tag)
                                current_tag_index += 1
                            else:
                                break
                        
                        block = self._parse_pseudo_list_block(pseudo_list_tags)
                        if block:
                            blocks.append(block)
                        
                        current_tag_index -= 1
                        continue

                block = self._map_tag_to_block(tag, chapter_base_dir)
                if block:
                    if isinstance(block, list):
                        blocks.extend(block)
                    else:
                        blocks.append(block)

            chapter.content = blocks

    def _get_css_classes(self, tag: Tag) -> Optional[List[str]]:
        """从标签中提取CSS类名列表。"""
        classes = tag.get('class')
        if isinstance(classes, list):
            return [str(c) for c in classes]
        if isinstance(classes, str):
            return classes.split()
        return None

    def _generate_id(self) -> str:
        """生成一个唯一的ID字符串。"""
        return uuid.uuid4().hex

    def _map_tag_to_block(self, tag: Tag, chapter_base_dir: pathlib.Path) -> Optional[Union[AnyBlock, List[AnyBlock]]]:
        """
        将 BeautifulSoup 的 Tag 对象映射到我们定义的块模型。
        返回单个块，块列表（用于解包的div），或在不支持的标签时返回 None。
        """
        tag_name = tag.name
        
        if tag_name == 'img':
            return self._parse_image_block(tag, chapter_base_dir)
        
        img_tag = tag.find('img')
        if isinstance(img_tag, Tag):
            if not any(s.strip() for s in tag.strings if s.strip()):
                block = self._parse_image_block(img_tag, chapter_base_dir)
                if block:
                    block.container_tag = tag_name
                    block.css_classes = self._get_css_classes(tag)
                return block

        if tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            return self._parse_heading_block(tag)
        
        if tag_name == 'p':
            return self._parse_paragraph_block(tag)

        if tag_name in ['ul', 'ol']:
            return self._parse_list_block(tag)

        if tag_name == 'table':
            return self._parse_table_block(tag)
        
        if tag_name == 'pre':
            return self._parse_code_block(tag)

        if tag_name == 'hr' and 'doc-pagebreak' in (tag.get('class') or []):
            title = tag.get('title')
            return MarkerBlock(
                id=self._generate_id(),
                role="doc-pagebreak",
                title=str(title) if title else None
            )
        
        epub_type = tag.get('epub:type')
        if isinstance(epub_type, str) and 'note' in epub_type:
            pass

        return None

    def _parse_rich_content(self, tag: Tag) -> List[RichContentItem]:
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
                    items.append(BoldItem(content=self._parse_rich_content(content)))
                elif content.name in ['i', 'em']:
                    items.append(ItalicItem(content=self._parse_rich_content(content)))
                elif content.name == 'small':
                     items.append(SmallItem(content=self._parse_rich_content(content)))
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
                            content=self._parse_rich_content(content),
                            title=str(title) if title else None
                        ))
                elif content.name == 'br':
                    items.append(LineBreakItem())
                else:
                    if content.text.strip():
                        items.append(TextItem(content=content.text))
        return items

    def _get_plain_text(self, tag: Tag) -> str:
        """获取标签内的纯文本表示。"""
        return tag.get_text(separator=" ", strip=True)

    def _parse_heading_block(self, tag: Tag) -> HeadingBlock:
        """解析标题标签 (<h1>, <h2>, etc.)。"""
        return HeadingBlock(
            id=self._generate_id(),
            level=int(tag.name[1]),
            content_source=self._get_plain_text(tag),
            css_classes=self._get_css_classes(tag)
        )

    def _parse_paragraph_block(self, tag: Tag) -> ParagraphBlock:
        """解析段落标签 (<p>)。"""
        return ParagraphBlock(
            id=self._generate_id(),
            content_rich_source=self._parse_rich_content(tag),
            content_source=self._get_plain_text(tag),
            css_classes=self._get_css_classes(tag)
        )

    def _parse_image_block(self, tag: Tag, chapter_base_dir: pathlib.Path) -> Optional[ImageBlock]:
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
            normalized_href = absolute_path.relative_to(self.content_dir).as_posix()
            
            if normalized_href in self.book.image_resources:
                final_path = normalized_href
        except Exception:
            pass

        if not final_path:
            filename = pathlib.Path(src).name
            found_paths = [
                href for href in self.book.image_resources.keys() 
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
            id=self._generate_id(),
            path=final_path_decision,
            content_source=str(alt_text) if alt_text else '',
            img_css_classes=self._get_css_classes(tag)
        )

    def _parse_list_block(self, tag: Tag) -> ListBlock:
        """解析列表标签 (<ul>, <ol>)。"""
        items: List[ListItem] = []
        for li in tag.find_all('li', recursive=False):
            if not isinstance(li, Tag): continue
            nested_list_tag = li.find(['ul', 'ol'])
            nested_list_block = None
            if isinstance(nested_list_tag, Tag):
                nested_list_tag.extract()
                nested_list_block = self._parse_list_block(nested_list_tag)

            items.append(ListItem(
                content=self._parse_rich_content(li),
                nested_list=nested_list_block
            ))
        
        return ListBlock(
            id=self._generate_id(),
            ordered=tag.name == 'ol',
            items_source=items,
            css_classes=self._get_css_classes(tag)
        )

    def _parse_table_block(self, tag: Tag) -> TableBlock:
        """解析表格标签 (<table>)。"""
        
        def parse_row(tr_tag: Tag) -> Row:
            row_data: Row = []
            for cell_tag in tr_tag.find_all(['th', 'td']):
                if isinstance(cell_tag, Tag):
                    cell_content: CellContent = self._parse_rich_content(cell_tag)
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
            id=self._generate_id(),
            content_source=TableContent(headers=final_headers, rows=rows),
            css_classes=self._get_css_classes(tag),
        )

    def _parse_code_block(self, tag: Tag) -> CodeBlock:
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
            id=self._generate_id(),
            language=lang,
            content_structured_source=structured_lines,
            css_classes=self._get_css_classes(tag)
        )

    def _parse_pseudo_list_block(self, tags: List[Tag]) -> ListBlock:
        """
        将一系列 <p> 标签（例如 <p class="bullet">）转换为一个 ListBlock。
        """
        items = [
            ListItem(content=self._parse_rich_content(tag)) for tag in tags
        ]
        
        css_classes = self._get_css_classes(tags[0]) or []
        css_classes.append('pseudo-list-marker')
        
        return ListBlock(
            id=self._generate_id(),
            ordered=False,
            items_source=items,
            css_classes=css_classes
        )

    def __del__(self):
        """在对象销毁时清理临时目录。"""
        if hasattr(self, 'temp_dir'):
            self.temp_dir.cleanup()
            print(f"已清理临时目录: {self.unzip_dir}")

def epub_to_book(epub_path: str) -> Book:
    """
    一个便捷的函数，用于将EPUB文件路径转换为 Book 对象。
    """

    parser = EpubParser(epub_path)
    book = parser.parse()
    return book