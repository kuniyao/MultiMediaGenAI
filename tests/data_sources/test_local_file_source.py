import asyncio
import unittest
import tempfile
import os
from data_sources.local_file_source import LocalFileSource
from workflows.parts import FilePathPart, FileContentPart


class TestLocalFileSource(unittest.TestCase):

    def test_read_file_successfully(self):
        # 1. 準備：創建一個臨時文件和處理器實例
        content_to_write = "Hello, world!\nThis is a test file."
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp:
            tmp.write(content_to_write)
            tmp_path = tmp.name

        source_processor = LocalFileSource()

        # 2. 執行：創建輸入流並處理
        async def run_test():
            # 創建一個異步生成器作為輸入流
            async def input_stream_generator():
                yield FilePathPart(path=tmp_path)

            output_parts = []
            async for part in source_processor(input_stream_generator()):
                output_parts.append(part)
            return output_parts

        results = asyncio.run(run_test())

        # 3. 驗證：檢查輸出是否符合預期
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], FileContentPart)
        self.assertEqual(results[0].path, tmp_path)
        self.assertEqual(results[0].content, content_to_write)

        # 清理
        os.remove(tmp_path)

if __name__ == '__main__':
    unittest.main()
