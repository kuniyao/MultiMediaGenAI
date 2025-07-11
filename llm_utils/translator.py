# llm_utils/translator.py (重构后)

import logging
import json
import config
from pathlib import Path
from dotenv import load_dotenv
import asyncio
from typing import Dict, Optional, Any, List, Tuple, Coroutine

# --- 新的导入 ---
from .base_client import BaseLLMClient
from .gemini_client import GeminiClient
# 在这里可以轻松地加入其他客户端
# from .openai_client import OpenAIClient 

from .prompt_builder import PromptBuilder # 仅导入 PromptBuilder

# --- 全局设置 ---
project_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=project_root / '.env')

# 在文件顶部定义，以便在多个函数中使用
PROMPT_CONFIG = {
    'json_batch': {'system': 'json_batch_system_prompt', 'user': 'json_batch_user_prompt', 'var_name': 'json_task_string'},
    'html_part': {'system': 'html_split_part_system_prompt', 'user': 'html_split_part_user_prompt', 'var_name': 'html_content'},
    'json_subtitle_batch': {'system': 'json_subtitle_system_prompt', 'user': 'json_subtitle_user_prompt', 'var_name': "json_task_string"}
}

class ModelInitializationError(Exception):
    """用于模型初始化期间错误的自定义异常。"""
    pass

# --- 客户端工厂 ---
def get_llm_client(client_name: str, logger: Optional[logging.Logger] = None) -> BaseLLMClient:
    """
    根据名称获取并返回一个 LLM 客户端实例。
    这是一个简单的工厂模式实现。
    """
    logger = logger or logging.getLogger(__name__)
    
    if client_name.lower() == "gemini":
        logger.info("正在创建 GeminiClient...")
        return GeminiClient(logger=logger)
    # elif client_name.lower() == "openai":
    #     logger.info("Creating OpenAIClient...")
    #     return OpenAIClient(logger=logger)
    else:
        logger.error(f"不支持的 LLM 客户端: {client_name}")
        raise ValueError(f"不支持的 LLM 客户端: {client_name}")

# --- 核心翻译器类 ---
class Translator:
    def __init__(self, logger: Optional[logging.Logger] = None, client_name: str = "gemini"):
        self.logger = logger if logger else logging.getLogger(__name__)
        self.prompts = self._load_prompts()
        # 通过工厂获取客户端
        self.client: BaseLLMClient = get_llm_client(client_name, self.logger)
        self._is_initialized = False

    async def initialize(self):
        """异步初始化翻译器及其底层的 LLM 客户端。"""
        if self._is_initialized:
            return
        try:
            self.logger.info(f"正在初始化 {self.client.__class__.__name__}...")
            await self.client.initialize()
            self._is_initialized = True
            self.logger.info(f"{self.client.__class__.__name__} 初始化成功。")
        except Exception as e:
            self.logger.critical(f"初始化 LLM 客户端失败: {e}", exc_info=True)
            raise ModelInitializationError(f"初始化 LLM 客户端失败: {e}")

    def _load_prompts(self) -> Dict:
        """从 prompts.json 加载提示。"""
        try:
            prompts_path = project_root / 'prompts.json'
            with open(prompts_path, 'r', encoding='utf-8') as f:
                prompts = json.load(f)
            self.logger.debug(f"成功从 {prompts_path} 加载提示。")
            return prompts
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.logger.critical(f"加载或解析 prompts.json 失败: {e}")
            raise

    async def translate_chapters_async(
        self, 
        chapter_tasks: list, 
        messages_list: List[List[Dict[str, Any]]], # 1. 接收预先构建好的消息列表
        concurrency_limit: int
    ) -> tuple[list, list]:
        """
        使用配置的 LLM 客户端并发翻译章节任务。
        此版本直接使用预先构建好的消息。
        """
        if not self._is_initialized:
            await self.initialize()

        semaphore = asyncio.Semaphore(concurrency_limit)
        
        # 将任务和消息配对
        tasks_with_messages = list(zip(chapter_tasks, messages_list))

        async def translate_task(task_with_message):
            task, prompt_messages = task_with_message
            async with semaphore:
                task_id = task['llm_processing_id']
                self.logger.info(f"准备任务 (ID: {task_id})...")
                
                # 2. 直接使用传入的消息，不再重新构建
                return await self.client.call_api_async(prompt_messages, task_id)

        # 3. 为配对好的任务创建异步tasks
        async_tasks = [translate_task(item) for item in tasks_with_messages]
        self.logger.info(f"正在以 {concurrency_limit} 的并发限制执行 {len(async_tasks)} 个翻译任务...")
        api_responses_tuples = await asyncio.gather(*async_tasks, return_exceptions=True)
        self.logger.info("所有并发任务已完成。")
        
        # --- 处理结果的逻辑保持不变 ---
        translated_results = []
        raw_llm_log_strings = []
        for task, response_or_exc in zip(chapter_tasks, api_responses_tuples):
            task_id = task['llm_processing_id']
            translated_text = f"[TRANSLATION_FAILED] 任务 {task_id} 的原始内容已保留。"
            log_string = None

            if isinstance(response_or_exc, tuple):
                response_text, log_string = response_or_exc
                if response_text:
                    translated_text = response_text
            elif isinstance(response_or_exc, Exception):
                self.logger.error(f"任务 {task_id} 在 API 调用中遇到异常: {response_or_exc}", exc_info=True)
                log_entry = {"task_id": task_id, "response_text": f"Exception: {str(response_or_exc)}"}
                log_string = json.dumps(log_entry, ensure_ascii=False)

            translated_results.append({
                "llm_processing_id": task_id,
                "translated_text": translated_text,
                "source_data": task['source_data']
            })
            if log_string:
                raw_llm_log_strings.append(log_string)
            
        return translated_results, raw_llm_log_strings

async def execute_translation_async(
    tasks_to_translate: List[Dict[str, Any]],
    source_lang_code: str,
    target_lang: str,
    logger: logging.Logger
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    logger_to_use = logger if logger else logging.getLogger(__name__)
    
    try:
        # 实例化 Translator 时传入客户端名称
        translator = Translator(logger=logger_to_use, client_name="gemini") # 假设默认使用 gemini
        # 异步初始化
        await translator.initialize()

        logger_to_use.info(f"开始对 {len(tasks_to_translate)} 个任务进行从 '{source_lang_code}' 到 '{target_lang}' 的异步翻译...")
        
        # 使用新的 PromptBuilder 构建所有需要的提示
        try:
            builder = PromptBuilder(source_lang_code, target_lang)
            
            # 识别任务类型并构建消息
            first_task_id = tasks_to_translate[0].get("llm_processing_id", "")
            
            task_type = "unknown"
            if "json_subtitle_batch" in first_task_id:
                task_type = "json_subtitle_batch"
            elif "json_batch" in first_task_id:
                task_type = "json_batch"
            elif "html_part" in first_task_id:
                task_type = "html_part"

            if task_type == "unknown":
                raise ValueError(f"Could not determine task type from ID: {first_task_id}")

            messages_to_send = [
                builder.build_messages(
                    task_type=task_type,
                    task_string=task['text_to_translate']
                )
                for task in tasks_to_translate
            ]
            logger_to_use.info(f"Successfully built {len(messages_to_send)} message sets for task type '{task_type}'.")
        except Exception as e:
            logger_to_use.error(f"Failed to build prompts for translation: {e}", exc_info=True)
            return [], [{"task_id": "all", "error": str(e), "success": False}]

        # 4. 将构建好的消息传递给底层函数
        translated_results, raw_llm_log_strings = await translator.translate_chapters_async(
            chapter_tasks=tasks_to_translate,
            messages_list=messages_to_send, # 传递消息
            concurrency_limit=5
        )

        if not translated_results:
            logger_to_use.error("翻译失败或未返回任何结果。")
            return [], raw_llm_log_strings
        
        logger_to_use.info("翻译任务成功完成。")
        return translated_results, raw_llm_log_strings

    except (ModelInitializationError, Exception) as e:
        # 统一处理所有异常，包括凭证错误和模型初始化失败
        logger_to_use = logger if logger else logging.getLogger(__name__)
        # 根据异常类型定制日志消息
        if isinstance(e, ModelInitializationError):
            logger_to_use.critical(f"无法执行翻译，因为模型初始化失败: {e}", exc_info=True)
        else:
            logger_to_use.critical(f"无法执行翻译，因为模型初始化或执行期间发生意外错误: {e}", exc_info=True)
        
        # 修正：返回一个空列表而不是 None，以匹配函数签名
        return [], []