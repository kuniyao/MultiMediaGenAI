from abc import ABC, abstractmethod
from typing import List, Tuple, Dict, Optional
import logging

class BaseLLMClient(ABC):
    """
    所有 LLM 客户端的抽象基类，定义了统一的接口。
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        初始化客户端，并设置日志记录器。

        Args:
            logger: 一个可选的日志记录器实例。
        """
        self.logger = logger if logger else logging.getLogger(self.__class__.__name__)
        self.model = None

    @abstractmethod
    async def initialize(self, **kwargs):
        """
        异步初始化客户端，加载 API 密钥、设置会话等。
        每个具体的客户端都需要实现这个方法。
        """
        pass

    @abstractmethod
    async def call_api_async(self, messages: List[Dict[str, str]], task_id: str) -> Tuple[Optional[str], Optional[str]]:
        """
        异步调用底层的大模型 API。

        Args:
            messages (List[Dict[str, str]]): 发送给模型的提示信息列表。
            task_id (str): 任务的唯一标识符，用于日志记录。

        Returns:
            一个元组，包含:
            - API 返回的原始文本响应 (str 或 None)。
            - 用于日志记录的原始响应 JSON 字符串 (str 或 None)。
        """
        pass 