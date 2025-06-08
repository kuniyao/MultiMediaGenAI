# Placeholder for LLM translation logic 

import os
import logging
import google.generativeai as genai
import json
import config
from format_converters.core import _normalize_timestamp_id
from pathlib import Path
from dotenv import load_dotenv

# Import the new refactored modules
from .prompt_builder import construct_prompt_for_batch
from .batching import create_batches_by_char_limit
from .response_parser import parse_and_validate_response

# Load .env file from project root
project_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=project_root / '.env')

class Translator:
    """
    A unified class to handle translation using the Google Gemini API.
    It encapsulates model initialization, batching, prompt construction,
    API calls, and response parsing, operating on a standardized rich data format
    to ensure metadata (like timestamps) is preserved.
    """
    def __init__(self, logger=None):
        self.logger = logger if logger else logging.getLogger(__name__)
        self.model = self._initialize_model()

    def _initialize_model(self):
        """Initializes and configures the Gemini model."""
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
            self.logger.debug(f"Successfully initialized Gemini model: {config.LLM_MODEL_GEMINI} (JSON mode, temp=0.0).")
            return model
        except Exception as e:
            self.logger.error(f"Failed to initialize Gemini model: {e}", exc_info=True)
            return None

    def translate_segments(self, pre_translate_json_list, source_lang_code, target_lang="zh-CN", video_specific_output_path=None):
        """
        The core method to orchestrate the translation process for a list of rich subtitle segments.
        It preserves all source metadata.

        Args:
            pre_translate_json_list (list): A list of rich JSON objects, each containing 'llm_processing_id', 
                                            'text_to_translate', and 'source_data'.
            source_lang_code (str): The source language code (e.g., 'en').
            target_lang (str): The target language code (e.g., 'zh-CN').
            video_specific_output_path (str, optional): Path to a directory for logging raw responses. Defaults to None.

        Returns:
            list: A list of rich JSON objects with translated text, preserving all original source data.
        """
        if not self.model:
            self.logger.error("Gemini model not initialized. Skipping translation.")
            return self._create_skipped_results(pre_translate_json_list, "MODEL_NOT_INITIALIZED")

        if not pre_translate_json_list:
            self.logger.info("No segments to translate.")
            return []

        # Prepare segments and source data map
        llm_input_segments, source_data_map, llm_processing_ids_ordered = self._prepare_input_data(pre_translate_json_list)
        
        raw_llm_responses_log_file = self._setup_raw_response_logging(video_specific_output_path, target_lang)

        output_text_field_key = f"text_{target_lang.lower().replace('-', '_')}"
        USE_SIMPLIFIED_IDS_EXPERIMENTAL = True # Keep this as a configurable flag

        # 1. BATCHING: Use the batching module
        self.logger.debug(f"Target prompt tokens per batch: {config.TARGET_PROMPT_TOKENS_PER_BATCH}, Max segments per batch: {config.MAX_SEGMENTS_PER_GEMINI_JSON_BATCH}")
        all_batches = create_batches_by_char_limit(
            llm_input_segments, source_lang_code, target_lang, 
            output_text_field_key, USE_SIMPLIFIED_IDS_EXPERIMENTAL, self.logger
        )

        translations_map = {}
        for batch_idx, actual_batch_segments in enumerate(all_batches):
            if not actual_batch_segments:
                continue
            self.logger.info(f"Translating batch {batch_idx + 1}/{len(all_batches)}...")

            segments_for_payload = self._prepare_batch_payload(actual_batch_segments, USE_SIMPLIFIED_IDS_EXPERIMENTAL)

            # 2. PROMPT CONSTRUCTION: Use the prompt builder module
            prompt_to_send = construct_prompt_for_batch(
                segments_for_payload, source_lang_code, target_lang, 
                output_text_field_key, USE_SIMPLIFIED_IDS_EXPERIMENTAL
            )

            # 3. API CALL
            response_text = self._call_gemini_api(prompt_to_send, raw_llm_responses_log_file, batch_idx + 1)

            # 4. RESPONSE PARSING & VALIDATION: Use the response parser module
            if response_text:
                batch_translations = parse_and_validate_response(
                    response_text, actual_batch_segments, output_text_field_key,
                    batch_idx, USE_SIMPLIFIED_IDS_EXPERIMENTAL, self.logger
                )
                translations_map.update(batch_translations)
            else:
                self.logger.warning(f"Gemini response for batch {batch_idx+1} was empty. Using originals.")
                for seg in actual_batch_segments:
                    translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_EMPTY_RESPONSE] {seg['text_en']}"
        
        # 5. FINAL ASSEMBLY
        return self._assemble_final_results(llm_processing_ids_ordered, translations_map, source_data_map)

    def _create_skipped_results(self, pre_translate_json_list, reason):
        """Creates a list of results indicating that translation was skipped."""
        skipped_results = []
        for item in pre_translate_json_list:
             llm_id = item.get("llm_processing_id")
             text = item.get("text_to_translate")
             source_data = item.get("source_data")
             skipped_results.append({
                "llm_processing_id": llm_id,
                "translated_text": f"[SKIPPED_{reason}] {text}",
                "llm_info": {"error": f"Translation skipped: {reason}"},
                "source_data": source_data
             })
        return skipped_results

    def _prepare_input_data(self, pre_translate_json_list):
        """Converts the input list into formats needed for processing."""
        llm_input_segments = []
        source_data_map = {}
        llm_processing_ids_ordered = []
        for item in pre_translate_json_list:
            llm_id = item.get("llm_processing_id")
            text = item.get("text_to_translate")
            source_data = item.get("source_data")
            if not llm_id or text is None:
                self.logger.warning(f"Skipping item due to missing 'llm_processing_id' or 'text_to_translate': {item.get('segment_guid', 'Unknown GUID')}")
                continue
            llm_input_segments.append({"id": llm_id, "text_en": text})
            source_data_map[llm_id] = source_data
            llm_processing_ids_ordered.append(llm_id)
        return llm_input_segments, source_data_map, llm_processing_ids_ordered

    def _setup_raw_response_logging(self, video_specific_output_path, target_lang):
        """Sets up the log file for raw LLM responses."""
        if not video_specific_output_path:
            return None
        try:
            log_filename = f"llm_raw_responses_{target_lang.lower().replace('-', '_')}.jsonl"
            raw_llm_responses_log_file = os.path.join(video_specific_output_path, log_filename)
            os.makedirs(video_specific_output_path, exist_ok=True)
            self.logger.debug(f"Raw LLM API responses will be logged to: {raw_llm_responses_log_file}")
            return raw_llm_responses_log_file
        except Exception as e:
            self.logger.error(f"Failed to set up raw response logging: {e}", exc_info=True)
            return None

    def _prepare_batch_payload(self, actual_batch_segments, use_simplified_ids):
        """Prepares the list of segments to be included in the prompt payload."""
        if not use_simplified_ids:
            return actual_batch_segments
        
        segments_for_payload = []
        for i, seg_data in enumerate(actual_batch_segments):
            segments_for_payload.append({
                "id": f"seg_{i}",
                "text_en": seg_data["text_en"]
            })
        return segments_for_payload

    def _call_gemini_api(self, prompt, log_file, batch_num):
        """Sends the prompt to the Gemini API and logs the raw response."""
        try:
            response = self.model.generate_content(prompt)
            raw_text = response.text if hasattr(response, 'text') and response.text else None
            
            if log_file:
                try:
                    with open(log_file, 'a', encoding='utf-8') as f_raw:
                        if raw_text:
                            f_raw.write(raw_text + '\n')
                        else:
                            placeholder = {"batch_index": batch_num, "status": "EMPTY_RESPONSE_TEXT", "has_parts": bool(response.parts if hasattr(response, 'parts') else False)}
                            f_raw.write(json.dumps(placeholder) + '\n')
                except Exception as e_log:
                    self.logger.warning(f"Could not write raw LLM response for batch {batch_num} to log file: {e_log}", exc_info=True)
            
            if not response.parts:
                self.logger.warning(f"Gemini response for batch {batch_num} has no parts.")
                return None
            
            return raw_text
        except Exception as e:
            self.logger.error(f"Error calling Gemini API for batch {batch_num}: {e}", exc_info=True)
            return None

    def _assemble_final_results(self, ordered_ids, translations_map, source_data_map):
        """Assembles the final list of translated segments in the original order."""
        final_results = []
        for llm_id in ordered_ids:
            normalized_id = _normalize_timestamp_id(llm_id)
            translated_text = translations_map.get(normalized_id, f"[TRANSLATION_NOT_FOUND] original text placeholder")
            
            # Find original text in case of placeholder, a bit inefficient but robust
            if "original text placeholder" in translated_text:
                 original_text = next((sd['text_en'] for sd_id, sd in source_data_map.items() if _normalize_timestamp_id(sd_id) == normalized_id), "")
                 translated_text = translated_text.replace("original text placeholder", original_text)

            final_results.append({
                "llm_processing_id": llm_id,
                "translated_text": translated_text,
                "llm_info": {"model": config.LLM_MODEL_GEMINI},
                "source_data": source_data_map.get(llm_id)
            })
        return final_results

# Optional: Keep a standalone function for backward compatibility or simple use cases
def translate_text_segments(pre_translate_json_list,
                            source_lang_code, 
                            target_lang="zh-CN",
                            video_specific_output_path=None,
                            logger=None):
    """
    High-level function to translate a list of processed transcript segments.
    Instantiates and uses the GeminiTranslator class.
    """
    translator = Translator(logger=logger)
    return translator.translate_segments(
        pre_translate_json_list,
        source_lang_code,
        target_lang,
        video_specific_output_path
    )