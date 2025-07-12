import logging
import os
import zipfile
from pathlib import Path
from genai_processors import processor
from workflows.book.parts import TranslatedBookPart
from common_utils.output_manager import OutputManager

class EpubWritingProcessor(processor.Processor):
    """
    一個接收 TranslatedBookPart 並將其寫入為 .epub 文件的處理器。
    這個版本手動創建 EPUB 結構，以確保最大的可控性。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def _create_container_xml(self) -> str:
        return """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

    def _create_content_opf(self, title: str, author: str, chapters: list) -> str:
        manifest_items = ""
        spine_items = ""
        for i, chapter in enumerate(chapters):
            safe_id = f"chap_{i+1}"
            chapter_filename = chapter.get("file_name", f"{safe_id}.xhtml")
            manifest_items += f'<item id="{safe_id}" href="{chapter_filename}" media-type="application/xhtml+xml"/>'
            spine_items += f'<itemref idref="{safe_id}"/>'

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{title}</dc:title>
    <dc:creator opf:role="aut">{author}</dc:creator>
    <dc:language>en</dc:language>
    <meta name="cover" content="cover-image" />
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"/>
    {manifest_items}
  </manifest>
  <spine toc="ncx">
    {spine_items}
  </spine>
</package>
"""

    def _create_toc_ncx(self, title: str, chapters: list) -> str:
        nav_points = ""
        for i, chapter in enumerate(chapters):
            safe_id = f"chap_{i+1}"
            chapter_filename = chapter.get("file_name", f"{safe_id}.xhtml")
            chapter_title = chapter.get("title", f"Chapter {i+1}")
            nav_points += f"""
            <navPoint id="navPoint-{i+1}" playOrder="{i+1}">
                <navLabel><text>{chapter_title}</text></navLabel>
                <content src="{chapter_filename}"/>
            </navPoint>
            """

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<ncx version="2005-1" xmlns="http://www.daisy.org/z3986/2005/ncx/">
  <head>
    <meta name="dtb:uid" content="bookid"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>{title}</text></docTitle>
  <navMap>
    {nav_points}
  </navMap>
</ncx>
"""
    
    def _create_nav_html(self, title: str, chapters: list) -> str:
        """手動創建 nav.xhtml 的內容。"""
        nav_list = ""
        for i, chapter in enumerate(chapters):
            safe_id = f"chap_{i+1}"
            chapter_filename = chapter.get("file_name", f"{safe_id}.xhtml")
            chapter_title = chapter.get("title", "Untitled")
            nav_list += f'<li><a href="{chapter_filename}">{chapter_title}</a></li>'
        
        return f"""
        <html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
        <head>
            <title>{title}</title>
        </head>
        <body>
            <nav epub:type="toc">
                <h2>Table of Contents</h2>
                <ol>
                    {nav_list}
                </ol>
            </nav>
        </body>
        </html>
        """

    async def call(self, stream):
        async for part in stream:
            if not isinstance(part, TranslatedBookPart):
                yield part
                continue

            self.logger.info(f"Writing translated book to EPUB file: {part.title}")

            try:
                output_dir = part.metadata.get("output_dir", "GlobalWorkflowOutputs")
                original_filename = Path(part.metadata.get("original_file", "book.epub")).stem
                target_lang = part.metadata.get("target_lang", "lang")
                output_filename = f"{original_filename}_{target_lang}.epub"
                
                output_manager = OutputManager(output_dir, self.logger)
                output_path = output_manager.get_workflow_output_path("epub_translated", output_filename)

                with zipfile.ZipFile(output_path, 'w') as epub_zip:
                    # mimetype file (must be first and uncompressed)
                    epub_zip.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
                    
                    # META-INF/container.xml
                    epub_zip.writestr('META-INF/container.xml', self._create_container_xml())

                    # OEBPS/content.opf
                    epub_zip.writestr('OEBPS/content.opf', self._create_content_opf(part.title, part.author, part.translated_chapters))

                    # OEBPS/toc.ncx
                    epub_zip.writestr('OEBPS/toc.ncx', self._create_toc_ncx(part.title, part.translated_chapters))
                    
                    # OEBPS/nav.xhtml
                    epub_zip.writestr('OEBPS/nav.xhtml', self._create_nav_html(part.title, part.translated_chapters))

                    # Chapter files
                    for i, chapter_data in enumerate(part.translated_chapters):
                        safe_id = f"chap_{i+1}"
                        chapter_filename = chapter_data.get("file_name", f"{safe_id}.xhtml")
                        epub_zip.writestr(f'OEBPS/{chapter_filename}', f'<?xml version="1.0" encoding="utf-8"?><!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml"><head><title>{chapter_data.get("title", "")}</title></head><body>{chapter_data["translated_content"]}</body></html>')

                self.logger.info(f"Successfully wrote translated EPUB to: {output_path}")

            except Exception as e:
                self.logger.error(f"EPUB file writing failed: {e}", exc_info=True)