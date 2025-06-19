# In llm_utils/translator.py (NEW VERSION)

import os
import logging
import google.generativeai as genai
import json
import config
from pathlib import Path
from dotenv import load_dotenv

# 导入我们新的prompt构建器
from .prompt_builder import build_html_translation_prompt

# 加载 .env 文件
project_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=project_root / '.env')

class Translator:
    """
    一个统一的类，用于处理使用Google Gemini API的翻译。
    这个新版本专门为处理大型、独立的HTML内容块（如EPUB章节）而优化。
    """
    def __init__(self, logger=None):
        self.logger = logger if logger else logging.getLogger(__name__)
        self.model = self._initialize_model()

    def _initialize_model(self):
        """(此函数保持不变) 初始化并配置Gemini模型。"""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            self.logger.error("GEMINI_API_KEY not found. Translation will be skipped.")
            return None
        
        try:
            genai.configure(api_key=api_key)
            generation_config = genai.types.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.0
            )
            model = genai.GenerativeModel(
                config.LLM_MODEL_GEMINI,
                generation_config=generation_config
            )
            self.logger.debug(f"Successfully initialized Gemini model: {config.LLM_MODEL_GEMINI}.")
            return model
        except Exception as e:
            self.logger.error(f"Failed to initialize Gemini model: {e}", exc_info=True)
            return None

    def _call_gemini_api_for_html(self, prompt: str, log_file_path: str | None, task_id: str) -> str | None:
        """为单个HTML翻译任务调用Gemini API，并增加健壮的错误处理。"""
        try:
            response = self.model.generate_content(prompt)
            raw_text = response.text
        except Exception as e:
            # 捕获API调用期间的任何错误（包括finish_reason导致的ValueError）
            self.logger.error(f"Error calling Gemini API for task {task_id}: {e}", exc_info=True)
            # 尝试从异常中获取 finish_reason
            finish_reason = "UNKNOWN"
            if hasattr(e, '__cause__') and hasattr(e.__cause__, 'candidate') and e.__cause__.candidate:
                finish_reason = str(e.__cause__.candidate.finish_reason)
            self.logger.error(f"API call for {task_id} failed with finish_reason: {finish_reason}")
            return None
        
        if log_file_path and raw_text:
            with open(log_file_path, 'a', encoding='utf-8') as f:
                log_entry = {"task_id": task_id, "response": raw_text}
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
        
        return raw_text

    def translate_chapters(self, chapter_tasks: list, source_lang_code: str, target_lang: str, output_path: str | None) -> list:
        """按顺序翻译一系列章节任务，一次一个。"""
        if not self.model:
            self.logger.error("Gemini model not initialized. Skipping translation.")
            return []

        raw_llm_log_file = os.path.join(output_path, f"llm_raw_responses_{target_lang.lower().replace('-', '_')}.jsonl") if output_path else None
        translated_results = []

        for i, task in enumerate(chapter_tasks):
            self.logger.info(f"Translating chapter {i + 1}/{len(chapter_tasks)} (ID: {task['llm_processing_id']})...")
            
            prompt = build_html_translation_prompt(task['text_to_translate'], source_lang_code, target_lang)
            response_text = self._call_gemini_api_for_html(prompt, raw_llm_log_file, task['llm_processing_id'])

            translated_html = f"[TRANSLATION_FAILED] {task['text_to_translate']}" # 默认的回退值
            if response_text:
                try:
                    response_json = json.loads(response_text)
                    translated_html = response_json.get("translated_html", translated_html)
                except json.JSONDecodeError:
                    self.logger.error(f"JSONDecodeError for chapter {task['llm_processing_id']}.")
            
            translated_results.append({
                "llm_processing_id": task['llm_processing_id'],
                "translated_text": translated_html,
                "source_data": task['source_data']
            })
        return translated_results

def execute_translation(pre_translate_json_list: list, source_lang_code: str, target_lang: str, video_specific_output_path: str | None = None, logger: logging.Logger | None = None) -> list | None:
    """协调翻译过程的高级函数。"""
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
        logger_to_use.critical("CRITICAL: Task count mismatch!")
        return None
    
    logger_to_use.info("Task count integrity check passed.")
    return translated_json_objects