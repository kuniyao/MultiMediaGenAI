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
        return None
    
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
        return None

class Translator:
    def __init__(self, logger=None, prompts: Optional[Dict] = None):
        self.logger = logger if logger else logging.getLogger(__name__)
        self.prompts = prompts if prompts else {}
        self.model = self._initialize_model()

    def _initialize_model(self):
        # 根據任務類型可能需要不同的 client，這裡暫時簡化
        # 對於 split_part 任務，我們需要的是 text/plain
        # 對於 json_batch 任務，我們需要的是 application/json
        # 暫時使用一個通用的，如果後續 API 嚴格要求，需要調整
        model_client = get_model_client(self.logger)
        return model_client

    async def _call_gemini_api_async(self, messages: list, log_file_path: str | None, task_id: str, semaphore: asyncio.Semaphore) -> str | None:
        async with semaphore:
            if not self.model:
                self.logger.error(f"Model is not initialized. Cannot call API for task {task_id}.")
                return None
            
            try:
                self.logger.debug(f"Requesting translation for task {task_id}...")
                # 注意：現在傳遞的是一個 messages 列表
                response = await self.model.generate_content_async(messages, request_options={'timeout': 300})
                raw_text = response.text
                self.logger.debug(f"Received response for task {task_id}.")
            except Exception as e:
                self.logger.error(f"Error calling Gemini API for task {task_id}: {e}", exc_info=True)
                # ... (錯誤處理保持不變)
                return None
            
            if log_file_path and raw_text:
                with open(log_file_path, 'a', encoding='utf-8') as f:
                    log_entry = {"task_id": task_id, "response_text": raw_text}
                    f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            
            return raw_text

    async def translate_chapters_async(self, chapter_tasks: list, source_lang_code: str, target_lang: str, output_path: str | None, concurrency_limit: int, glossary: Optional[Dict[str, str]] = None):
        if not self.model:
            self.logger.error("Gemini model not initialized. Skipping translation.")
            return []

        raw_llm_log_file = os.path.join(output_path, f"llm_raw_responses_{target_lang.lower().replace('-', '_')}.jsonl") if output_path else None
        
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

            if task_type == 'json_batch':
                system_prompt_template = self.prompts.get('json_batch_system_prompt')
                user_prompt_template = self.prompts.get('json_batch_user_prompt')
                variables["json_task_string"] = task['text_to_translate']
            elif task_type == 'split_part':
                system_prompt_template = self.prompts.get('html_split_part_system_prompt')
                user_prompt_template = self.prompts.get('html_split_part_user_prompt')
                variables["html_content"] = task['text_to_translate']
            else:
                self.logger.warning(f"Unknown task type '{task_type}' for task ID {task_id}. Skipping.")
                continue

            prompt_messages = build_prompt_from_template(
                system_prompt_template,
                user_prompt_template,
                variables,
                glossary,
                self.prompts.get('glossary_injection_template')
            )
            
            async_tasks.append(
                self._call_gemini_api_async(prompt_messages, raw_llm_log_file, task_id, semaphore)
            )

        self.logger.info(f"Executing {len(async_tasks)} translation tasks concurrently with a limit of {concurrency_limit}...")
        api_responses = await asyncio.gather(*async_tasks)
        self.logger.info("All concurrent tasks have been completed.")
        
        translated_results = []
        for task, response_text in zip(chapter_tasks, api_responses):
            task_id = task['llm_processing_id']
            source_data = task['source_data']
            task_type = source_data.get('type')
            
            translated_text = f"[TRANSLATION_FAILED] Original content preserved for task {task_id}."
            
            if response_text:
                # 對於 split_part 和 json_batch，我們現在都期望直接的文本/JSON string
                translated_text = response_text
            
            translated_results.append({
                "llm_processing_id": task_id,
                "translated_text": translated_text,
                "source_data": source_data
            })
            
        return translated_results

async def execute_translation_async(
    pre_translate_json_list: list, 
    source_lang_code: str, 
    target_lang: str, 
    video_specific_output_path: str | None = None, 
    logger: logging.Logger | None = None,
    concurrency: int = 10,
    prompts: Optional[Dict] = None,      # <-- 接收 prompts
    glossary: Optional[Dict[str, str]] = None # <-- 接收 glossary
) -> list | None:
    logger_to_use = logger if logger else logging.getLogger(__name__)
    translator = Translator(logger=logger_to_use, prompts=prompts)

    logger_to_use.info(f"Starting async chapter-by-chapter translation from '{source_lang_code}' to '{target_lang}'...")
    
    translated_json_objects = await translator.translate_chapters_async(
        chapter_tasks=pre_translate_json_list,
        source_lang_code=source_lang_code,
        target_lang=target_lang,
        output_path=video_specific_output_path,
        concurrency_limit=concurrency,
        glossary=glossary # <-- 傳入 glossary
    )

    if not translated_json_objects:
        logger_to_use.error("Translation failed or returned no results.")
        return None
        
    if len(translated_json_objects) != len(pre_translate_json_list):
        logger_to_use.critical(f"CRITICAL: Task count mismatch! Input tasks: {len(pre_translate_json_list)}, Output results: {len(translated_json_objects)}")
        return None
    
    logger_to_use.info("Task count integrity check passed.")
    return translated_json_objects