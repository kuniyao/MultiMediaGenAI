import logging
from pathlib import Path

from genai_processors import processor
from workflows.parts import TranslationRequestPart
import config

class LogSetupProcessor(processor.Processor):
    """
    一个在工作流开始时设置文件日志的处理器。
    它捕获第一个 Part，从中提取元数据来构建特定于任务的日志文件路径，
    然后为根日志记录器配置一个文件处理器。
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._is_configured = False

    async def call(self, stream):
        """
        处理流，仅对第一个 Part 操作一次。
        """
        async for part in stream:
            if not self._is_configured and isinstance(part, TranslationRequestPart):
                try:
                    # 1. 从 Part 元数据构建日志路径
                    output_dir = Path(part.metadata.get("output_dir", "GlobalWorkflowOutputs"))
                    original_file = Path(part.metadata.get("original_file", "unknown_task.log"))
                    workflow_dirname = original_file.stem
                    
                    log_dir = output_dir / workflow_dirname
                    log_dir.mkdir(parents=True, exist_ok=True)
                    log_file_path = log_dir / "processing.log"

                    # 2. 获取根日志记录器并添加文件处理器
                    root_logger = logging.getLogger("RootLogger")
                    
                    # 检查是否已存在同名处理器，避免重复添加
                    handler_exists = any(
                        isinstance(h, logging.FileHandler) and h.baseFilename == str(log_file_path)
                        for h in root_logger.handlers
                    )
                    
                    if not handler_exists:
                        file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
                        log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                        formatter = logging.Formatter(log_format)
                        file_handler.setFormatter(formatter)
                        
                        # 设置文件处理器应记录的最低级别
                        # 这里我们硬编码为DEBUG，以确保文件中包含所有信息
                        file_handler.setLevel(logging.DEBUG) 
                        
                        root_logger.addHandler(file_handler)
                        self.logger.info(f"Task-specific file logging configured at: {log_file_path}")
                    
                    self._is_configured = True

                except Exception as e:
                    self.logger.error(f"Failed to configure task-specific logging: {e}", exc_info=True)
            
            # 无论如何都要将 Part 传递下去
            yield part 