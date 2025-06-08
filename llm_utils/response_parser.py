import json
import logging
from format_converters.core import _normalize_timestamp_id

def parse_and_validate_response(
    response_text,
    actual_batch_segments,
    output_text_field_key,
    batch_idx,
    use_simplified_ids,
    logger=None
):
    """
    Parses, cleans, and validates the JSON response from the LLM for a single batch.

    Args:
        response_text (str): The raw text response from the LLM.
        actual_batch_segments (list): The original list of segments sent in the batch.
        output_text_field_key (str): The key where the translated text is expected.
        batch_idx (int): The index of the current batch (for logging).
        use_simplified_ids (bool): Whether simplified IDs were used.
        logger: A logger instance.

    Returns:
        dict: A dictionary mapping normalized original IDs to translated text.
              Returns a dict with error placeholders if validation fails.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    translations_map = {}

    try:
        cleaned_json_str = response_text.strip()
        if cleaned_json_str.startswith("```json"):
            cleaned_json_str = cleaned_json_str[7:]
        if cleaned_json_str.endswith("```"):
            cleaned_json_str = cleaned_json_str[:-3]
        cleaned_json_str = cleaned_json_str.strip()

        # Attempt to fix common JSON error: extra closing brace
        if cleaned_json_str.startswith('{') and cleaned_json_str.endswith('}'):
            if cleaned_json_str.count('}') > cleaned_json_str.count('{'):
                 logger_to_use.warning(f"Attempting to fix a potential extra trailing curly brace in JSON response for batch {batch_idx+1}.")
                 # Find the matching brace for the opening brace
                 open_braces = 1
                 match_index = -1
                 for i, char in enumerate(cleaned_json_str[1:]):
                     if char == '{':
                         open_braces += 1
                     elif char == '}':
                         open_braces -= 1
                     if open_braces == 0:
                         match_index = i + 1
                         break
                 if match_index != -1 and match_index < len(cleaned_json_str) -1:
                    cleaned_json_str = cleaned_json_str[:match_index+1]

        translated_data = json.loads(cleaned_json_str)
        
        # Validation 1: Check for the main 'translated_segments' key
        if 'translated_segments' not in translated_data or not isinstance(translated_data['translated_segments'], list):
            logger_to_use.warning(f"  Warning: 'translated_segments' array not found/invalid in response for batch {batch_idx+1}. Raw: {cleaned_json_str[:200] if cleaned_json_str else 'EMPTY'}... Using originals.")
            for seg in actual_batch_segments:
                translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_BAD_JSON_STRUCTURE] {seg['text_en']}"
            return translations_map

        translated_batch_segments_from_response = translated_data['translated_segments']

        # Validation 2: Check for segment count mismatch
        if len(translated_batch_segments_from_response) != len(actual_batch_segments):
            logger_to_use.warning(f"Mismatch in translated segments for batch {batch_idx+1} (expected {len(actual_batch_segments)}, got {len(translated_batch_segments_from_response)}). Using originals for this batch.")
            for seg in actual_batch_segments:
                translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_SEG_COUNT_MISMATCH] {seg['text_en']}"
            return translations_map
        
        # If all validations pass, process the segments
        for i, translated_seg_item in enumerate(translated_batch_segments_from_response):
            original_complex_id = actual_batch_segments[i]["id"]
            text_en = actual_batch_segments[i]["text_en"]
            map_key = _normalize_timestamp_id(original_complex_id)

            # Validation 3: ID integrity check
            response_id = translated_seg_item.get("id")
            if use_simplified_ids:
                expected_id = f"seg_{i}"
                if response_id != expected_id:
                    logger_to_use.warning(f"ID mismatch in batch {batch_idx+1}, segment {i}. Expected simplified ID '{expected_id}', got '{response_id}'. Using original text.")
                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISMATCH] {text_en}"
                    continue
            else: # Original complex ID check
                normalized_response_id = _normalize_timestamp_id(response_id)
                if normalized_response_id != map_key:
                    logger_to_use.warning(f"ID mismatch in batch {batch_idx+1}, segment {i}. Expected '{map_key}', got '{normalized_response_id}'. Using original text.")
                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISMATCH] {text_en}"
                    continue
            
            # Validation 4: Text extraction
            if output_text_field_key in translated_seg_item and translated_seg_item.get(output_text_field_key):
                 translations_map[map_key] = translated_seg_item[output_text_field_key]
            else:
                 logger_to_use.warning(f"Translated text field '{output_text_field_key}' not found or empty in segment {i} of batch {batch_idx+1}. Using original.")
                 translations_map[map_key] = f"[NO_TRANSLATION_TEXT_FIELD_MISSING] {text_en}"

    except json.JSONDecodeError:
        logger_to_use.warning(f"JSONDecodeError for batch {batch_idx+1}. Raw response: {response_text[:300]}... Using originals for this batch.")
        for seg in actual_batch_segments:
            translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_JSON_DECODE_ERROR] {seg['text_en']}"
    except Exception as e:
        logger_to_use.error(f"An unexpected error occurred while parsing batch {batch_idx+1}: {e}", exc_info=True)
        for seg in actual_batch_segments:
            translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_UNEXPECTED_ERROR] {seg['text_en']}"
            
    return translations_map 