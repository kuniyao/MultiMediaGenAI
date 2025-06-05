# Placeholder for LLM translation logic 

import os
import logging
import google.generativeai as genai
import json
import time
import config # Assuming config.py is in the PYTHONPATH or project root
from format_converters.core import format_time, _normalize_timestamp_id

def translate_text_segments(transcript_data_processed, 
                            source_lang_code, 
                            target_lang="zh-CN",
                            video_specific_output_path=None,
                            logger=None):
    """
    Translates a list of processed transcript segments (with text, start, duration)
    using the configured LLM provider, via batched JSON objects.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)

    logger_to_use.info(f"--- LLM Provider from config: {config.LLM_PROVIDER} ---")
    
    if not transcript_data_processed:
        logger_to_use.info("No segments to translate.")
        return []

    json_segments_to_translate = []
    for item in transcript_data_processed:
        original_raw_id = format_time(item['start']) + " --> " + format_time(item['start'] + item['duration'])
        json_segments_to_translate.append({
            "id": original_raw_id, 
            "text_en": item['text'] 
        })

    translations_map = {} 

    raw_llm_responses_log_file = None
    if video_specific_output_path:
        log_filename = f"llm_raw_responses_{target_lang.lower().replace('-', '_')}.jsonl"
        raw_llm_responses_log_file = os.path.join(video_specific_output_path, log_filename)
        os.makedirs(video_specific_output_path, exist_ok=True)
        logger_to_use.info(f"Raw LLM API responses will be logged to: {raw_llm_responses_log_file}")

    if config.LLM_PROVIDER == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger_to_use.error("GEMINI_API_KEY not found. Translation will be skipped.")
            return [f"[SKIPPED_NO_KEY] {s['text_en']}" for s in json_segments_to_translate]

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
            logger_to_use.info(f"Using Gemini model: {config.LLM_MODEL_GEMINI} for translation from '{source_lang_code}' to '{target_lang}' (JSON mode, temperature=0.0)." )
            logger_to_use.info(f"Target prompt tokens per batch: {config.TARGET_PROMPT_TOKENS_PER_BATCH}, Max segments per batch: {config.MAX_SEGMENTS_PER_GEMINI_JSON_BATCH}")

            output_text_field_key = f"text_{target_lang.lower().replace('-', '_')}" 

            def _construct_prompt_string_for_batch(segments_list_for_payload, src_lang, tgt_lang, out_text_key, use_simplified_ids=False):
                if use_simplified_ids:
                    example_id_format = "seg_N (e.g., 'seg_0', 'seg_1', ... 'seg_99')"
                    id_preservation_instruction = (
                        f"CRITICAL ID PRESERVATION: The 'id' field is a simplified segment identifier (format: {example_id_format}). "
                        f"You MUST return this 'id' string EXACTLY as it was provided in the input for each segment. DO NOT alter or omit the 'id'. "
                        "The 'id' ensures segments are correctly mapped back after translation."
                    )
                else: # Original behavior
                    example_id_format = "HH:MM:SS,mmm --> HH:MM:SS,mmm (e.g., '00:01:23,456 --> 00:01:25,789')"
                    id_preservation_instruction = (
                        f"CRITICAL ID PRESERVATION: The 'id' field is a precise timestamp string (format: {example_id_format}). "
                        f"You MUST return this 'id' string EXACTLY as it was provided in the input for each segment. DO NOT alter, reformat, or change any part of the 'id' string, including numbers, colons, commas, spaces, or the '-->' separator. "
                    )
                
                instruction_text_for_payload = (
                    f"Objective: Translate the 'text_en' field of each segment object from {src_lang} to {tgt_lang}. "
                    f"Output Format: A JSON object with a single key 'translated_segments'. This key's value must be an array of objects. "
                    f"Each object in this output array must retain the original 'id' from the input segment and include the translated text in a new field named '{out_text_key}'."
                    f"{id_preservation_instruction} " 
                    "The segments are ordered chronologically and provide context for each other. "
                    "CRITICAL REQUIREMENT: The number of objects in the 'translated_segments' array MUST EXACTLY MATCH the number of input segments. If the counts do not match, the entire translation for this batch will be discarded. Do not split a single input segment into multiple translated segments in the output array. Maintain a strict one-to-one correspondence."
                )
                json_payload_for_prompt = {
                    "source_language": src_lang,
                    "target_language": tgt_lang,
                    "instructions": instruction_text_for_payload, 
                    "segments": segments_list_for_payload
                }
                return (
                    f"Your task is to process the following JSON request. The 'instructions' field within the JSON details the primary objective: "
                    f"to translate text segments from {src_lang} to {tgt_lang}. "
                    "You MUST return a single, valid JSON object that strictly follows the output structure described in the 'instructions' field of the request. "
                    "Pay EXTREME ATTENTION to the ID PRESERVATION requirement detailed in the instructions: the 'id' field for each segment in your response MUST be an IDENTICAL, UNCHANGED copy of the 'id' field from the input segment.\n\n"
                    f"JSON Request:\n```json\n{json.dumps(json_payload_for_prompt, indent=2, ensure_ascii=False)}\n```"
                )

            all_batches = []
            current_batch_input_segments = [] 
            USE_SIMPLIFIED_IDS_EXPERIMENTAL = True
            if USE_SIMPLIFIED_IDS_EXPERIMENTAL:
                logger_to_use.info("Using SIMPLIFIED IDs (seg_N) for translation batches.")

            for seg_obj in json_segments_to_translate:
                potential_segments_for_this_batch = current_batch_input_segments + [seg_obj]
                prompt_if_added = _construct_prompt_string_for_batch(
                    potential_segments_for_this_batch, 
                    source_lang_code, 
                    target_lang, 
                    output_text_field_key,
                    use_simplified_ids=False 
                )
                try:
                    num_tokens_if_added = model.count_tokens(prompt_if_added).total_tokens
                except Exception as e_count:
                    logger_to_use.warning(f"Token counting failed for a potential batch. Error: {e_count}. Proceeding with segment count only for this decision.", exc_info=True)
                    if len(potential_segments_for_this_batch) > 10: 
                         num_tokens_if_added = config.TARGET_PROMPT_TOKENS_PER_BATCH + 1 
                    else:
                         num_tokens_if_added = 1 

                if current_batch_input_segments and \
                   (num_tokens_if_added > config.TARGET_PROMPT_TOKENS_PER_BATCH or \
                    len(potential_segments_for_this_batch) > config.MAX_SEGMENTS_PER_GEMINI_JSON_BATCH):
                    all_batches.append(list(current_batch_input_segments))
                    current_batch_input_segments = [seg_obj]
                else:
                    current_batch_input_segments.append(seg_obj)
            
            if current_batch_input_segments:
                all_batches.append(list(current_batch_input_segments))

            if all_batches:
                logger_to_use.info(f"Prepared {len(all_batches)} batches for translation.")
            else:
                logger_to_use.info("No batches to translate.") 

            for batch_idx, actual_batch_segments in enumerate(all_batches):
                if not actual_batch_segments:
                    continue
                logger_to_use.info(f"Translating batch {batch_idx + 1}/{len(all_batches)}...")
                
                segments_for_payload_this_batch = []
                if USE_SIMPLIFIED_IDS_EXPERIMENTAL:
                    for i, seg_data in enumerate(actual_batch_segments):
                        segments_for_payload_this_batch.append({
                            "id": f"seg_{i}",
                            "text_en": seg_data["text_en"]
                        })
                else:
                    segments_for_payload_this_batch = actual_batch_segments

                prompt_to_send = _construct_prompt_string_for_batch(
                    segments_for_payload_this_batch, 
                    source_lang_code, 
                    target_lang, 
                    output_text_field_key,
                    use_simplified_ids=USE_SIMPLIFIED_IDS_EXPERIMENTAL
                )
                
                try:
                    response = model.generate_content(prompt_to_send)
                    if raw_llm_responses_log_file:
                        try:
                            raw_text_to_log = response.text if hasattr(response, 'text') and response.text else None
                            if raw_text_to_log:
                                with open(raw_llm_responses_log_file, 'a', encoding='utf-8') as f_raw:
                                    f_raw.write(raw_text_to_log + '\n')
                            else:
                                with open(raw_llm_responses_log_file, 'a', encoding='utf-8') as f_raw:
                                    placeholder_log = {"batch_index": batch_idx + 1, "status": "EMPTY_RESPONSE_TEXT", "has_parts": bool(response.parts if hasattr(response, 'parts') else False)}
                                    f_raw.write(json.dumps(placeholder_log) + '\n')
                        except Exception as e_log:
                            logger_to_use.warning(f"Could not write raw LLM response for batch {batch_idx + 1} to log file: {e_log}", exc_info=True)

                    if not response.parts:
                         logger_to_use.warning(f"Gemini response for batch {batch_idx+1} has no parts. Using originals.")
                         for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_EMPTY_RESPONSE] {seg['text_en']}"
                         continue
                    try:
                        translated_json_str = response.text 
                        cleaned_json_str = translated_json_str.strip()
                        if cleaned_json_str.startswith('{') and cleaned_json_str.endswith('}'):
                            if cleaned_json_str.count('}') == cleaned_json_str.count('{') + 1:
                                logger_to_use.warning("Attempting to fix a potential extra trailing curly brace in JSON response.")
                                cleaned_json_str = cleaned_json_str[:-1]
                        
                        translated_data = json.loads(cleaned_json_str)
                        if 'translated_segments' not in translated_data or not isinstance(translated_data['translated_segments'], list):
                            logger_to_use.warning(f"  Warning: 'translated_segments' array not found/invalid in response for batch {batch_idx+1}. Raw: {cleaned_json_str[:200] if cleaned_json_str else 'EMPTY'}... Using originals.")
                            for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_BAD_JSON_STRUCTURE] {seg['text_en']}"
                            continue
                        translated_batch_segments_from_response = translated_data['translated_segments']
                        if len(translated_batch_segments_from_response) != len(actual_batch_segments):
                            logger_to_use.warning(f"Mismatch in translated segments for batch {batch_idx+1} (expected {len(actual_batch_segments)}, got {len(translated_batch_segments_from_response)}). Using originals for this batch.")
                            for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_SEG_COUNT_MISMATCH] {seg['text_en']}"
                            continue
                        
                        for i, translated_seg_item in enumerate(translated_batch_segments_from_response):
                            original_complex_id_from_actual_batch = actual_batch_segments[i]["id"]
                            text_en_from_actual_batch = actual_batch_segments[i]["text_en"]
                            map_key = _normalize_timestamp_id(original_complex_id_from_actual_batch)

                            if USE_SIMPLIFIED_IDS_EXPERIMENTAL:
                                expected_simple_id = f"seg_{i}"
                                model_returned_simple_id = translated_seg_item.get("id")
                                if not model_returned_simple_id:
                                    logger_to_use.warning(f"ID missing in translated segment. Batch {batch_idx+1}. Expected simple ID '{expected_simple_id}' (for original: '{original_complex_id_from_actual_batch}'). Skipping.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISSING_IN_RESPONSE] {text_en_from_actual_batch}"
                                    continue
                                if model_returned_simple_id != expected_simple_id:
                                    logger_to_use.warning(f"Simple ID mismatch from model. Batch {batch_idx+1}.\n     Expected: '{expected_simple_id}' (for original: '{original_complex_id_from_actual_batch}')\n     Model Returned: '{model_returned_simple_id}'. Skipping.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_SIMPLE_ID_MISMATCH] {text_en_from_actual_batch}"
                                    continue
                            else: 
                                translated_id_from_model = translated_seg_item.get("id")
                                if not translated_id_from_model:
                                    logger_to_use.warning(f"ID missing in translated segment for original ID '{original_complex_id_from_actual_batch}' in batch {batch_idx+1}. Skipping.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISSING_IN_RESPONSE] {text_en_from_actual_batch}"
                                    continue
                                normalized_translated_id = _normalize_timestamp_id(translated_id_from_model)
                                if map_key != normalized_translated_id: 
                                    logger_to_use.warning(f"ID mismatch after attempting to normalize model response. Batch {batch_idx+1}.\n     Original (Normalized): '{map_key}'\n     Model Output Raw : '{translated_id_from_model}'\n     Model OutputNormd: '{normalized_translated_id}'. Skipping segment.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISMATCH_NORM_FAILED_OR_VALUE_DIFF] {text_en_from_actual_batch}"
                                    continue
                            
                            if output_text_field_key not in translated_seg_item:
                                id_for_error_msg = f"seg_{i}" if USE_SIMPLIFIED_IDS_EXPERIMENTAL else original_complex_id_from_actual_batch
                                logger_to_use.warning(f"Expected field '{output_text_field_key}' not found for ID '{id_for_error_msg}' in batch {batch_idx+1}. Using original.")
                                translations_map[map_key] = f"[NO_TRANSLATION_MISSING_TEXT_FIELD] {text_en_from_actual_batch}"
                                continue
                            translations_map[map_key] = translated_seg_item[output_text_field_key]
                        logger_to_use.info(f"Batch {batch_idx + 1} translated successfully.")
                    except json.JSONDecodeError as e_json:
                        logger_to_use.error(f"  Error decoding JSON response from Gemini for batch {batch_idx+1}: {e_json}. Cleaned Raw Attempt: {(cleaned_json_str[:500] if cleaned_json_str else 'EMPTY_STRING_FOR_DECODE')}", exc_info=True)
                        for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[ERROR_JSON_DECODE] {seg['text_en']}"
                    except Exception as e_resp_proc:
                        logger_to_use.error(f"Error processing response from Gemini for batch {batch_idx+1}: {e_resp_proc}", exc_info=True)
                        for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[ERROR_RESP_PROCESSING] {seg['text_en']}"
                except Exception as e_api_call:
                    logger_to_use.error(f"An error occurred during Gemini API call for batch {batch_idx+1}: {e_api_call}. This might be due to the batch size exceeding model limits even after token counting.", exc_info=True)
                    if raw_llm_responses_log_file:
                        try:
                            with open(raw_llm_responses_log_file, 'a', encoding='utf-8') as f_raw:
                                error_info = {"batch_index": batch_idx + 1, "status": "API_CALL_ERROR", "error_message": str(e_api_call)}
                                f_raw.write(json.dumps(error_info) + '\n')
                        except Exception as e_log_err:
                            logger_to_use.warning(f"Could not write API call error to log file for batch {batch_idx + 1}: {e_log_err}", exc_info=True)
                    for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[ERROR_API_CALL] {seg['text_en']}"
                
                delay_seconds = getattr(config, 'LLM_REQUEST_DELAY', 0)
                if delay_seconds > 0 and batch_idx < len(all_batches) - 1 :
                    logger_to_use.info(f"Waiting for {delay_seconds}s before next batch...")
                    time.sleep(delay_seconds)

            final_translated_texts = []
            for seg_obj_orig in json_segments_to_translate:
                normalized_key_to_lookup = _normalize_timestamp_id(seg_obj_orig["id"])
                default_not_found_message = (f"[TRANSLATION_NOT_FOUND_FOR_ID:{seg_obj_orig['id']}] "
                                           f"[NORMALIZED_AS:{normalized_key_to_lookup}] "
                                           f"{seg_obj_orig['text_en']}")
                final_translated_texts.append(translations_map.get(normalized_key_to_lookup, default_not_found_message))
            
            if len(final_translated_texts) != len(json_segments_to_translate):
                 logger_to_use.critical(f"Final translated segment count ({len(final_translated_texts)}) MISMATCHES original segment count ({len(json_segments_to_translate)}).")
            
            logger_to_use.info(f"--- Gemini JSON translation processing complete. ---")
            return final_translated_texts
        except Exception as e:
            logger_to_use.critical(f"A critical error occurred during Gemini JSON setup or outer processing loop: {e}", exc_info=True)
            if raw_llm_responses_log_file:
                try:
                    with open(raw_llm_responses_log_file, 'a', encoding='utf-8') as f_raw:
                        error_info = {"batch_index": "CRITICAL_OUTER", "status": "CRITICAL_ERROR_TRANSLATING", "error_message": str(e)}
                        f_raw.write(json.dumps(error_info) + '\n')
                except Exception as e_log_crit:
                    logger_to_use.warning(f"Could not write critical outer processing error to log file: {e_log_crit}", exc_info=True)
            return [f"[CRITICAL_ERROR_TRANSLATING] {s['text_en']}" for s in json_segments_to_translate]
    else:
        logger_to_use.warning(f"Unsupported or misconfigured LLM_PROVIDER: {config.LLM_PROVIDER}. Using simulated translation.")
        simulated_translated_segments = []
        if raw_llm_responses_log_file:
            try:
                with open(raw_llm_responses_log_file, 'a', encoding='utf-8') as f_raw:
                    # Note: batch_idx might not be defined here if LLM_PROVIDER wasn't gemini from the start.
                    # Using a placeholder or ensuring it's initialized might be safer.
                    # For simplicity, assuming it might exist from a prior loop context if this path is hit after some batches.
                    # A more robust way is to log this at a higher level or pass batch_idx if meaningful here.
                    # However, for a simple simulated translation, a generic log is fine.
                    error_info = {"status": "SIMULATED_TRANSLATION", "error_message": "Simulated translation used due to unsupported/misconfigured LLM_PROVIDER."}
                    f_raw.write(json.dumps(error_info) + '\n')
            except Exception as e_log_sim:
                logger_to_use.warning(f"Could not write simulation info to log file: {e_log_sim}", exc_info=True)

        for seg_obj in json_segments_to_translate: 
            translated_text = f"[译] {seg_obj['text_en']}" 
            simulated_translated_segments.append(translated_text)
        logger_to_use.info("--- Simulated translation complete ---")
        return simulated_translated_segments 