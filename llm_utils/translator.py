# llm_utils/translator.py (修改後)

import os
import logging
import google.generativeai as genai
import json
import config
from pathlib import Path
from dotenv import load_dotenv
import asyncio # <--- 導入 asyncio

# 導入我們所有需要的prompt構建器
from .prompt_builder import build_html_translation_prompt, build_json_batch_translation_prompt

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
    def __init__(self, logger=None):
        self.logger = logger if logger else logging.getLogger(__name__)
        self.model = self._initialize_model()

    def _initialize_model(self):
        json_config_overrides = {"response_mime_type": "application/json"}
        model_client = get_model_client(
            self.logger, 
            generation_config_overrides=json_config_overrides
        )
        return model_client

    # 【修改點 1】將 _call_gemini_api 重構為非同步函式，並加入信號量控制
    async def _call_gemini_api_async(self, prompt: str, log_file_path: str | None, task_id: str, semaphore: asyncio.Semaphore) -> str | None:
        async with semaphore: # <--- 在請求前後獲取和釋放信號量
            if not self.model:
                self.logger.error(f"Model is not initialized. Cannot call API for task {task_id}.")
                return None
            
            try:
                # 【關鍵】使用 generate_content_async
                self.logger.debug(f"Requesting translation for task {task_id}...")
                response = await self.model.generate_content_async(prompt, request_options={'timeout': 300})
                raw_text = response.text
                self.logger.debug(f"Received response for task {task_id}.")
            except Exception as e:
                # 保持現有的健壯錯誤處理
                self.logger.error(f"Error calling Gemini API for task {task_id}: {e}", exc_info=True)
                finish_reason = "UNKNOWN"
                if hasattr(e, '__cause__') and hasattr(e.__cause__, 'candidate') and getattr(e.__cause__, 'candidate', None):
                    candidate = getattr(e.__cause__, 'candidate')
                    finish_reason = str(getattr(candidate, 'finish_reason', 'UNKNOWN'))
                self.logger.error(f"API call for {task_id} failed with finish_reason: {finish_reason}")
                return None
            
            if log_file_path and raw_text:
                with open(log_file_path, 'a', encoding='utf-8') as f:
                    log_entry = {"task_id": task_id, "response_text": raw_text}
                    f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
            
            return raw_text

    # 【修改點 2】將 translate_chapters 重構為非同步函式
    async def translate_chapters_async(self, chapter_tasks: list, source_lang_code: str, target_lang: str, output_path: str | None, concurrency_limit: int) -> list:
        if not self.model:
            self.logger.error("Gemini model not initialized. Skipping translation.")
            return []

        raw_llm_log_file = os.path.join(output_path, f"llm_raw_responses_{target_lang.lower().replace('-', '_')}.jsonl") if output_path else None
        
        # 創建信號量以限制併發數
        semaphore = asyncio.Semaphore(concurrency_limit)
        
        async_tasks = []
        for i, task in enumerate(chapter_tasks):
            task_id = task['llm_processing_id']
            source_data = task['source_data']
            task_type = source_data.get('type')
            prompt = ""
            
            self.logger.info(f"Preparing task {i + 1}/{len(chapter_tasks)} (ID: {task_id}, Type: {task_type})...")

            if task_type == 'json_batch':
                prompt = build_json_batch_translation_prompt(task['text_to_translate'], source_lang_code, target_lang)
            elif task_type == 'split_part':
                prompt = build_html_translation_prompt(task['text_to_translate'], source_lang_code, target_lang)
            else:
                self.logger.warning(f"Unknown task type '{task_type}' for task ID {task_id}. Skipping.")
                continue
            
            # 將非同步 API 呼叫添加到任務列表
            async_tasks.append(
                self._call_gemini_api_async(prompt, raw_llm_log_file, task_id, semaphore)
            )

        # 【關鍵】使用 asyncio.gather 并發執行所有任務
        self.logger.info(f"Executing {len(async_tasks)} translation tasks concurrently with a limit of {concurrency_limit}...")
        api_responses = await asyncio.gather(*async_tasks)
        self.logger.info("All concurrent tasks have been completed.")
        
        # 處理返回的結果
        translated_results = []
        for task, response_text in zip(chapter_tasks, api_responses):
            task_id = task['llm_processing_id']
            source_data = task['source_data']
            task_type = source_data.get('type')
            
            translated_text = f"[TRANSLATION_FAILED] Original content preserved for task {task_id}."
            
            if response_text:
                if task_type == 'split_part':
                    try:
                        response_json = json.loads(response_text)
                        translated_text = response_json.get("translated_html", translated_text)
                    except json.JSONDecodeError:
                        self.logger.warning(f"JSONDecodeError for split_part task {task_id}. Assuming raw HTML response.")
                        translated_text = response_text
                
                elif task_type == 'json_batch':
                    try:
                        json.loads(response_text) 
                        translated_text = response_text
                    except json.JSONDecodeError:
                        self.logger.error(f"FATAL: JSONDecodeError for json_batch task {task_id}. The model's response was not valid JSON.")
                        # 保留失敗標記
            
            translated_results.append({
                "llm_processing_id": task_id,
                "translated_text": translated_text,
                "source_data": source_data
            })
            
        return translated_results

# 【修改點 3】將 execute_translation 重構為頂層的非同步函式
async def execute_translation_async(
    pre_translate_json_list: list, 
    source_lang_code: str, 
    target_lang: str, 
    video_specific_output_path: str | None = None, 
    logger: logging.Logger | None = None,
    concurrency: int = 10 # <--- 增加併發數參數
) -> list | None:
    logger_to_use = logger if logger else logging.getLogger(__name__)
    translator = Translator(logger=logger_to_use)

    logger_to_use.info(f"Starting async chapter-by-chapter translation from '{source_lang_code}' to '{target_lang}'...")
    
    translated_json_objects = await translator.translate_chapters_async(
        chapter_tasks=pre_translate_json_list,
        source_lang_code=source_lang_code,
        target_lang=target_lang,
        output_path=video_specific_output_path,
        concurrency_limit=concurrency
    )

    if not translated_json_objects:
        logger_to_use.error("Translation failed or returned no results.")
        return None
        
    if len(translated_json_objects) != len(pre_translate_json_list):
        logger_to_use.critical(f"CRITICAL: Task count mismatch! Input tasks: {len(pre_translate_json_list)}, Output results: {len(translated_json_objects)}")
        return None
    
    logger_to_use.info("Task count integrity check passed.")
    return translated_json_objects