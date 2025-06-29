from __future__ import annotations
import zipfile
import tempfile
import pathlib
from typing import Dict, List, Optional
from bs4 import BeautifulSoup, Tag

from . import html_mapper
from .book_schema import (
    Book, BookMetadata, Chapter, ImageResource, CSSResource,
    AnyBlock
)
# 【變更 1】: 導入我們剛剛建立的"合約"
from .base_converter import BaseInputConverter


# 【變更 2】: 類別改名並繼承自 BaseInputConverter
class EpubParser(BaseInputConverter):
    """
    將EPUB文件解析並將其內容轉換為基於 book_schema 的 Book 物件。
    這個類別現在履行 BaseInputConverter 的"合約"。
    """

    def __init__(self, epub_path: str, logger=None):
        """
        初始化解析器，解壓EPUB文件並找到 .opf 文件。
        """
        self.epub_path = pathlib.Path(epub_path)
        self.logger = logger
        if not self.epub_path.is_file():
            raise FileNotFoundError(f"EPUB 文件未找到: {self.epub_path}")

        # 創建一個臨時目錄來存放解壓後的檔案
        self.temp_dir = tempfile.TemporaryDirectory()
        self.unzip_dir = pathlib.Path(self.temp_dir.name)
        self._unzip_epub()

        # 定位核心的 .opf 文件路徑
        self.opf_path = self._find_opf_path()
        self.content_dir = self.opf_path.parent

        # 初始化一個空的 Book 物件，後續將填充內容
        self.book = Book(
            metadata=BookMetadata(title_source="", language_source="", language_target=""),
            chapters=[]
        )
        # 用於儲存 ID 和文件路徑的映射
        self.manifest_items: Dict[str, Dict] = {}
        # 用於儲存 href 和章節標題的映射
        self.nav_map: Dict[str, str] = {}
        # 用於儲存 href 和 epub:type 的映射
        self.type_map: Dict[str, str] = {}
        # 新增：用於從 href 直接查找 manifest 條目
        self.href_to_manifest_item: Dict[str, Dict] = {}

    def _unzip_epub(self):
        """將EPUB文件解壓到臨時目錄。"""
        with zipfile.ZipFile(self.epub_path, 'r') as zip_ref:
            zip_ref.extractall(self.unzip_dir)
        print(f"已將EPUB解壓至: {self.unzip_dir}")

    def _find_opf_path(self) -> pathlib.Path:
        """
        通過 container.xml 找到 .opf 文件的路徑。
        .opf 文件是定義書籍結構的"主文件"。
        """
        container_xml_path = self.unzip_dir / 'META-INF' / 'container.xml'
        if not container_xml_path.exists():
            raise FileNotFoundError("EPUB中未找到 META-INF/container.xml。")

        with open(container_xml_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'xml')

        rootfile = soup.find('rootfile')
        if not isinstance(rootfile, Tag):
            raise ValueError("在 container.xml 中無法找到 <rootfile> 標籤。")

        full_path_attr = rootfile.get('full-path')
        if not isinstance(full_path_attr, str):
             raise ValueError("在 container.xml 的 <rootfile> 標籤中找不到 'full-path' 屬性。")

        opf_path = self.unzip_dir / full_path_attr
        if not opf_path.exists():
            raise FileNotFoundError(f"在 container.xml 指定的路徑中未找到OPF文件: {opf_path}")

        return opf_path

    def to_book(self) -> Book:
        """
        執行EPUB文件解析的主方法。
        
        返回:
            一个代表EPUB内容的 Book 对象。
        """
        # 第二階段: 解析 .opf 文件，獲取元數據、資源清單和閱讀順序
        if self.logger:
            self.logger.info("正在解析 OPF 文件...")
        self._parse_opf()

        # 第三階段: 解析每個章節文件，將HTML內容映射到我們的數據模型
        if self.logger:
            self.logger.info("正在解析章節內容...")
        self._parse_chapters()

        if self.logger:
            self.logger.info("解析完成。")
        return self.book

    def _parse_opf(self):
        """解析 .opf 文件以填充元數據、資源和章節順序。"""
        with open(self.opf_path, 'r', encoding='utf-8') as f:
            opf_soup = BeautifulSoup(f, 'xml')

        # 1. 解析元數據 <metadata>
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
        
        # 2. 解析資源清單 <manifest>
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
                    print(f"警告: 在manifest中聲明的文件未找到: {full_path}")
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
        
        # 創建 href 到 manifest 條目的反向映射，方便後續查找
        self.href_to_manifest_item = {v['href']: v for v in self.manifest_items.values() if 'href' in v}

        # 4. 解析導航文件以獲取章節標題和類型
        if isinstance(manifest_tag, Tag):
            self._parse_nav(opf_soup, manifest_tag)
        else:
            print("警告: 在 OPF 文件中未找到 <manifest> 標籤，無法解析導航。")

        # 3. 解析閱讀順序 <spine>
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
        """安全地從父標籤中獲取子標籤的文本內容。"""
        tag = parent_tag.find(tag_name)
        return tag.text.strip() if isinstance(tag, Tag) and tag.text else ""

    def _get_cover_image_id(self, metadata_tag: Tag) -> Optional[str]:
        """從元數據中找到封面圖片的ID。"""
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
        解析導航文件 (nav.xhtml 或 toc.ncx) 來獲取章節標題和語義類型。
        此方法現在更具魯棒性，可以處理兩種常見的目錄格式。
        """
        nav_item = manifest_tag.find('item', {'properties': 'nav'})
        if not isinstance(nav_item, Tag):
            nav_item = manifest_tag.find('item', {'media-type': 'application/x-dtbncx+xml'})
        
        if not isinstance(nav_item, Tag):
            print("警告: 未在 manifest 中找到導航文件 (nav.xhtml 或 toc.ncx)。")
            return

        nav_href = nav_item.get('href')
        if not isinstance(nav_href, str):
            print(f"警告: 導航文件 item 缺少有效的 href 屬性。")
            return
            
        nav_path = self.content_dir / nav_href
        if not nav_path.exists():
            print(f"警告: 導航文件 '{nav_path}' 不存在。")
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
        遍歷所有已識別的章節，解析其HTML內容。
        """
        for chapter in self.book.chapters:
            chapter_href = chapter.id
            if chapter_href not in self.href_to_manifest_item:
                print(f"警告: 無法在 manifest 中找到章節 href '{chapter_href}' 對應的文件。")
                continue

            chapter_info = self.href_to_manifest_item[chapter_href]
            chapter_path_any = chapter_info.get("path")

            if not isinstance(chapter_path_any, pathlib.Path) or not chapter_path_any.exists():
                print(f"警告: 章節文件路徑無效或文件不存在: {chapter_path_any}")
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

                block = html_mapper.map_tag_to_block(tag, chapter_base_dir, self.content_dir, self.book.image_resources)
                if block:
                    if isinstance(block, list):
                        blocks.extend(block)
                    else:
                        blocks.append(block)

            chapter.content = blocks

    def __del__(self):
        """在對象銷毀時清理臨時目錄。"""
        if hasattr(self, 'temp_dir'):
            self.temp_dir.cleanup()
            print(f"已清理臨時目錄: {self.unzip_dir}")

def epub_to_book(epub_path: str, logger) -> Book:
    """
    一个辅助函数，用于快速将EPUB文件转换为Book对象。
    """
    # 这里我们实例化新的、符合接口的类
    parser = EpubParser(epub_path, logger=logger)
    # 调用符合接口的方法
    return parser.to_book()