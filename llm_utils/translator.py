# llm_utils/translator.py (MODIFIED to fix type checking issues)

import os
import logging
import google.generativeai as genai
import json
import config
from pathlib import Path
from dotenv import load_dotenv

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
        model = genai.GenerativeModel(
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

    def _call_gemini_api(self, prompt: str, log_file_path: str | None, task_id: str) -> str | None:
        # 在調用前檢查self.model是否存在，這是一個好的實踐
        if not self.model:
            self.logger.error(f"Model is not initialized. Cannot call API for task {task_id}.")
            return None
            
        try:
            # self.model 在這裡被確認存在，所以 generate_content 的警告會消失
            response = self.model.generate_content(prompt, request_options={'timeout': 300})
            raw_text = response.text
        except Exception as e:
            self.logger.error(f"Error calling Gemini API for task {task_id}: {e}", exc_info=True)
            
            # 【關鍵修改】使用 hasattr 進行安全檢查
            finish_reason = "UNKNOWN"
            # 檢查 e.__cause__ 是否存在，再檢查 e.__cause__.candidate 是否存在
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

    def translate_chapters(self, chapter_tasks: list, source_lang_code: str, target_lang: str, output_path: str | None) -> list:
        if not self.model:
            self.logger.error("Gemini model not initialized. Skipping translation.")
            return []

        raw_llm_log_file = os.path.join(output_path, f"llm_raw_responses_{target_lang.lower().replace('-', '_')}.jsonl") if output_path else None
        translated_results = []

        for i, task in enumerate(chapter_tasks):
            task_id = task['llm_processing_id']
            source_data = task['source_data']
            task_type = source_data.get('type')
            prompt = ""
            
            self.logger.info(f"Processing task {i + 1}/{len(chapter_tasks)} (ID: {task_id}, Type: {task_type})...")

            if task_type == 'json_batch':
                prompt = build_json_batch_translation_prompt(task['text_to_translate'], source_lang_code, target_lang)
            elif task_type == 'split_part':
                prompt = build_html_translation_prompt(task['text_to_translate'], source_lang_code, target_lang)
            else:
                self.logger.warning(f"Unknown task type '{task_type}' for task ID {task_id}. Skipping.")
                continue

            response_text = self._call_gemini_api(prompt, raw_llm_log_file, task_id)
            
            # 默認失敗標記
            translated_text = f"[TRANSLATION_FAILED] Original content preserved for task {task_id}."
            
            if response_text:
                if task_type == 'split_part':
                    try:
                        # 優先嘗試解析JSON
                        response_json = json.loads(response_text)
                        translated_text = response_json.get("translated_html", translated_text)
                    except json.JSONDecodeError:
                        # 【新增容錯】如果解析失敗，我們假設模型直接返回了HTML
                        self.logger.warning(f"JSONDecodeError for split_part task {task_id}. Assuming raw HTML response.")
                        translated_text = response_text
                
                elif task_type == 'json_batch':
                    try:
                        # 對於批處理，我們必須要有合法的JSON
                        json.loads(response_text) 
                        translated_text = response_text
                    except json.JSONDecodeError:
                        self.logger.error(f"FATAL: JSONDecodeError for json_batch task {task_id}. The model's response was not valid JSON. This batch cannot be recovered.")
                        # 這種情況下保留失敗標記
            
            translated_results.append({
                "llm_processing_id": task_id,
                "translated_text": translated_text,
                "source_data": source_data
            })

        return translated_results

def execute_translation(pre_translate_json_list: list, source_lang_code: str, target_lang: str, video_specific_output_path: str | None = None, logger: logging.Logger | None = None) -> list | None:
    logger_to_use = logger if logger else logging.getLogger(__name__)
    translator = Translator(logger=logger_to_use)

    logger_to_use.info(f"Starting chapter-by-chapter translation from '{source_lang_code}' to '{target_lang}'...")
    translated_json_objects = translator.translate_chapters(
        chapter_tasks=pre_translate_json_list,
        source_lang_code=source_lang_code,
        target_lang=target_lang,
        output_path=video_specific_output_path
    )

    if not translated_json_objects:
        logger_to_use.error("Translation failed or returned no results.")
        return None
        
    if len(translated_json_objects) != len(pre_translate_json_list):
        logger_to_use.critical(f"CRITICAL: Task count mismatch! Input tasks: {len(pre_translate_json_list)}, Output results: {len(translated_json_objects)}")
        return None
    
    logger_to_use.info("Task count integrity check passed.")
    return translated_json_objects