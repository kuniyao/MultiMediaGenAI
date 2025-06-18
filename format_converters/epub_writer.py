from __future__ import annotations
import pathlib
import tempfile
import zipfile
import base64
from typing import List, Optional
from bs4 import BeautifulSoup, Tag

from .book_schema import (
    Book, Chapter, AnyBlock, RichContentItem, HeadingBlock, ParagraphBlock,
    ImageBlock, ListBlock, TableBlock, TextItem, BoldItem, ItalicItem,
    HyperlinkItem, LineBreakItem, NoteReferenceItem, CodeBlock, MarkerBlock,
    NoteContentBlock, SmallItem
)


class EpubWriter:
    """
    根据一个 Book 对象，生成一个符合 EPUB 3 标准的 .epub 文件。
    """

    def __init__(self, book: Book, output_path: str):
        """
        初始化写入器。

        Args:
            book: 包含所有书籍内容的 Book 对象。
            output_path: 最终生成的 .epub文件的路径。
        """
        self.book = book
        self.output_path = pathlib.Path(output_path)
        
        # 创建一个临时目录用于构建EPUB文件结构
        self.temp_dir = tempfile.TemporaryDirectory()
        self.build_dir = pathlib.Path(self.temp_dir.name)

        # 定义EPUB标准目录结构
        self.oebps_dir = self.build_dir / 'OEBPS'
        self.meta_inf_dir = self.build_dir / 'META-INF'
        self.text_dir = self.oebps_dir / 'text'
        self.image_dir = self.oebps_dir / 'images'
        self.style_dir = self.oebps_dir / 'styles'

    def write(self):
        """
        执行所有步骤，生成最终的 .epub 文件。
        """
        print("开始构建 EPUB 文件...")
        
        # 1. 创建目录结构
        self._setup_directories()
        
        # 2. 写入 mimetype 文件 (这是EPUB规范的强制要求)
        self._write_mimetype()
        
        # 3. 还原所有资源 (图片、CSS)
        self._write_resources()
        
        # 4. 根据Book对象内容，生成所有章节的XHTML文件
        self._write_chapters()
        
        # 5. 生成元数据和配置文件
        self._write_container_xml()
        self._write_opf_file()
        self._write_nav_file()
        
        # 6. 将所有生成的文件打包成 .epub (ZIP压缩包)
        self._package_epub()
        
        print(f"EPUB 文件已成功生成: {self.output_path}")

    def _setup_directories(self):
        """在临时目录中创建EPUB标准文件夹结构。"""
        print("  - 创建目录结构...")
        self.oebps_dir.mkdir()
        self.meta_inf_dir.mkdir()
        self.text_dir.mkdir()
        self.image_dir.mkdir()
        self.style_dir.mkdir()

    def _write_mimetype(self):
        """创建 mimetype 文件。这个文件必须是ZIP包的第一个，且不能压缩。"""
        print("  - 写入 mimetype 文件...")
        mimetype_path = self.build_dir / 'mimetype'
        mimetype_path.write_text('application/epub+zip', encoding='ascii')

    def _write_resources(self):
        """将图片和CSS资源写入对应的目录。"""
        print("  - 写入资源文件 (CSS, 图片)...")
        
        # 写入 CSS 文件
        for path, resource in self.book.css_resources.items():
            # 使用 .name 实现扁平化目录结构
            file_name = pathlib.Path(path).name
            css_path = self.style_dir / file_name
            css_path.parent.mkdir(parents=True, exist_ok=True)
            css_path.write_text(resource.content, encoding='utf-8')

        # 写入图片文件
        for path, resource in self.book.image_resources.items():
            # 使用 .name 实现扁平化目录结构
            file_name = pathlib.Path(path).name
            img_path = self.image_dir / file_name
            img_path.parent.mkdir(parents=True, exist_ok=True)
            # 从 book_schema 中获取的是原始 bytes，可以直接写入
            img_path.write_bytes(resource.content)

    def _write_chapters(self):
        """遍历所有章节并生成对应的XHTML文件。"""
        print("  - 写入章节 XHTML 文件...")
        for i, chapter in enumerate(self.book.chapters):
            soup = self._create_xhtml_soup(chapter)
            
            # 将内容块转换为HTML并添加到body中
            body = soup.find('body')
            if isinstance(body, Tag):
                for block in chapter.content:
                    html_element = self._map_block_to_html(block, soup)
                    if html_element:
                        body.append(html_element)

            # 将soup对象写入文件
            # chapter.id 现在就是文件名，例如 "text/part0001.html"
            # 我们只需要取其文件名部分
            file_name = pathlib.Path(chapter.id).name
            chapter_path = self.text_dir / file_name
            chapter_path.write_text(str(soup.prettify()), encoding='utf-8')

    def _create_xhtml_soup(self, chapter: Chapter) -> BeautifulSoup:
        """创建一个标准XHTML文件的BeautifulSoup骨架。"""
        # 创建一个基本的HTML5结构
        soup = BeautifulSoup(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<!DOCTYPE html>'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
            '<head></head>'
            '<body></body>'
            '</html>',
            'xml' # 使用XML解析器以正确处理自闭合标签如<link/>
        )

        head = soup.find('head')
        if not isinstance(head, Tag):
             # 如果 head 找不到，这是一个严重错误，但至少我们不会在 None 上崩溃
            return soup
        
        # 添加标题
        if chapter.title:
            title_tag = soup.new_tag('title')
            # 优先使用翻译后的标题
            title_tag.string = chapter.title_target if chapter.title_target else chapter.title
            head.append(title_tag)

        # 链接外部CSS文件
        for css_path in self.book.css_resources:
            # 计算从text/到styles/的相对路径，并使用扁平化的文件名
            file_name = pathlib.Path(css_path).name
            relative_path = f"../styles/{file_name}"
            link_tag = soup.new_tag(
                'link',
                rel="stylesheet",
                type="text/css",
                href=relative_path
            )
            head.append(link_tag)
        
        # 添加内部CSS
        if chapter.internal_css:
            style_tag = soup.new_tag('style', type="text/css")
            style_tag.string = chapter.internal_css
            head.append(style_tag)
            
        return soup

    def _map_block_to_html(self, block: AnyBlock, soup: BeautifulSoup) -> Optional[Tag]:
        """将一个AnyBlock对象转换为BeautifulSoup的Tag对象。作为分发器。"""
        
        # 使用 isinstance 进行类型收窄，确保类型安全
        if isinstance(block, HeadingBlock):
            return self._map_heading_to_html(block, soup)
        elif isinstance(block, ParagraphBlock):
            return self._map_paragraph_to_html(block, soup)
        elif isinstance(block, ImageBlock):
            return self._map_image_to_html(block, soup)
        elif isinstance(block, ListBlock):
            return self._map_list_to_html(block, soup)
        elif isinstance(block, TableBlock):
            return self._map_table_to_html(block, soup)
        elif isinstance(block, CodeBlock):
            return self._map_code_block_to_html(block, soup)
        elif isinstance(block, MarkerBlock):
            return self._map_marker_to_html(block, soup)
        elif isinstance(block, NoteContentBlock):
            return self._map_note_content_to_html(block, soup)
        
        return None

    def _add_css_classes(self, tag: Tag, block: AnyBlock):
        """将block中的css_classes添加到tag中。"""
        if hasattr(block, 'css_classes') and block.css_classes:
            tag['class'] = " ".join(block.css_classes)

    def _map_heading_to_html(self, block: HeadingBlock, soup: BeautifulSoup) -> Tag:
        """将 HeadingBlock 转换为 <h1>, <h2> ... 标签。"""
        tag = soup.new_tag(f"h{block.level}")
        # 优先使用翻译后的目标内容
        tag.string = block.content_target if block.content_target else block.content_source
        self._add_css_classes(tag, block)
        return tag

    def _map_paragraph_to_html(self, block: ParagraphBlock, soup: BeautifulSoup) -> Tag:
        """将 ParagraphBlock 转换为 <p> 标签，并处理其内部的富文本。"""
        p_tag = soup.new_tag("p")
        self._add_css_classes(p_tag, block)
        # 优先使用翻译后的目标富文本内容
        content_to_map = block.content_rich_target if block.content_rich_target else block.content_rich_source
        self._map_rich_content_to_html(p_tag, content_to_map, soup)
        return p_tag

    def _map_image_to_html(self, block: ImageBlock, soup: BeautifulSoup) -> Tag:
        """将 ImageBlock 转换为 <img> 标签，可能包含在一个容器内。"""
        # 计算图片的相对路径，使用扁平化的文件名
        file_name = pathlib.Path(block.path).name
        relative_path = f"../images/{file_name}"
        
        # 优先使用翻译后的图片描述作为 alt 文本
        alt_text = block.content_target if block.content_target else block.content_source
        img_tag = soup.new_tag("img", src=relative_path, alt=alt_text)
        if block.img_css_classes:
            img_tag['class'] = " ".join(block.img_css_classes)

        # 如果指定了容器标签 (e.g., 'p')，则将图片包裹起来
        if block.container_tag:
            container_tag = soup.new_tag(block.container_tag)
            self._add_css_classes(container_tag, block) # css_classes 应用于容器
            container_tag.append(img_tag)
            return container_tag
        else:
            # 如果没有容器，img_css_classes 已经应用于 img_tag，
            # 现在将 block 的 css_classes (通常用于容器)也应用于 img_tag
            self._add_css_classes(img_tag, block)
            return img_tag

    def _map_list_to_html(self, block: ListBlock, soup: BeautifulSoup) -> Tag:
        """将 ListBlock 转换为 <ul> 或 <ol> 标签，并递归处理其项目。"""
        list_tag_name = "ol" if block.ordered else "ul"
        list_tag = soup.new_tag(list_tag_name)

        items_to_map = block.items_target if block.items_target else block.items_source

        # 检查是否为由<p>标签转换而来的伪列表
        is_pseudo_list = False
        final_classes = block.css_classes
        # 检查标记class
        if final_classes and 'pseudo-list-marker' in final_classes:
            is_pseudo_list = True
            # 创建一个不包含我们内部标记的新列表
            final_classes = [c for c in final_classes if c != 'pseudo-list-marker']

        # 应用清理后的class
        if final_classes:
            list_tag['class'] = " ".join(final_classes)

        for item in items_to_map:
            li_tag = soup.new_tag("li")
            self._map_rich_content_to_html(li_tag, item.content, soup)
            
            # 处理嵌套列表
            if item.nested_list:
                nested_list_tag = self._map_list_to_html(item.nested_list, soup)
                if nested_list_tag:
                    li_tag.append(nested_list_tag)
            
            if is_pseudo_list:
                # 对于伪列表的<li>标签，添加一个特定的类名以应用CSS ::before 伪元素
                li_tag['class'] = 'pseudo-list-item'
            
            list_tag.append(li_tag)
        return list_tag

    def _map_table_to_html(self, block: TableBlock, soup: BeautifulSoup) -> Tag:
        """将 TableBlock 转换为 <table> 标签。"""
        table_tag = soup.new_tag("table")
        self._add_css_classes(table_tag, block)
        
        # 优先使用翻译后的目标表格内容
        content_to_map = block.content_target if (block.content_target and (block.content_target.headers or block.content_target.rows)) else block.content_source

        # 渲染表头
        if content_to_map.headers:
            thead = soup.new_tag("thead")
            tr = soup.new_tag("tr")
            for cell_content in content_to_map.headers:
                th = soup.new_tag("th")
                self._map_rich_content_to_html(th, cell_content, soup)
                tr.append(th)
            thead.append(tr)
            table_tag.append(thead)
            
        # 渲染数据行
        if content_to_map.rows:
            tbody = soup.new_tag("tbody")
            for row_data in content_to_map.rows:
                tr = soup.new_tag("tr")
                for cell_content in row_data:
                    td = soup.new_tag("td")
                    self._map_rich_content_to_html(td, cell_content, soup)
                    tr.append(td)
                tbody.append(tr)
            table_tag.append(tbody)
            
        return table_tag

    def _map_code_block_to_html(self, block: CodeBlock, soup: BeautifulSoup) -> Tag:
        """将 CodeBlock 转换为 <pre><code>...</code></pre> 结构。"""
        pre_tag = soup.new_tag("pre")
        self._add_css_classes(pre_tag, block)
        
        code_tag = soup.new_tag("code")
        if block.language:
            code_tag['class'] = f"language-{block.language}"
        
        # 将结构化的代码行拼接为字符串，保留换行符
        code_text = "\n".join(line.value for line in block.content_structured_source)
        code_tag.string = code_text

        pre_tag.append(code_tag)

        # 优先使用翻译后的目标结构化内容
        content_to_map = block.content_structured_target if block.content_structured_target else block.content_structured_source

        # 逐行处理代码或注释
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

    def _map_marker_to_html(self, block: MarkerBlock, soup: BeautifulSoup) -> Optional[Tag]:
        """将 MarkerBlock 转换为对应的HTML标记，如 <hr/>。"""
        if block.role == "doc-pagebreak":
            hr_tag = soup.new_tag("hr")
            if block.title:
                hr_tag['title'] = block.title
            self._add_css_classes(hr_tag, block)
            # 在XHTML中，<hr> 可能是自闭合的，但BeautifulSoup会处理好
            return hr_tag
        return None

    def _map_note_content_to_html(self, block: NoteContentBlock, soup: BeautifulSoup) -> Tag:
        """将脚注/尾注内容块转换为HTML。"""
        # 脚注/尾注容器，通常是一个 div
        note_div = soup.new_tag("div")
        self._add_css_classes(note_div, block)
        note_div['id'] = block.id # 使用块的ID作为HTML元素的ID

        # 优先使用翻译后的目标内容
        content_to_map = block.content_target if block.content_target else block.content_source

        # 在容器内部渲染脚注的实际内容
        for inner_block in content_to_map:
            html_element = self._map_block_to_html(inner_block, soup)
            if html_element:
                note_div.append(html_element)
                
        return note_div

    def _map_rich_content_to_html(self, parent_tag: Tag, rich_content: List[RichContentItem], soup: BeautifulSoup):
        """将 RichContentItem 列表转换为HTML并追加到父标签中。"""
        for item in rich_content:
            # 使用 isinstance 进行类型收窄
            if isinstance(item, TextItem):
                parent_tag.append(item.content)
            elif isinstance(item, BoldItem):
                b_tag = soup.new_tag("b")
                self._map_rich_content_to_html(b_tag, item.content, soup)
                parent_tag.append(b_tag)
            elif isinstance(item, ItalicItem):
                i_tag = soup.new_tag("i")
                self._map_rich_content_to_html(i_tag, item.content, soup)
                parent_tag.append(i_tag)
            elif isinstance(item, HyperlinkItem):
                a_tag = soup.new_tag("a", href=item.href)
                if item.title:
                    a_tag['title'] = item.title
                self._map_rich_content_to_html(a_tag, item.content, soup)
                parent_tag.append(a_tag)
            elif isinstance(item, LineBreakItem):
                br_tag = soup.new_tag("br")
                parent_tag.append(br_tag)
            elif isinstance(item, NoteReferenceItem):
                # 将脚注引用转换为一个指向脚注内容的链接
                a_tag = soup.new_tag("a", href=f"#{item.note_id}")
                a_tag['epub:type'] = 'noteref'
                a_tag.string = item.marker # 显示的引用标记，如 [1]
                parent_tag.append(a_tag)
            elif isinstance(item, SmallItem):
                small_tag = soup.new_tag("small")
                self._map_rich_content_to_html(small_tag, item.content, soup)
                parent_tag.append(small_tag)

    def _write_container_xml(self):
        """生成 META-INF/container.xml 文件。"""
        print("  - 写入 container.xml...")
        container_content = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        container_path = self.meta_inf_dir / 'container.xml'
        container_path.write_text(container_content, encoding='utf-8')

    def _write_opf_file(self):
        """生成 content.opf 文件，包含元数据、清单和阅读顺序。"""
        print("  - 写入 content.opf 文件...")
        
        # 创建一个BeautifulSoup对象来构建OPF的XML结构
        soup = BeautifulSoup(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="pub-id" version="3.0">'
            '</package>',
            'xml'
        )
        package = soup.find('package')
        if not isinstance(package, Tag): return

        # --- 1. 元数据 (Metadata) ---
        metadata = soup.new_tag('metadata')
        
        dc_title = soup.new_tag('dc:title')
        dc_title.string = self.book.metadata.title_source
        metadata.append(dc_title)
        
        dc_lang = soup.new_tag('dc:language')
        dc_lang.string = self.book.metadata.language_source
        metadata.append(dc_lang)
        
        # 添加作者
        for author in self.book.metadata.author_source:
             creator_tag = soup.new_tag('dc:creator')
             creator_tag.string = author
             metadata.append(creator_tag)
        
        # 添加发布者
        if self.book.metadata.publisher_source:
            publisher_tag = soup.new_tag('dc:publisher')
            publisher_tag.string = self.book.metadata.publisher_source
            metadata.append(publisher_tag)

        # 添加ISBN作为唯一标识符
        if self.book.metadata.isbn:
            isbn_tag = soup.new_tag('dc:identifier', id="pub-id")
            isbn_tag.string = f"urn:isbn:{self.book.metadata.isbn}"
            metadata.append(isbn_tag)
        else:
            # 如果没有ISBN，创建一个UUID作为唯一标识符
            import uuid
            uuid_tag = soup.new_tag('dc:identifier', id="pub-id")
            uuid_tag.string = f"urn:uuid:{uuid.uuid4()}"
            metadata.append(uuid_tag)

        # 添加封面图片引用
        if self.book.metadata.cover_image:
             cover_meta_tag = soup.new_tag('meta', attrs={'name': 'cover', 'content': f"img-cover"})
             metadata.append(cover_meta_tag)

        package.append(metadata)

        # --- 2. 资源清单 (Manifest) ---
        manifest = soup.new_tag('manifest')
        # 添加导航文件
        manifest.append(soup.new_tag('item', id="nav", href="nav.xhtml", attrs={'media-type': 'application/xhtml+xml', 'properties': 'nav'}))

        # 添加章节
        for chapter in self.book.chapters:
            chapter_name = pathlib.Path(chapter.id).name
            # 为 manifest item 生成一个更可靠的 ID
            item_id = f"chap-{chapter_name}"
            manifest.append(soup.new_tag('item', id=item_id, href=f"text/{chapter_name}", attrs={'media-type': 'application/xhtml+xml'}))
        # 添加CSS
        for path in self.book.css_resources:
            file_name = pathlib.Path(path).name
            manifest.append(soup.new_tag('item', id=f"css-{file_name}", href=f"styles/{file_name}", attrs={'media-type': 'text/css'}))
        # 添加图片
        for path in self.book.image_resources:
            file_name = pathlib.Path(path).name
            media_type = self.book.image_resources[path].media_type
            item_id = f"img-{file_name}"
            # 特殊处理封面图片ID
            if path == self.book.metadata.cover_image:
                item_id = "img-cover"
                manifest.append(soup.new_tag('item', id=item_id, href=f"images/{file_name}", attrs={'media-type': media_type, 'properties': 'cover-image'}))
            else:
                manifest.append(soup.new_tag('item', id=item_id, href=f"images/{file_name}", attrs={'media-type': media_type}))
        
        package.append(manifest)

        # --- 3. 阅读顺序 (Spine) ---
        spine = soup.new_tag('spine')
        for chapter in self.book.chapters:
            chapter_name = pathlib.Path(chapter.id).name
            item_id = f"chap-{chapter_name}"
            spine.append(soup.new_tag('itemref', idref=item_id))
        package.append(spine)

        # 写入文件
        opf_path = self.oebps_dir / 'content.opf'
        opf_path.write_text(str(soup.prettify()), encoding='utf-8')

    def _write_nav_file(self):
        """生成 nav.xhtml 导航文件。"""
        print("  - 写入 nav.xhtml 文件...")
        
        soup = self._create_xhtml_soup(Chapter(id='nav.xhtml', title='Table of Contents', content=[]))
        body = soup.find('body')
        
        if isinstance(body, Tag):
            nav = soup.new_tag('nav', attrs={'epub:type': 'toc'})
            
            h1 = soup.new_tag('h1')
            h1.string = "Table of Contents"
            nav.append(h1)
            
            ol = soup.new_tag('ol')
            for chapter in self.book.chapters:
                if chapter.title:
                    li = soup.new_tag('li')
                    chapter_name = pathlib.Path(chapter.id).name
                    a = soup.new_tag('a', href=f"text/{chapter_name}")
                    # 优先使用翻译后的章节标题
                    a.string = chapter.title_target if chapter.title_target else chapter.title
                    li.append(a)
                    ol.append(li)
            
            nav.append(ol)
            body.append(nav)

        nav_path = self.oebps_dir / 'nav.xhtml'
        nav_path.write_text(str(soup.prettify()), encoding='utf-8')

    def _package_epub(self):
        """将构建目录中的所有内容打包成 .epub 文件。"""
        print("  - 打包为 .epub 文件...")
        
        with zipfile.ZipFile(self.output_path, 'w') as epub_zip:
            # 1. 写入 mimetype 文件 (无压缩)
            mimetype_path = self.build_dir / 'mimetype'
            epub_zip.write(mimetype_path, arcname='mimetype', compress_type=zipfile.ZIP_STORED)

            # 2. 递归写入其他所有文件 (带压缩)
            for file_path in self.build_dir.rglob('*'):
                if file_path.name == 'mimetype':
                    continue # 已经处理过了
                
                # 计算文件在ZIP包中的相对路径
                archive_name = file_path.relative_to(self.build_dir).as_posix()
                epub_zip.write(file_path, arcname=archive_name, compress_type=zipfile.ZIP_DEFLATED)
    
    def __del__(self):
        """在对象销毁时清理临时目录。"""
        if hasattr(self, 'temp_dir'):
            self.temp_dir.cleanup()
            print(f"已清理临时构建目录: {self.build_dir}")


def book_to_epub(book: Book, output_path: str):
    """
    一个便捷的函数，用于将 Book 对象直接转换为 .epub 文件。
    """
    writer = EpubWriter(book, output_path)
    writer.write() 