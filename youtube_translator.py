import argparse
import os # Added for .env
from dotenv import load_dotenv # Added for .env
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
import config # Added for config.py
import google.generativeai as genai # Added for Gemini
import time # Added for time.sleep if using batch delays
import json # Added for new translation flow
import re # For normalizing timestamp IDs

def get_youtube_transcript(video_url_or_id):
    """
    Fetches the transcript for a given YouTube video ID or URL.
    Prioritizes manually created transcripts, then falls back to generated ones.
    Languages are prioritized based on config.py, then any available.
    """
    video_id = video_url_or_id
    if "youtube.com/watch?v=" in video_url_or_id:
        video_id = video_url_or_id.split("watch?v=")[1].split("&")[0]
    elif "youtu.be/" in video_url_or_id:
        video_id = video_url_or_id.split("youtu.be/")[1].split("?")[0]

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Use preferred languages from config
        preferred_langs = config.PREFERRED_TRANSCRIPT_LANGUAGES

        # Try manual transcript in preferred languages
        for lang in preferred_langs:
            try:
                transcript = transcript_list.find_manually_created_transcript([lang])
                print(f"Found manually created transcript in '{lang}'.")
                return transcript.fetch(), lang, "manual"
            except NoTranscriptFound:
                continue
        print(f"No manually created transcript found in preferred languages: {preferred_langs}.")

        # Try generated transcript in preferred languages
        for lang in preferred_langs:
            try:
                transcript = transcript_list.find_generated_transcript([lang])
                print(f"Found auto-generated transcript in '{lang}'.")
                return transcript.fetch(), lang, "generated"
            except NoTranscriptFound:
                continue
        print(f"No auto-generated transcript found in preferred languages: {preferred_langs}.")

        # If not found in preferred languages, try any manual transcript
        available_manual = transcript_list._manually_created_transcripts
        if available_manual:
            first_available_manual_lang = list(available_manual.keys())[0]
            try:
                transcript = transcript_list.find_manually_created_transcript([first_available_manual_lang])
                print(f"Found manually created transcript in '{first_available_manual_lang}' (first available).")
                return transcript.fetch(), first_available_manual_lang, "manual"
            except NoTranscriptFound: # Should not happen if key exists
                pass 
        print("No manually created transcript found in any language.")

        # If no manual transcript, try any generated transcript
        available_generated = transcript_list._generated_transcripts
        if available_generated:
            first_available_generated_lang = list(available_generated.keys())[0]
            try:
                transcript = transcript_list.find_generated_transcript([first_available_generated_lang])
                print(f"Found auto-generated transcript in '{first_available_generated_lang}' (first available).")
                return transcript.fetch(), first_available_generated_lang, "generated"
            except NoTranscriptFound: # Should not happen
                 pass
        print("No auto-generated transcript found in any language.")
        
        print(f"No suitable transcript found for video {video_id}.")
        return None, None, None

    except TranscriptsDisabled:
        print(f"Transcripts are disabled for video {video_id}.")
        return None, None, None
    except Exception as e:
        print(f"An error occurred while fetching transcript for {video_id}: {e}")
        return None, None, None

def format_time(seconds_val):
    """Converts seconds to SRT time format (HH:MM:SS,ms)"""
    # Separate integer and fractional parts of seconds
    integer_seconds = int(seconds_val)
    fractional_seconds = seconds_val - integer_seconds

    # Calculate milliseconds, round, and handle carry-over to seconds
    millis = int(round(fractional_seconds * 1000))

    if millis >= 1000:
        integer_seconds += millis // 1000  # Add carried-over second(s)
        millis %= 1000                     # Remainder is the new milliseconds

    # Calculate HH, MM, SS from the (potentially adjusted) integer_seconds
    hours = integer_seconds // 3600
    remainder_after_hours = integer_seconds % 3600
    minutes = remainder_after_hours // 60
    final_seconds_part = remainder_after_hours % 60
    
    return f"{hours:02d}:{minutes:02d}:{final_seconds_part:02d},{millis:03d}"

def preprocess_and_merge_segments(raw_transcript_data):
    """
    Merges raw transcript segments based on duration, length, and punctuation.
    Also cleans up newlines within segments.
    """
    if not raw_transcript_data:
        return []

    # --- Pass 1: Initial Cleaning from API data --- 
    initial_cleaned_entries = []
    for entry_obj in raw_transcript_data: # entry_obj is FetchedTranscriptSnippet here
        cleaned_text = entry_obj.text.replace('\n', ' ').strip()
        if cleaned_text:
            initial_cleaned_entries.append({
                'text': cleaned_text,
                'start': entry_obj.start,    
                'duration': entry_obj.duration,
                'original_text_length': len(cleaned_text) # Store original length for proportional duration later
            })

    if not initial_cleaned_entries:
        return []
    
    # --- Helper function to check for actual sentence ending (handles decimals and common host/file patterns) ---
    def _is_actual_sentence_end_char(text_segment, char_index_in_segment, sentence_end_punctuations_config):
        char_to_check = text_segment[char_index_in_segment]

        if char_to_check == '.':
            # Rule 1: Decimal point detection (e.g., "2.5", ".5")
            is_prev_digit = (char_index_in_segment > 0 and text_segment[char_index_in_segment - 1].isdigit())
            is_next_digit = (char_index_in_segment < len(text_segment) - 1 and text_segment[char_index_in_segment + 1].isdigit())
            
            if is_prev_digit and is_next_digit: # e.g., "2.5"
                return False 
            if not is_prev_digit and is_next_digit: # e.g., ".5"
                if not (char_index_in_segment > 0 and text_segment[char_index_in_segment - 1] == '.'):
                    return False 

            prev_char_is_alnum = (char_index_in_segment > 0 and text_segment[char_index_in_segment - 1].isalnum())
            next_char_is_alnum = (char_index_in_segment < len(text_segment) - 1 and text_segment[char_index_in_segment + 1].isalnum())

            if prev_char_is_alnum and next_char_is_alnum:
                idx_after_alnum_dot_alnum = char_index_in_segment + 2 
                
                if idx_after_alnum_dot_alnum < len(text_segment) -1:
                    if text_segment[idx_after_alnum_dot_alnum] == ' ' and text_segment[idx_after_alnum_dot_alnum + 1].isupper():
                        return True 
                    else:
                        return False 
                else:
                    return False 

            return True
            
        elif char_to_check in sentence_end_punctuations_config: 
            return True
            
        return False
    # --- End of Helper --- 

    print(f"\n--- Starting Pre-segmentation and Merging Logic ---")
    print(f"Pass 1: Initial cleaning complete. {len(initial_cleaned_entries)} entries.")

    # --- Pass 2: Pre-splitting entries with internal punctuations --- 
    fine_grained_entries = []
    for i, entry_dict in enumerate(initial_cleaned_entries):
        text_to_process = entry_dict['text']
        original_start_time = entry_dict['start']
        original_duration = entry_dict['duration']
        original_text_len = entry_dict['original_text_length']
        if original_text_len == 0: continue

        current_sub_segment_start_time = original_start_time

        while text_to_process:
            found_punc_at = -1
            # Find the *first* sentence-ending punctuation from the start of text_to_process
            for punc_char_idx, char_in_text in enumerate(text_to_process):
                # Use the helper function here
                if _is_actual_sentence_end_char(text_to_process, punc_char_idx, config.SENTENCE_END_PUNCTUATIONS):
                    found_punc_at = punc_char_idx
                    break
            
            if found_punc_at != -1:
                sub_segment_text = text_to_process[:found_punc_at + 1]
                len_sub_segment = len(sub_segment_text)
                # Estimate duration proportionally to the original segment's duration
                # This is an estimate; final segment duration is recalculated later.
                estimated_duration = (len_sub_segment / original_text_len) * original_duration
                
                fine_grained_entries.append({
                    'text': sub_segment_text,
                    'start': current_sub_segment_start_time,
                    'duration': estimated_duration
                })
                current_sub_segment_start_time += estimated_duration
                text_to_process = text_to_process[found_punc_at + 1:].lstrip() # Process remainder
            else:
                # No more sentence-ending punctuations in the remainder of this original entry
                if text_to_process: # If there's any text left
                    remaining_len = len(text_to_process)
                    # Estimate duration for the remainder
                    estimated_duration = (remaining_len / original_text_len) * original_duration
                    # Ensure total duration of pieces doesn't wildly exceed original from this one entry
                    # This is tricky; a simpler approach is to just use proportional as well, or remaining original duration. 
                    # For now, proportional. The main merge logic re-calculates final segment duration.

                    fine_grained_entries.append({
                        'text': text_to_process,
                        'start': current_sub_segment_start_time,
                        'duration': estimated_duration 
                    })
                text_to_process = "" # All processed for this original entry
        
    print(f"Pass 2: Pre-splitting complete. {len(fine_grained_entries)} fine-grained entries generated.")

    # --- Pass 3: Merge fine-grained entries based ONLY on SENTENCE_END_PUNCTUATIONS at the very end --- 
    print(f"\nPass 3: Merging fine-grained entries (Punctuation ONLY at end of accumulation)...")
    print(f"Configured Sentence End Punctuations: {config.SENTENCE_END_PUNCTUATIONS}\n")

    final_merged_segments = []
    current_accumulated_fine_grained_entries = [] 

    for i, fg_entry_dict in enumerate(fine_grained_entries):
        current_accumulated_fine_grained_entries.append(fg_entry_dict)
        current_segment_text = " ".join(e['text'] for e in current_accumulated_fine_grained_entries)

        if current_segment_text and _is_actual_sentence_end_char(current_segment_text, len(current_segment_text)-1, config.SENTENCE_END_PUNCTUATIONS):
            segment_start_time = current_accumulated_fine_grained_entries[0]['start']
            segment_end_time = current_accumulated_fine_grained_entries[-1]['start'] + current_accumulated_fine_grained_entries[-1]['duration']
            segment_duration = segment_end_time - segment_start_time
            
            final_merged_segments.append({
                'text': current_segment_text,
                'start': segment_start_time,
                'duration': segment_duration
            })
            current_accumulated_fine_grained_entries = [] 
        else:
            pass # Explicitly passing if no action needed

    if current_accumulated_fine_grained_entries:
        print(f"\n  Pass 3 - Finalizing remaining accumulated fine-grained entries as the last segment.")
        segment_text = " ".join(e['text'] for e in current_accumulated_fine_grained_entries)
        segment_start_time = current_accumulated_fine_grained_entries[0]['start']
        segment_end_time = current_accumulated_fine_grained_entries[-1]['start'] + current_accumulated_fine_grained_entries[-1]['duration']
        segment_duration = segment_end_time - segment_start_time
        
        final_merged_segments.append({
            'text': segment_text,
            'start': segment_start_time,
            'duration': segment_duration
        })
    
    print(f"\n--- Pre-segmentation and Merging Logic Finished. Total segments: {len(final_merged_segments)} ---")
    return final_merged_segments

def transcript_to_markdown(transcript_data, lang_code, source_type, video_id):
    """Converts transcript data (list of dicts) to Markdown with timestamps."""
    md_content = [f"# YouTube Video Transcript: {video_id}\n"]
    md_content.append(f"**Source Language:** {lang_code}")
    md_content.append(f"**Source Type:** {source_type} subtitles\n")
    
    for entry in transcript_data:
        start_time = format_time(entry['start'])
        # Duration might not always be perfectly accurate for end time with some APIs,
        # but youtube-transcript-api provides start and duration.
        end_time = format_time(entry['start'] + entry['duration'])
        text = entry['text']
        md_content.append(f"## {start_time} --> {end_time}\n{text}\n")
    return "\n".join(md_content)

def _parse_time_part(time_str_part):
    """Helper to parse a single time string like HH:MM:SS,ms or MM:SS,ms etc."""
    h, m, s, ms = 0, 0, 0, 0
    try:
        main_and_ms = time_str_part.split(',')
        if len(main_and_ms) != 2:
            # print(f"DEBUG: _parse_time_part: Invalid main/ms split for '{time_str_part}'")
            return None
        ms = int(main_and_ms[1])
        
        hms_parts = main_and_ms[0].split(':')
        if len(hms_parts) == 3: # HH:MM:SS
            h = int(hms_parts[0])
            m = int(hms_parts[1])
            s = int(hms_parts[2])
        elif len(hms_parts) == 2: # MM:SS
            m = int(hms_parts[0])
            s = int(hms_parts[1])
        elif len(hms_parts) == 1: # SS
            s = int(hms_parts[0])
        else:
            # print(f"DEBUG: _parse_time_part: Invalid h/m/s part count for '{main_and_ms[0]}'")
            return None
        
        # Basic validation for parsed values (optional, but good practice)
        if not (0 <= h <= 99 and 0 <= m <= 59 and 0 <= s <= 59 and 0 <= ms <= 999):
            # print(f"DEBUG: _parse_time_part: Parsed time values out of range for '{time_str_part}'")
            return None
            
        return h, m, s, ms
    except ValueError:
        # print(f"DEBUG: _parse_time_part: ValueError during int conversion for '{time_str_part}'")
        return None
    except Exception as e:
        # print(f"DEBUG: _parse_time_part: Generic error for '{time_str_part}': {e}")
        return None

def _normalize_timestamp_id(id_str):
    """Normalizes a timestamp ID string like 'HH:MM:SS,ms --> HH:MM:SS,ms' to a consistent format."""
    if not id_str or not isinstance(id_str, str):
        return f"ERROR_NORM_INVALID_INPUT_TYPE__{id_str}"
    
    id_str_stripped = id_str.strip()
    parts = id_str_stripped.split("-->")
    if len(parts) != 2:
        return f"ERROR_NORM_NO_ARROW_SEPARATOR__{id_str_stripped}"
        
    start_parsed = _parse_time_part(parts[0].strip())
    end_parsed = _parse_time_part(parts[1].strip())
    
    if not start_parsed:
        return f"ERROR_NORM_START_PARSE_FAILED__{id_str_stripped}"
    if not end_parsed:
        return f"ERROR_NORM_END_PARSE_FAILED__{id_str_stripped}"
        
    sh, sm, ss, sms = start_parsed
    eh, em, es, ems = end_parsed
    
    return (f"{sh:02d}:{sm:02d}:{ss:02d},{sms:03d} --> "
            f"{eh:02d}:{em:02d}:{es:02d},{ems:03d}")

def translate_text_segments(transcript_data_processed, 
                            source_lang_code, 
                            target_lang="zh-CN"):
    """
    Translates a list of processed transcript segments (with text, start, duration)
    using the configured LLM provider, via batched JSON objects.
    """
    print(f"\n--- LLM Provider from config: {config.LLM_PROVIDER} ---")
    
    if not transcript_data_processed:
        print("No segments to translate.")
        return []

    json_segments_to_translate = []
    for item in transcript_data_processed:
        original_raw_id = format_time(item['start']) + " --> " + format_time(item['start'] + item['duration'])
        json_segments_to_translate.append({
            "id": original_raw_id, 
            "text_en": item['text'] 
        })

    translations_map = {} 

    if config.LLM_PROVIDER == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("Error: GEMINI_API_KEY not found. Translation will be skipped.")
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
            print(f"Using Gemini model: {config.LLM_MODEL_GEMINI} for translation from '{source_lang_code}' to '{target_lang}' (JSON mode, temperature=0.0)." )
            print(f"Target prompt tokens per batch: {config.TARGET_PROMPT_TOKENS_PER_BATCH}, Max segments per batch: {config.MAX_SEGMENTS_PER_GEMINI_JSON_BATCH}")

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
                    f"{id_preservation_instruction} " # Use the chosen instruction
                    "The segments are ordered chronologically and provide context for each other. "
                    "Ensure the number of objects in the 'translated_segments' array exactly matches the number of input segments."
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
                    "Pay EXTREME ATTENTION to the ID PRESERVATION requirement detailed in the instructions: the 'id' field for each segment in your response MUST be an IDENTICAL, UNCHANGED copy of the 'id' field from the input segment.\\n\\n"
                    f"JSON Request:\\n```json\\n{json.dumps(json_payload_for_prompt, indent=2, ensure_ascii=False)}\\n```"
                )

            all_batches = []
            current_batch_input_segments = [] 

            # Flag to control the ID strategy
            USE_SIMPLIFIED_IDS_EXPERIMENTAL = True
            if USE_SIMPLIFIED_IDS_EXPERIMENTAL:
                print("INFO: Using SIMPLIFIED IDs (seg_N) for translation batches.")

            for seg_obj in json_segments_to_translate:
                potential_segments_for_this_batch = current_batch_input_segments + [seg_obj]
                
                # Token counting prompt generation will use original IDs for now.
                # This is a slight overestimation if simplified IDs are shorter, which is generally safe.
                # To be extremely precise, this prompt construction would also need to be aware of USE_SIMPLIFIED_IDS_EXPERIMENTAL
                # and create a temporary list with simplified IDs for counting if that flag is True.
                # For now, we keep it as is, as the impact is likely small.
                prompt_if_added = _construct_prompt_string_for_batch(
                    potential_segments_for_this_batch, 
                    source_lang_code, 
                    target_lang, 
                    output_text_field_key,
                    use_simplified_ids=False # For token counting, assume original ID format complexity
                )
                try:
                    num_tokens_if_added = model.count_tokens(prompt_if_added).total_tokens
                except Exception as e_count:
                    print(f"  Warning: Token counting failed for a potential batch. Error: {e_count}. Proceeding with segment count only for this decision.")
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

            print(f"Prepared {len(json_segments_to_translate)} segments into {len(all_batches)} batches for translation based on token/segment limits.")

            for batch_idx, actual_batch_segments in enumerate(all_batches):
                if not actual_batch_segments:
                    continue
                print(f"Translating Batch {batch_idx + 1}/{len(all_batches)} with {len(actual_batch_segments)} segments...")

                segments_for_payload_this_batch = []
                if USE_SIMPLIFIED_IDS_EXPERIMENTAL:
                    for i, seg_data in enumerate(actual_batch_segments):
                        segments_for_payload_this_batch.append({
                            "id": f"seg_{i}",
                            "text_en": seg_data["text_en"]
                        })
                else:
                    segments_for_payload_this_batch = actual_batch_segments # Use as is

                prompt_to_send = _construct_prompt_string_for_batch(
                    segments_for_payload_this_batch, 
                    source_lang_code, 
                    target_lang, 
                    output_text_field_key,
                    use_simplified_ids=USE_SIMPLIFIED_IDS_EXPERIMENTAL # Pass the flag
                )
                
                try:
                    response = model.generate_content(prompt_to_send)
                    if not response.parts:
                         print(f"  Warning: Gemini response for batch {batch_idx+1} has no parts. Using originals.")
                         for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_EMPTY_RESPONSE] {seg['text_en']}"
                         continue
                    try:
                        translated_json_str = response.text 
                        translated_data = json.loads(translated_json_str)
                        if 'translated_segments' not in translated_data or not isinstance(translated_data['translated_segments'], list):
                            print(f"  Warning: 'translated_segments' array not found/invalid in response for batch {batch_idx+1}. Raw: {translated_json_str[:200]}... Using originals.")
                            for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_BAD_JSON_STRUCTURE] {seg['text_en']}"
                            continue
                        translated_batch_segments_from_response = translated_data['translated_segments']
                        if len(translated_batch_segments_from_response) != len(actual_batch_segments):
                            print(f"  Warning: Mismatch in translated segments for batch {batch_idx+1} (expected {len(actual_batch_segments)}, got {len(translated_batch_segments_from_response)}). Using originals for this batch.")
                            for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[NO_TRANSLATION_SEG_COUNT_MISMATCH] {seg['text_en']}"
                            continue
                        
                        # Revised loop for processing translated segments
                        for i, translated_seg_item in enumerate(translated_batch_segments_from_response):
                            original_complex_id_from_actual_batch = actual_batch_segments[i]["id"]
                            text_en_from_actual_batch = actual_batch_segments[i]["text_en"]
                            
                            map_key = _normalize_timestamp_id(original_complex_id_from_actual_batch)

                            if USE_SIMPLIFIED_IDS_EXPERIMENTAL:
                                expected_simple_id = f"seg_{i}"
                                model_returned_simple_id = translated_seg_item.get("id")

                                if not model_returned_simple_id:
                                    print(f"  Warning: ID missing in translated segment. Batch {batch_idx+1}. Expected simple ID '{expected_simple_id}' (for original: '{original_complex_id_from_actual_batch}'). Skipping.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISSING_IN_RESPONSE] {text_en_from_actual_batch}"
                                    continue
                                if model_returned_simple_id != expected_simple_id:
                                    print(f"  Warning: Simple ID mismatch from model. Batch {batch_idx+1}.\\n     Expected: '{expected_simple_id}' (for original: '{original_complex_id_from_actual_batch}')\\n     Model Returned: '{model_returned_simple_id}'. Skipping.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_SIMPLE_ID_MISMATCH] {text_en_from_actual_batch}"
                                    continue
                                # If we are here, simple ID from model is correct and matches expected.
                            else: # Original (complex) ID logic
                                translated_id_from_model = translated_seg_item.get("id")
                                if not translated_id_from_model:
                                    print(f"  Warning: ID missing in translated segment for original ID '{original_complex_id_from_actual_batch}' in batch {batch_idx+1}. Skipping.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISSING_IN_RESPONSE] {text_en_from_actual_batch}"
                                    continue

                                normalized_translated_id = _normalize_timestamp_id(translated_id_from_model)
                                
                                if map_key != normalized_translated_id: # map_key is already the normalized original complex ID
                                    print(f"  Warning: ID mismatch after attempting to normalize model response. Batch {batch_idx+1}.\\n     Original (Normalized): '{map_key}'\\n     Model Output Raw : '{translated_id_from_model}'\\n     Model OutputNormd: '{normalized_translated_id}'. Skipping segment.")
                                    translations_map[map_key] = f"[NO_TRANSLATION_ID_MISMATCH_NORM_FAILED_OR_VALUE_DIFF] {text_en_from_actual_batch}"
                                    continue
                            
                            # Common logic for checking text field and storing translation
                            if output_text_field_key not in translated_seg_item:
                                id_for_error_msg = f"seg_{i}" if USE_SIMPLIFIED_IDS_EXPERIMENTAL else original_complex_id_from_actual_batch
                                print(f"  Warning: Expected field '{output_text_field_key}' not found for ID '{id_for_error_msg}' in batch {batch_idx+1}. Using original.")
                                translations_map[map_key] = f"[NO_TRANSLATION_MISSING_TEXT_FIELD] {text_en_from_actual_batch}"
                                continue
                            
                            translations_map[map_key] = translated_seg_item[output_text_field_key]
                        print(f"  Batch {batch_idx + 1} translated successfully.")
                    except json.JSONDecodeError as e_json:
                        print(f"  Error decoding JSON response from Gemini for batch {batch_idx+1}: {e_json}. Raw: {response.text[:500] if response.text else 'EMPTY'}")
                        for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[ERROR_JSON_DECODE] {seg['text_en']}"
                    except Exception as e_resp_proc:
                        print(f"  Error processing response from Gemini for batch {batch_idx+1}: {e_resp_proc}")
                        for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[ERROR_RESP_PROCESSING] {seg['text_en']}"
                except Exception as e_api_call:
                    print(f"  An error occurred during Gemini API call for batch {batch_idx+1}: {e_api_call}. This might be due to the batch size exceeding model limits even after token counting.")
                    for seg in actual_batch_segments: translations_map[_normalize_timestamp_id(seg["id"])] = f"[ERROR_API_CALL] {seg['text_en']}"
                
                delay_seconds = getattr(config, 'LLM_REQUEST_DELAY', 0)
                if delay_seconds > 0 and batch_idx < len(all_batches) - 1 :
                    print(f"  Waiting for {delay_seconds}s before next batch...")
                    time.sleep(delay_seconds)

            final_translated_texts = []
            for seg_obj_orig in json_segments_to_translate:
                # Normalize the ID from the original segment list before looking up in the map
                normalized_key_to_lookup = _normalize_timestamp_id(seg_obj_orig["id"])
                
                # Prepare a more informative default message if translation is not found
                default_not_found_message = (
                    f"[TRANSLATION_NOT_FOUND_FOR_ID:{seg_obj_orig['id']}] "
                    f"[NORMALIZED_AS:{normalized_key_to_lookup}] "
                    f"{seg_obj_orig['text_en']}"
                )

                final_translated_texts.append(
                    translations_map.get(normalized_key_to_lookup, default_not_found_message)
                )
            
            if len(final_translated_texts) != len(json_segments_to_translate):
                 print(f"Critical Warning: Final translated segment count ({len(final_translated_texts)}) MISMATCHES original segment count ({len(json_segments_to_translate)}).")
            
            print(f"--- Gemini JSON translation processing complete. ---")
            return final_translated_texts
        except Exception as e:
            print(f"A critical error occurred during Gemini JSON setup or outer processing loop: {e}")
            return [f"[CRITICAL_ERROR_TRANSLATING] {s['text_en']}" for s in json_segments_to_translate]
    else:
        print(f"Unsupported or misconfigured LLM_PROVIDER: {config.LLM_PROVIDER}. Using simulated translation.")
        simulated_translated_segments = []
        for seg_obj in json_segments_to_translate: 
            translated_text = f"[译] {seg_obj['text_en']}" 
            simulated_translated_segments.append(translated_text)
        print("--- Simulated translation complete ---")
        return simulated_translated_segments

def reconstruct_translated_srt(original_transcript_data, translated_texts):
    """Reconstructs SRT from original timestamps and translated texts."""
    if len(original_transcript_data) != len(translated_texts):
        print("Warning: Mismatch between original transcript entries and translated texts count.")
        # Pad or truncate translated_texts if necessary, or handle error more gracefully
        # For now, we'll proceed but this might lead to incorrect SRT.
        # A robust solution would be to ensure the translation function returns a list of the same length.
    
    srt_content = []
    min_len = min(len(original_transcript_data), len(translated_texts))
    for i in range(min_len):
        entry = original_transcript_data[i]
        start_time = format_time(entry['start'])
        end_time = format_time(entry['start'] + entry['duration'])
        text = translated_texts[i]
        srt_content.append(f"{i+1}\n{start_time} --> {end_time}\n{text}\n")
    return "\n".join(srt_content)

def reconstruct_translated_markdown(original_transcript_data, translated_texts, original_lang, source_type, target_lang="zh-CN", video_id=""):
    """Reconstructs Markdown from original timestamps (list of dicts) and translated texts."""
    if len(original_transcript_data) != len(translated_texts):
        print("Warning: Mismatch between original transcript entries and translated texts count during MD reconstruction.")

    md_content = [f"# YouTube Video Translation: {video_id}\n"]
    md_content.append(f"**Original Language:** {original_lang} ({source_type})")
    md_content.append(f"**Translated Language:** {target_lang}\n")
    
    min_len = min(len(original_transcript_data), len(translated_texts))
    for i in range(min_len):
        entry = original_transcript_data[i]
        start_time = format_time(entry['start'])
        end_time = format_time(entry['start'] + entry['duration'])
        text = translated_texts[i]
        md_content.append(f"## {start_time} --> {end_time}\n{text}\n")
    return "\n".join(md_content)

def save_to_file(content, filename):
    """Saves content to a file."""
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Successfully saved to {filename}")
    except IOError as e:
        print(f"Error saving file {filename}: {e}")

def get_video_id(url_or_id):
    if "youtube.com/watch?v=" in url_or_id:
        return url_or_id.split("watch?v=")[1].split("&")[0]
    elif "youtu.be/" in url_or_id:
        return url_or_id.split("youtu.be/")[1].split("?")[0]
    return url_or_id # Assume it's already an ID if no common URL patterns match

def main():
    parser = argparse.ArgumentParser(description="Translate YouTube video subtitles.")
    parser.add_argument("video_url_or_id", help="The URL or ID of the YouTube video.")
    parser.add_argument("--output_basename", help="Basename for output files (e.g., 'my_video'). Defaults to video ID.", default=None)
    parser.add_argument("--target_lang", help="Target language for translation (e.g., 'zh-CN', 'zh-Hans').", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
    args = parser.parse_args()
    load_dotenv()
    video_id = get_video_id(args.video_url_or_id)
    base_filename = args.output_basename if args.output_basename else video_id
    print(f"Processing video: {video_id} (from input: {args.video_url_or_id})")
    raw_transcript_data, lang_code, source_type = get_youtube_transcript(video_id)
    if not raw_transcript_data:
        print("Could not retrieve transcript. Exiting.")
        return
    print(f"Successfully fetched raw transcript in '{lang_code}' ({source_type}). Original segment count: {len(raw_transcript_data)}.")
    print("Preprocessing and merging transcript segments...")
    merged_transcript_data = preprocess_and_merge_segments(raw_transcript_data)
    if not merged_transcript_data:
        print("Transcript data is empty after preprocessing and merging. Exiting.")
        return
    print(f"Preprocessing complete. Merged into {len(merged_transcript_data)} segments.")
    transcript_data_for_processing = merged_transcript_data
    original_md = transcript_to_markdown(transcript_data_for_processing, lang_code, source_type, video_id)
    original_md_filename = f"{base_filename}_original_merged_{lang_code}.md"
    save_to_file(original_md, original_md_filename)
    
    # --- MODIFICATION: Temporarily comment out/remove skip for testing translation ---
    # print("\nSkipping translation and generation of translated files as per request.")
    # print(f"Original merged transcript (MD) saved to: {original_md_filename}")
    # print("\nProcessing finished up to the original merged Markdown generation.")
    # return # Exit main function early
    # --- END OF MODIFICATION ---

    # 2. Text segments for translation are now implicitly handled by new translate_text_segments
    
    # 3. Translate
    print(f"\nStarting translation from '{lang_code}' to '{args.target_lang}' using new JSON method...")
    translated_texts = translate_text_segments(
        transcript_data_for_processing, 
        lang_code,                      
        args.target_lang                
    )

    if not translated_texts :
        print("Translation failed or returned no segments. Exiting.")
        return
    if len(translated_texts) != len(transcript_data_for_processing):
         print(f"Warning: Number of translated segments ({len(translated_texts)}) does not match original ({len(transcript_data_for_processing)}). Results might be incomplete or misaligned.")

    translated_md_filename = f"{base_filename}_translated_{args.target_lang}.md"
    translated_md_content = reconstruct_translated_markdown(transcript_data_for_processing, translated_texts, lang_code, source_type, args.target_lang, video_id)
    save_to_file(translated_md_content, translated_md_filename)

    translated_srt_filename = f"{base_filename}_translated_{args.target_lang}.srt"
    translated_srt_content = reconstruct_translated_srt(transcript_data_for_processing, translated_texts)
    save_to_file(translated_srt_content, translated_srt_filename)

    print("\nAll tasks completed!")
    print(f"Original transcript (MD): {original_md_filename}")
    print(f"Translated transcript (MD): {translated_md_filename}")
    print(f"Translated transcript (SRT): {translated_srt_filename}")

if __name__ == "__main__":
    main()