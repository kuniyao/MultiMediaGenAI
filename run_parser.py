import json
import sys
import os
import traceback

# 将项目根目录添加到Python路径中，以便能够找到 format_converters 模块
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from format_converters.epub_parser import epub_to_book
from format_converters.epub_writer import book_to_epub
from format_converters.book_schema import Book

def main():
    # epub_file_path = "test_books/The Minimalist Entrepreneur.epub"
    epub_file_path = "/home/guts/下载/The Minimalist Entrepreneur _ How Great Founders Do More -- Sahil Lavingia.epub"
    json_output_path = "parsed_book.json"
    epub_output_path = "output.epub"

    # --- 步骤 1: 解析 EPUB -> JSON ---
    print("="*20)
    print(f"开始解析EPUB文件: {epub_file_path}")
    print("="*20)
    
    # 将 EPUB 文件解析为 Book 对象
    book_object = epub_to_book(epub_file_path)

    # 将 Book 对象序列化为 JSON 字符串
    # Pydantic 的 model_dump_json 方法可以很好地处理所有内嵌模型
    json_data = book_object.model_dump_json(indent=2)
    
    # 将 JSON 字符串写入文件
    with open(json_output_path, 'w', encoding='utf-8') as f:
        f.write(json_data)
    
    print(f"\n书籍已成功解析并保存到: {json_output_path}")


    # --- 步骤 2: 从 JSON 反序列化回 Book 对象并重新生成 EPUB ---
    # 这一步验证我们的整个流程是否闭环
    print("\n" + "="*20)
    print("开始从JSON文件重新构建EPUB")
    print("="*20)

    # 从 JSON 文件加载数据
    with open(json_output_path, 'r', encoding='utf-8') as f:
        loaded_json_data = json.load(f)
    
    # 将 JSON 数据反序列化为 Book 对象
    # 注意：这里我们使用 Pydantic 的 model_validate 来处理解码
    rehydrated_book = Book.model_validate(loaded_json_data)

    # 调用写入器来生成新的 EPUB 文件
    book_to_epub(rehydrated_book, epub_output_path)
    
    print(f"\n书籍已从JSON成功重建并保存到: {epub_output_path}")


if __name__ == "__main__":
    main() 