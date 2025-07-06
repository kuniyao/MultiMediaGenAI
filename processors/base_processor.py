# 定义处理器接口
from abc import ABC, abstractmethod
from workflows.dto import PipelineContext # 我们将在下一步定义 DTO

class BaseProcessor(ABC):
    """处理管道中一个步骤的抽象基类。"""

    @abstractmethod
    def process(self, context: PipelineContext) -> PipelineContext:
        """
        接收包含所有需要数据的上下文对象，
        处理后返回一个更新了的上下文对象。
        """
        pass