from __future__ import annotations
import zipfile
import tempfile
import pathlib
import uuid
from typing import Dict, List, Optional, Tuple, Union
from bs4 import BeautifulSoup, Tag
import base64
import mimetypes

from .book_schema import (
    Book, BookMetadata, Chapter, ImageResource, CSSResource,
    AnyBlock, HeadingBlock, ParagraphBlock, ImageBlock, ListBlock,
    TableBlock, NoteContentBlock, MarkerBlock, CodeBlock,
    RichContentItem, TextItem, BoldItem, ItalicItem, HyperlinkItem,
    LineBreakItem, NoteReferenceItem, ListItem, TableContent,
    CellContent, Row, CodeLine
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
        if not rootfile or 'full-path' not in rootfile.attrs:
            raise ValueError("在 container.xml 中无法找到 rootfile 路径。")

        opf_path = self.unzip_dir / rootfile['full-path']
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
        if metadata_tag:
            self.book.metadata.title_source = self._get_tag_text(metadata_tag, 'dc:title')
            self.book.metadata.language_source = self._get_tag_text(metadata_tag, 'dc:language')
            self.book.metadata.publisher_source = self._get_tag_text(metadata_tag, 'dc:publisher')
            
            authors = metadata_tag.find_all('dc:creator')
            self.book.metadata.author_source = [author.text.strip() for author in authors if author.text]

            isbn_tag = metadata_tag.find('dc:identifier', {'id': 'pub-identifier'})
            if isbn_tag and isbn_tag.text:
                 self.book.metadata.isbn = isbn_tag.text.strip()
            else:
                isbn_tag = metadata_tag.find('dc:identifier', string=lambda t: t and 'urn:isbn:' in t)
                if isbn_tag and isbn_tag.text:
                    self.book.metadata.isbn = isbn_tag.text.strip().split(':')[-1]
        
        # 2. 解析资源清单 <manifest>
        manifest_tag = opf_soup.find('manifest')
        cover_image_id = self._get_cover_image_id(metadata_tag)
        if manifest_tag:
            for item in manifest_tag.find_all('item'):
                item_id = item.get('id')
                href = item.get('href')
                media_type = item.get('media-type')
                if not all([item_id, href, media_type]):
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
        self._parse_nav(opf_soup, manifest_tag)

        # 3. 解析阅读顺序 <spine>
        spine_tag = opf_soup.find('spine')
        if spine_tag:
            for itemref in spine_tag.find_all('itemref'):
                idref = itemref.get('idref')
                if idref and idref in self.manifest_items:
                    item_info = self.manifest_items[idref]
                    # 在查找前，也对 manifest 中的 href 进行规范化，确保与 nav_map 中的 key 格式一致
                    raw_href = item_info.get("href")
                    if raw_href:
                        lookup_href = (self.content_dir / raw_href).resolve().relative_to(self.content_dir).as_posix()
                        
                        new_chapter = Chapter(
                            id=raw_href,  # 使用 href 作为更清晰、稳定的ID
                            title=self.nav_map.get(lookup_href),
                            epub_type=self.type_map.get(lookup_href),
                            content=[]
                        )
                        self.book.chapters.append(new_chapter)

    def _get_tag_text(self, parent_tag: Tag, tag_name: str) -> str:
        """安全地从父标签中获取子标签的文本内容。"""
        tag = parent_tag.find(tag_name)
        return tag.text.strip() if tag and tag.text else ""

    def _get_cover_image_id(self, metadata_tag: Optional[Tag]) -> Optional[str]:
        """从元数据中找到封面图片的ID。"""
        if not metadata_tag:
            return None
        cover_meta = metadata_tag.find('meta', {'name': 'cover'})
        if cover_meta and cover_meta.get('content'):
            return cover_meta.get('content')
        return None

    def _parse_nav(self, opf_soup: BeautifulSoup, manifest_tag: Tag):
        """
        解析导航文件 (nav.xhtml 或 toc.ncx) 来获取章节标题和语义类型。
        此方法现在更具鲁棒性，可以处理两种常见的目录格式。
        """
        # 从 manifest 查找导航文件
        nav_item = manifest_tag.find('item', {'properties': 'nav'})
        if not nav_item:
            # 兼容旧的 toc.ncx
            nav_item = manifest_tag.find('item', {'media-type': 'application/x-dtbncx+xml'})
        if not nav_item:
            print("警告: 未在 manifest 中找到导航文件 (nav.xhtml 或 toc.ncx)。")
            return

        nav_href = nav_item.get('href')
        nav_path = self.content_dir / nav_href
        if not nav_path.exists():
            print(f"警告: 导航文件 '{nav_path}' 不存在。")
            return
        
        nav_dir = nav_path.parent
        with open(nav_path, 'r', encoding='utf-8') as f:
            nav_soup = BeautifulSoup(f, 'xml')

        # 根据文件类型选择不同的解析路径
        if nav_path.suffix == '.ncx':
            # --- 解析旧的 toc.ncx 文件 ---
            for nav_point in nav_soup.find_all('navPoint'):
                nav_label = nav_point.find('navLabel')
                content_tag = nav_point.find('content')
                if nav_label and content_tag and content_tag.get('src'):
                    title = nav_label.find('text').text.strip()
                    src = content_tag.get('src')
                    
                    # 我们需要将 src（相对于ncx文件的路径）转换为相对于 OPF content_dir 的路径
                    absolute_path = (nav_dir / src).resolve()
                    key_href = absolute_path.relative_to(self.content_dir).as_posix()
                    clean_href = key_href.split('#')[0]
                    self.nav_map[clean_href] = title
        else:
            # --- 解析现代的 nav.xhtml 文件 ---
            # 首先尝试查找官方的 <nav epub:type="toc">
            nav_element = nav_soup.find('nav', {'epub:type': 'toc'})
            # 如果找不到，则退而求其次，查找第一个 <nav> 标签
            if not nav_element:
                nav_element = nav_soup.find('nav')

            if nav_element:
                for a_tag in nav_element.find_all('a'):
                    href = a_tag.get('href')
                    if href:
                        absolute_path = (nav_dir / href).resolve()
                        key_href = absolute_path.relative_to(self.content_dir).as_posix()
                        clean_href = key_href.split('#')[0]
                        self.nav_map[clean_href] = a_tag.text.strip()
            
            # 额外解析 epub:type
            for nav_element in nav_soup.find_all('nav'):
                epub_type = nav_element.get('epub:type')
                if not epub_type: continue

                # 将此 epub:type 应用于其包含的所有链接
                for a_tag in nav_element.find_all('a'):
                    if 'href' in a_tag.attrs:
                        absolute_path = (nav_dir / a_tag['href']).resolve()
                        key_href = absolute_path.relative_to(self.content_dir).as_posix()
                        clean_href = key_href.split('#')[0]
                        self.type_map[clean_href] = epub_type

    def _parse_chapters(self):
        """
        遍历所有已识别的章节，解析其HTML内容。
        """
        for chapter in self.book.chapters:
            # 现在 chapter.id 就是 href, 用它来查找 manifest 条目
            chapter_href = chapter.id
            if chapter_href not in self.href_to_manifest_item:
                print(f"警告: 无法在 manifest 中找到章节 href '{chapter_href}' 对应的文件。")
                continue

            chapter_info = self.href_to_manifest_item[chapter_href]
            chapter_path = chapter_info.get("path")

            if not chapter_path or not chapter_path.exists():
                print(f"警告: 章节文件路径无效或文件不存在: {chapter_path}")
                continue

            chapter_base_dir = chapter_path.parent
            with open(chapter_path, 'r', encoding='utf-8') as f:
                chapter_soup = BeautifulSoup(f, 'html.parser')

            # 提取章节内的 <style> 块
            style_tag = chapter_soup.find('style')
            if style_tag:
                chapter.internal_css = style_tag.string or ""

            body = chapter_soup.find('body')
            if not body:
                continue

            blocks: List[AnyBlock] = []
            
            # 使用 .children 迭代所有直接子节点，而不是 find_all
            tags_to_process = list(body.children)
            current_tag_index = 0
            
            while current_tag_index < len(tags_to_process):
                tag = tags_to_process[current_tag_index]
                current_tag_index += 1

                if not isinstance(tag, Tag):
                    continue
                
                # --- 智能列表处理 ---
                # 解包 <section> 和 <div> 容器
                if tag.name in ['section', 'div']:
                    # 将容器内的标签插入到当前处理队列的前面
                    tags_to_process[current_tag_index:current_tag_index] = list(tag.children)
                    continue

                if tag.name == 'p':
                    # 修正：处理 <p class="bullet">...</p> 这样的伪列表
                    # 我们需要向前看，检查接下来是否还有连续的 'bullet' 段落
                    if 'bullet' in (tag.get('class') or []):
                        # 查找所有连续的兄弟节点
                        pseudo_list_tags = [tag]
                        
                        # 这个循环需要安全地在原始的 tags_to_process 列表中查看
                        while current_tag_index < len(tags_to_process):
                            next_tag = tags_to_process[current_tag_index]
                            if isinstance(next_tag, Tag) and next_tag.name == 'p' and 'bullet' in (next_tag.get('class') or []):
                                pseudo_list_tags.append(next_tag)
                                current_tag_index += 1 # 跳过我们已经处理的兄弟节点
                            else:
                                break
                        
                        # 将这些标签作为一个伪列表块进行处理
                        block = self._parse_pseudo_list_block(pseudo_list_tags)
                        if block:
                            blocks.append(block)
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
        return classes if classes else None

    def _generate_id(self) -> str:
        """生成一个唯一的ID字符串。"""
        return uuid.uuid4().hex

    def _map_tag_to_block(self, tag: Tag, chapter_base_dir: pathlib.Path) -> Optional[Union[AnyBlock, List[AnyBlock]]]:
        """
        将 BeautifulSoup 的 Tag 对象映射到我们定义的块模型。
        返回单个块，块列表（用于解包的div），或在不支持的标签时返回 None。
        """
        tag_name = tag.name
        
        # 标题
        if tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            return self._parse_heading_block(tag)
        
        # 图片: 优先处理图片和图片容器
        if tag_name == 'img':
            return self._parse_image_block(tag, chapter_base_dir)
        if tag.find('img'): # 检查标签内是否包含图片
             # 如果是 p 或 div 等容器，并且主要内容是图片
            img_tag = tag.find('img')
            # 检查除了img外是否还有其他有意义的内容
            if img_tag and not any(s.strip() for s in tag.strings if s.strip()):
                block = self._parse_image_block(img_tag, chapter_base_dir)
                if block:
                    block.container_tag = tag_name
                    block.css_classes = self._get_css_classes(tag)
                return block

        # 段落 (在图片之后处理)
        if tag_name == 'p':
            return self._parse_paragraph_block(tag)

        # 列表
        if tag_name in ['ul', 'ol']:
            return self._parse_list_block(tag)

        # 表格
        if tag_name == 'table':
            return self._parse_table_block(tag)
        
        # 代码块
        if tag_name == 'pre':
            return self._parse_code_block(tag)

        # 分页符等标记
        if tag_name == 'hr' and 'doc-pagebreak' in (tag.get('class') or []):
            return MarkerBlock(
                id=self._generate_id(),
                role="doc-pagebreak",
                title=tag.get('title')
            )
        
        # 脚注/尾注内容块 (e.g., <div epub:type="rearnote">)
        if tag.get('epub:type') and 'note' in tag.get('epub:type'):
             # 注意：这里的实现需要根据具体EPUB的脚注结构来调整
             # 这是一个简化的示例
            pass

        return None

    def _parse_rich_content(self, tag: Tag) -> List[RichContentItem]:
        """
        将一个标签内的混合内容（文本、<b>、<i>、<a>等）解析为 RichContentItem 列表。
        """
        items: List[RichContentItem] = []
        for content in tag.contents:
            if isinstance(content, str):
                # 忽略纯粹的空白换行符
                if content.strip():
                    items.append(TextItem(content=content))
            elif isinstance(content, Tag):
                if content.name in ['b', 'strong']:
                    items.append(BoldItem(content=content.text))
                elif content.name in ['i', 'em']:
                    items.append(ItalicItem(content=content.text))
                elif content.name == 'a':
                    # 检查是否为脚注引用
                    epub_type = content.get('epub:type')
                    if epub_type and 'noteref' in epub_type:
                        items.append(NoteReferenceItem(
                            marker=content.text,
                            note_id=content.get('href', '#')[1:] # href="#note1" -> "note1"
                        ))
                    else:
                        items.append(HyperlinkItem(
                            href=content.get('href', ''),
                            content=content.text,
                            title=content.get('title')
                        ))
                elif content.name == 'br':
                    items.append(LineBreakItem())
                else:
                    # 对于未知的内联标签，我们只提取其文本
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
        if not src:
            return None

        final_path = None
        normalized_href = src # 默认情况下，如果所有尝试都失败，则回退到原始src

        # 步骤 1: 尝试通过解析HTML中的src路径来规范化和定位图片
        try:
            # 将 src 路径（相对于当前章节文件）转换为相对于 OPF content_dir 的路径
            absolute_path = (chapter_base_dir / src).resolve()
            normalized_href = absolute_path.relative_to(self.content_dir).as_posix()
            
            # 如果解析出的路径存在于我们的图片资源中，就使用它
            if normalized_href in self.book.image_resources:
                final_path = normalized_href
        except Exception:
            # 如果路径解析失败（例如，文件在临时目录中实际不存在），则忽略错误并继续执行回退逻辑
            pass

        # 步骤 2: 如果主要方法失败，则回退到基于文件名的搜索
        if not final_path:
            filename = pathlib.Path(src).name
            # 在所有已知的图片资源href中查找匹配的文件名
            found_paths = [
                href for href in self.book.image_resources.keys() 
                if href.endswith(f"/{filename}") or href == filename
            ]

            if len(found_paths) == 1:
                # 找到了唯一匹配项，这是最理想的回退情况
                final_path = found_paths[0]
                print(f"警告: 图片 '{src}' 的路径不规范。已通过文件名匹配修正为 -> '{final_path}'")
            elif len(found_paths) > 1:
                # 存在多个同名文件，无法确定使用哪一个
                print(f"警告: 图片 '{src}' 的路径不规范, 且在资源中找到多个同名文件: {found_paths}。将使用原始src。")
                final_path = src # 保留原始的、可能损坏的路径
            else:
                 # 在任何地方都找不到该图片
                print(f"警告: 无法在图片资源中找到 '{src}'。将使用原始src。")
                final_path = src # 保留原始的、可能损坏的路径
        
        # 最终决定使用的路径
        final_path_decision = final_path if final_path is not None else normalized_href

        return ImageBlock(
            id=self._generate_id(),
            path=final_path_decision,
            content_source=tag.get('alt', ''),
            img_css_classes=self._get_css_classes(tag)
        )

    def _parse_list_block(self, tag: Tag) -> ListBlock:
        """解析列表标签 (<ul>, <ol>)。"""
        items: List[ListItem] = []
        for li in tag.find_all('li', recursive=False):
            # 分离 li 中的嵌套列表
            nested_list_tag = li.find(['ul', 'ol'])
            nested_list_block = None
            if nested_list_tag:
                # 从 li 的内容中移除嵌套列表，避免重复解析
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
                cell_content: CellContent = self._parse_rich_content(cell_tag)
                row_data.append(cell_content)
            return row_data

        headers: Row = []
        rows: List[Row] = []

        # 查找 thead
        thead = tag.find('thead')
        if thead:
            for tr in thead.find_all('tr'):
                # 表头可能有多行
                headers.extend(parse_row(tr))
        
        # 查找 tbody
        tbody = tag.find('tbody')
        if not tbody:
            # 如果没有tbody，则将整个table视为body
            tbody = tag

        for tr in tbody.find_all('tr'):
            # 确保我们不会重复计算表头行（如果它不在thead里）
            if tr.parent.name == 'thead': continue
            # 忽略完全在 thead 中的 tr
            if tr.find_parent('thead'): continue
                
            rows.append(parse_row(tr))
        
        # 如果没有找到独立的 thead，但第一行是 th，则将其视为表头
        if not headers and rows:
            first_row_cells = tbody.find('tr').find_all(['th', 'td'])
            if first_row_cells and first_row_cells[0].name == 'th':
                 headers = rows.pop(0)

        return TableBlock(
            id=self._generate_id(),
            content_source=TableContent(headers=headers, rows=rows),
            css_classes=self._get_css_classes(tag),
        )

    def _parse_code_block(self, tag: Tag) -> CodeBlock:
        """解析预格式化文本标签 (<pre>)，通常用于代码。"""
        code_tag = tag.find('code')
        target_tag = code_tag if code_tag else tag
        
        # 通常语言在 <code> 的 class 中，例如 <code class="language-python">
        lang = None
        if code_tag and code_tag.get('class'):
            for c in code_tag.get('class'):
                if c.startswith('language-'):
                    lang = c.replace('language-', '')
                    break
        
        lines = target_tag.get_text().split('\n')
        structured_lines = [CodeLine(value=line) for line in lines]

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
        
        # 注意：这种伪列表我们假定其为无序列表
        return ListBlock(
            id=self._generate_id(),
            ordered=False,
            items_source=items,
            css_classes=self._get_css_classes(tags[0]) # 使用第一个标签的class
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