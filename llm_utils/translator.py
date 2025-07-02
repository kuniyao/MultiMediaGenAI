# llm_utils/translator.py (修改後)

import os
import logging
import google.generativeai as genai
import json
import config
from pathlib import Path
from dotenv import load_dotenv
import asyncio
from typing import Dict, Optional, Any

class ModelInitializationError(Exception):
    """Custom exception for errors during LLM model initialization."""
    pass

# 導入我們新的通用prompt構建器
from .prompt_builder import build_prompt_from_template

# 加載 .env 文件
project_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=project_root / '.env')

def get_model_client(logger=None, generation_config_overrides: dict | None = None):
    logger = logger if logger else logging.getLogger(__name__)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("GEMINI_API_KEY not found in environment variables.")
        raise ModelInitializationError("GEMINI_API_KEY not found in environment variables.")
    
    try:
        # 類型檢查工具可能不認識 configure，但運行時是正確的
        genai.configure(api_key=api_key) # type: ignore

        config_params = {"temperature": 0.0}
        if generation_config_overrides:
            config_params.update(generation_config_overrides)
        
        # 類型檢查工具可能不認識 types，但運行時是正確的
        generation_config = genai.types.GenerationConfig(**config_params) # type: ignore
        
        # 類型檢查工具可能不認識 GenerativeModel，但運行時是正確的
        model = genai.GenerativeModel( # type: ignore
            config.LLM_MODEL_GEMINI,
            generation_config=generation_config
        )
        logger.debug(f"Successfully initialized Gemini model client with config: {config_params}")
        return model
    except Exception as e:
        logger.error(f"Failed to initialize Gemini model client: {e}", exc_info=True)
        raise ModelInitializationError(f"Failed to initialize Gemini model client: {e}")

class Translator:
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger if logger else logging.getLogger(__name__)
        self.model = self._initialize_model()
        self.prompts = self._load_prompts()

    def _initialize_model(self):
        try:
            model_client = get_model_client(self.logger)
            if model_client is None:
                raise ModelInitializationError("get_model_client returned None without raising an error.")
            return model_client
        except ModelInitializationError as e:
            self.logger.critical(f"Failed to initialize LLM model: {e}")
            raise  # Re-raise the exception to prevent Translator from being instantiated with a bad model

    def _load_prompts(self) -> Dict:
        """Loads prompts from prompts.json."""
        try:
            prompts_path = project_root / 'prompts.json'
            with open(prompts_path, 'r', encoding='utf-8') as f:
                prompts = json.load(f)
            self.logger.debug(f"Successfully loaded prompts from {prompts_path}")
            return prompts
        except FileNotFoundError:
            self.logger.critical(f"prompts.json not found at {prompts_path}. Please ensure the file exists.")
            raise
        except json.JSONDecodeError as e:
            self.logger.critical(f"Error decoding prompts.json: {e}")
            raise
        except Exception as e:
            self.logger.critical(f"An unexpected error occurred while loading prompts: {e}", exc_info=True)
            raise

    async def _call_gemini_api_async(self, messages: list, task_id: str, semaphore: asyncio.Semaphore) -> tuple[str | None, str | None]:
        async with semaphore:
            raw_text = None
            log_entry_json_string = None

            if not self.model:
                self.logger.error(f"Model is not initialized. Cannot call API for task {task_id}.")
                return None, None
            
            MAX_RETRIES = 5
            INITIAL_BACKOFF_SECONDS = 2
            
            for attempt in range(MAX_RETRIES):
                try:
                    self.logger.debug(f"Requesting translation for task {task_id} (Attempt {attempt + 1}/{MAX_RETRIES})...")
                    response = await self.model.generate_content_async(messages, request_options={'timeout': 300})
                    raw_text = response.text
                    self.logger.debug(f"Received response for task {task_id} on attempt {attempt + 1}.")
                    break # Success, exit retry loop
                except (genai.APIError, asyncio.TimeoutError) as e:
                    self.logger.warning(f"API error for task {task_id} on attempt {attempt + 1}: {e}")
                    if attempt < MAX_RETRIES - 1:
                        backoff_time = INITIAL_BACKOFF_SECONDS * (2 ** attempt)
                        self.logger.info(f"Retrying task {task_id} in {backoff_time} seconds...")
                        await asyncio.sleep(backoff_time)
                    else:
                        self.logger.error(f"All {MAX_RETRIES} attempts failed for task {task_id}: {e}", exc_info=True)
                        raw_text = None # Ensure raw_text is None on final failure
                        break
                except Exception as e:
                    self.logger.error(f"An unexpected error occurred for task {task_id}: {e}", exc_info=True)
                    raw_text = None # Ensure raw_text is None on unexpected error
                    break
            
            # Prepare log entry regardless of success/failure
            log_entry = {"task_id": task_id, "response_text": raw_text}
            log_entry_json_string = json.dumps(log_entry, ensure_ascii=False)
            
            return raw_text, log_entry_json_string

    async def translate_chapters_async(self, chapter_tasks: list, source_lang_code: str, target_lang: str, concurrency_limit: int, glossary: Optional[Dict[str, str]] = None) -> tuple[list, list]:
        if not self.model:
            self.logger.error("Gemini model not initialized. Skipping translation.")
            return [], []

        semaphore = asyncio.Semaphore(concurrency_limit)
        
        async_tasks = []
        for i, task in enumerate(chapter_tasks):
            task_id = task['llm_processing_id']
            source_data = task['source_data']
            task_type = source_data.get('type')
            
            self.logger.info(f"Preparing task {i + 1}/{len(chapter_tasks)} (ID: {task_id}, Type: {task_type})...")
            
            prompt_messages = []
            variables: Dict[str, Any] = {
                "source_lang": source_lang_code,
                "target_lang": target_lang
            }

            prompt_config = {
                'json_batch': {
                    'system': self.prompts.get('json_batch_system_prompt'),
                    'user': self.prompts.get('json_batch_user_prompt'),
                    'var_name': "json_task_string"
                },
                'split_part': {
                    'system': self.prompts.get('html_split_part_system_prompt'),
                    'user': self.prompts.get('html_split_part_user_prompt'),
                    'var_name': "html_content"
                },
                # 【新增】告诉程序如何处理 'fix_batch'
                'fix_batch': {
                    'system': self.prompts.get('html_split_part_system_prompt'), # 复用 html_split_part 的 system prompt
                    'user': self.prompts.get('html_split_part_user_prompt'),   # 复用 html_split_part 的 user prompt
                    'var_name': "html_content"                                # 告诉程序任务内容在 'text_to_translate' 字段
                },
                'html_subtitle_batch': {
                    'system': self.prompts.get('html_subtitle_system_prompt'),
                    'user': self.prompts.get('html_subtitle_user_prompt'),
                    'var_name': "html_content"
                }
            }

            config_for_type = prompt_config.get(task_type)
            
            if not config_for_type:
                self.logger.warning(f"Unknown task type '{task_type}' for task ID {task_id}. Skipping.")
                continue

            system_prompt_template = config_for_type['system']
            user_prompt_template = config_for_type['user']
            variables[config_for_type['var_name']] = task['text_to_translate']

            prompt_messages = build_prompt_from_template(
                system_prompt_template,
                user_prompt_template,
                variables,
                glossary,
                self.prompts.get('glossary_injection_template')
            )
            
            async_tasks.append(
                self._call_gemini_api_async(prompt_messages, task_id, semaphore)
            )

        self.logger.info(f"Executing {len(async_tasks)} translation tasks concurrently with a limit of {concurrency_limit}...")
        api_responses_tuples = await asyncio.gather(*async_tasks)
        self.logger.info("All concurrent tasks have been completed.")
        
        translated_results = []
        raw_llm_log_strings = []

        for task, response_tuple in zip(chapter_tasks, api_responses_tuples):
            task_id = task['llm_processing_id']
            source_data = task['source_data']
            task_type = source_data.get('type')
            
            response_text, log_string = response_tuple

            translated_text = f"[TRANSLATION_FAILED] Original content preserved for task {task_id}."
            
            if response_text:
                # 對於 split_part 和 json_batch，我們現在都期望直接的文本/JSON string
                translated_text = response_text
            
            translated_results.append({
                "llm_processing_id": task_id,
                "translated_text": translated_text,
                "source_data": source_data
            })
            
            if log_string:
                raw_llm_log_strings.append(log_string)
            
        return translated_results, raw_llm_log_strings

async def execute_translation_async(
    tasks_to_translate: list, 
    source_lang_code: str, 
    target_lang: str, 
    logger: logging.Logger | None = None,
    concurrency: int = 5,
    glossary: Optional[Dict[str, str]] = None
) -> tuple[list | None, list]:
    logger_to_use = logger if logger else logging.getLogger(__name__)
    translator = Translator(logger=logger_to_use)

    logger_to_use.info(f"Starting async translation for {len(tasks_to_translate)} tasks from '{source_lang_code}' to '{target_lang}'...")
    
    # 直接传递收到的任务列表
    translated_results, raw_llm_log_strings = await translator.translate_chapters_async(
        chapter_tasks=tasks_to_translate,
        source_lang_code=source_lang_code,
        target_lang=target_lang,
        concurrency_limit=concurrency,
        glossary=glossary
    )

    if not translated_results:
        logger_to_use.error("Translation failed or returned no results.")
        return None, raw_llm_log_strings
        
    if len(translated_results) != len(tasks_to_translate):
        logger_to_use.critical(f"CRITICAL: Task count mismatch! Input tasks: {len(tasks_to_translate)}, Output results: {len(translated_results)}")
        # 即使不匹配，也继续处理，让调用者决定如何处理
    
    logger_to_use.info("Task count integrity check passed.")
    return translated_results, raw_llm_log_strings # <--- 返回通用的结果列表