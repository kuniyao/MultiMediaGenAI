from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

# 為了避免在運行時產生循環導入，我們使用 TYPE_CHECKING
# 這讓靜態檢查工具（如 Mypy）和 IDE 知道 Book 是什麼型別
# 但在實際運行時，這段 import 不會被執行
if TYPE_CHECKING:
    from .book_schema import Book

class BaseInputConverter(ABC):
    """
    輸入轉換器的抽象基類 (合約)。

    它規定任何繼承它的類別，都必須能夠將一種源格式轉換為 Book 物件，
    方法是實現一個名為 to_book 的方法。
    """
    
    @abstractmethod
    def to_book(self) -> "Book":
        """
        將源文件解析並轉換為一個標準的 Book 物件。
        
        這是一個抽象方法，沒有任何實現邏輯。
        繼承此類別的子類別「必須」提供自己的 to_book 實現。
        """
        pass