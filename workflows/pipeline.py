# 新的管道执行器
from typing import List
from processors.base_processor import BaseProcessor
from workflows.dto import PipelineContext
import inspect

class Pipeline:
    def __init__(self, processors: List[BaseProcessor], logger):
        self._processors = processors
        self.logger = logger

    async def run(self, context: PipelineContext) -> PipelineContext:
        self.logger.info("--- Starting Async Pipeline Execution ---")
        current_context = context
        
        for processor in self._processors:
            processor_name = processor.__class__.__name__
            self.logger.info(f"Executing processor: {processor_name}...")
            
            # 【修改2】: 检查处理器是同步还是异步，并相应地调用
            if inspect.iscoroutinefunction(processor.process):
                current_context = await processor.process(current_context)
            else:
                current_context = processor.process(current_context)
            
            if not current_context.is_successful:
                self.logger.error(f"Pipeline failed at processor '{processor_name}'. Reason: {current_context.error_message}")
                break
        
        self.logger.info("--- Pipeline Execution Finished ---")
        return current_context