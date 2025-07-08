# 处理器6：写入文件
from ..base_processor import BaseProcessor
from workflows.dto import PipelineContext
from common_utils.output_manager import OutputManager
from common_utils.file_helpers import sanitize_filename
from pathlib import Path
import logging

class FileWriteProcessor(BaseProcessor):
    """
    处理器第六步（终点）：将最终生成的内容写入文件，处理文件IO的副作用。
    """
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def process(self, context: PipelineContext) -> PipelineContext:
        # 这是管道的终点，可以直接修改上下文，无需创建副本
        if not context.is_successful:
            self.logger.warning("Skipping file writing because the pipeline failed in a previous step.")
            return context

        self.logger.info("Writing final output to files...")
        try:
            # 构造一个任务专用的输出管理器
            sanitized_title = sanitize_filename(context.source_metadata.get("title", "untitled_task"))
            task_output_dir = Path(context.output_dir) / sanitized_title
            output_manager = OutputManager(str(task_output_dir), self.logger)
            
            # 写入 SRT 文件
            if context.final_srt_content:
                file_basename = sanitize_filename(context.source_metadata.get("title", "translation"))
                srt_path = output_manager.get_workflow_output_path("subtitle", f"{file_basename}_{context.target_lang}.srt")
                output_manager.save_file(srt_path, context.final_srt_content)
                self.logger.info(f"Final SRT file saved to: {srt_path}")

            # 可以在这里扩展，比如写入最终的 Markdown 对照文件等
            
            # 写入LLM日志（如果需要）
            if context.llm_logs: # 这里可以根据配置增加更复杂的判断逻辑
                 log_file_name = f"llm_raw_responses_{context.target_lang.lower().replace('-','').replace('_','')}.jsonl"
                 log_file_path = output_manager.get_workflow_output_path("llm_logs", log_file_name)
                 try:
                     with open(log_file_path, 'w', encoding='utf-8') as f:
                         for log_entry in context.llm_logs:
                             f.write(log_entry + '\n')
                     self.logger.info(f"LLM raw response logs saved to: {log_file_path}")
                 except Exception as e:
                     self.logger.error(f"Failed to save LLM raw response logs: {e}", exc_info=True)

        except Exception as e:
            self.logger.error(f"Failed during file writing process: {e}", exc_info=True)
            context.is_successful = False
            context.error_message = f"File writing failed: {e}"

        return context