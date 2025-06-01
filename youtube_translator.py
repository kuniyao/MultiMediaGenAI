import argparse
import os # Added for .env
from dotenv import load_dotenv # Added for .env
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
import config # Added for config.py
import google.generativeai as genai # Added for Gemini
import time # Added for time.sleep if using batch delays

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

def format_time(seconds):
    """Converts seconds to SRT time format (HH:MM:SS,ms)"""
    millis = int(round((seconds - int(seconds)) * 1000))
    seconds = int(seconds)
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

def transcript_to_markdown(transcript_data, lang_code, source_type, video_id):
    """Converts transcript data to Markdown with timestamps."""
    md_content = [f"# YouTube Video Transcript: {video_id}\n"]
    md_content.append(f"**Source Language:** {lang_code}")
    md_content.append(f"**Source Type:** {source_type} subtitles\n")
    
    for entry in transcript_data:
        start_time = format_time(entry.start)
        # Duration might not always be perfectly accurate for end time with some APIs,
        # but youtube-transcript-api provides start and duration.
        end_time = format_time(entry.start + entry.duration)
        text = entry.text
        md_content.append(f"## {start_time} --> {end_time}\n{text}\n")
    return "\n".join(md_content)

def translate_text_segments(text_segments, target_language="zh-CN"):
    """
    Translates a list of text segments using the configured LLM provider,
    with a multi-level batching strategy for Gemini.
    """
    print(f"\n--- LLM Provider from config: {config.LLM_PROVIDER} ---")
    translated_segments_final = []

    if config.LLM_PROVIDER == "gemini":
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("Error: GEMINI_API_KEY not found. Translation will be skipped.")
            return [f"[SKIPPED_NO_KEY] {s}" for s in text_segments]

        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(config.LLM_MODEL_GEMINI)
            print(f"Using Gemini model: {config.LLM_MODEL_GEMINI} for translation to {target_language}.")
            print(f"Primary batch char limit: {config.TARGET_INPUT_CHAR_LIMIT_PER_BATCH}, Fallback batch segments: {config.FALLBACK_BATCH_MAX_SEGMENTS}, Fallback char limit: {config.FALLBACK_BATCH_CHAR_LIMIT}")

            # Helper function to attempt translation for a given batch of segments
            def _translate_batch_attempt(batch_to_translate, batch_label="Primary Batch"):
                if not batch_to_translate:
                    return [], True # No segments, success (nothing to do)

                print(f"Attempting {batch_label} of {len(batch_to_translate)} segments...")
                batch_text_to_translate = config.SEGMENT_SEPARATOR.join(batch_to_translate)
                
                prompt = (
                    f"You are a helpful translation assistant. Translate the following text segments from their original language to {target_language}. "
                    f"The segments are separated by '{config.SEGMENT_SEPARATOR.strip()}'. "
                    f"Please maintain the same number of segments in your output, using the exact same separator. "
                    f"Each translated segment should correspond to its original segment. Do not add any extra explanatory text before or after the translated segments block."
                    f"\n\nTEXT TO TRANSLATE:\n{batch_text_to_translate}"
                )
                try:
                    response = model.generate_content(prompt)
                    translated_batch_text = ""
                    if response.parts:
                        translated_batch_text = response.parts[0].text
                    elif hasattr(response, 'text') and response.text:
                        translated_batch_text = response.text
                    else:
                        print(f"Warning: No text returned for {batch_label}. Using original segments.")
                        return [f"[NO_TRANSLATION_{batch_label.upper().replace(' ', '_')}] {s}" for s in batch_to_translate], False # Indicate failure

                    translated_segments_from_batch = translated_batch_text.strip().split(config.SEGMENT_SEPARATOR)

                    if len(translated_segments_from_batch) == len(batch_to_translate):
                        print(f"{batch_label} translated successfully: {len(translated_segments_from_batch)} segments.")
                        return translated_segments_from_batch, True # Success
                    else:
                        print(f"Warning: Mismatch in translated segments for {batch_label} (expected {len(batch_to_translate)}, got {len(translated_segments_from_batch)}). Response: '{translated_batch_text[:200]}...'")
                        return None, False # Indicate failure, no segments returned directly for retry at this level
                
                except Exception as e_batch_attempt:
                    print(f"An error occurred during {batch_label} Gemini translation: {e_batch_attempt}")
                    return None, False # Indicate failure

            # Helper function for final fallback: individual translation
            def _translate_individually(segments_to_translate_individually, original_batch_label="Failed Batch"):
                individual_translations = []
                print(f"Falling back to individual translation for {len(segments_to_translate_individually)} segments from {original_batch_label}.")
                for k_fallback, seg_to_translate in enumerate(segments_to_translate_individually):
                    fallback_prompt = f"Translate the following text to {target_language}:\n\n\"{seg_to_translate}\""
                    try:
                        fallback_response = model.generate_content(fallback_prompt)
                        if fallback_response.parts:
                            individual_translations.append(fallback_response.parts[0].text)
                        elif hasattr(fallback_response, 'text') and fallback_response.text:
                            individual_translations.append(fallback_response.text)
                        else:
                            individual_translations.append(f"[NO_INDIVIDUAL_TRANSLATION] {seg_to_translate}")
                    except Exception as e_individual:
                        print(f"Error during individual fallback translation for segment: {e_individual}")
                        individual_translations.append(f"[ERROR_INDIVIDUAL_TRANSLATING] {seg_to_translate}")
                    if (k_fallback + 1) % 20 == 0 or (k_fallback + 1) == len(segments_to_translate_individually): # Log every 20 or at the end
                         print(f"Individual fallback translated segment {k_fallback+1}/{len(segments_to_translate_individually)} of {original_batch_label}.")
                return individual_translations

            # Main batching loop
            current_primary_batch = []
            current_primary_batch_char_count = 0
            total_segments = len(text_segments)
            
            for i, segment in enumerate(text_segments):
                segment_char_count = len(segment)
                should_add_to_primary_batch = True
                if current_primary_batch and (current_primary_batch_char_count + segment_char_count + len(config.SEGMENT_SEPARATOR) > config.TARGET_INPUT_CHAR_LIMIT_PER_BATCH):
                    should_add_to_primary_batch = False
                
                if should_add_to_primary_batch:
                    current_primary_batch.append(segment)
                    current_primary_batch_char_count += segment_char_count

                if not should_add_to_primary_batch or (i == total_segments - 1):
                    if not current_primary_batch:
                        if not should_add_to_primary_batch: # Single large segment
                             current_primary_batch.append(segment)
                             current_primary_batch_char_count += segment_char_count
                        else: # Empty list of segments to process
                            continue 
                    
                    # Attempt 1: Primary large batch
                    translated_slice, success = _translate_batch_attempt(current_primary_batch, "Primary Batch")

                    if success:
                        translated_segments_final.extend(translated_slice)
                    else:
                        # Attempt 2: Fallback to smaller batches
                        print(f"Primary batch failed. Trying fallback with smaller batches for {len(current_primary_batch)} segments.")
                        segments_from_failed_primary = list(current_primary_batch) # Make a copy
                        
                        current_fallback_batch = []
                        current_fallback_batch_char_count = 0
                        
                        for j, fallback_segment in enumerate(segments_from_failed_primary):
                            fallback_segment_char_count = len(fallback_segment)
                            should_add_to_fallback_batch = True
                            
                            if current_fallback_batch and \
                               ((len(current_fallback_batch) >= config.FALLBACK_BATCH_MAX_SEGMENTS) or \
                                (current_fallback_batch_char_count + fallback_segment_char_count + len(config.SEGMENT_SEPARATOR) > config.FALLBACK_BATCH_CHAR_LIMIT)):
                                should_add_to_fallback_batch = False

                            if should_add_to_fallback_batch:
                                current_fallback_batch.append(fallback_segment)
                                current_fallback_batch_char_count += fallback_segment_char_count
                            
                            if not should_add_to_fallback_batch or (j == len(segments_from_failed_primary) - 1):
                                if not current_fallback_batch:
                                    if not should_add_to_fallback_batch: # Single large segment in fallback
                                        current_fallback_batch.append(fallback_segment)
                                        current_fallback_batch_char_count += fallback_segment_char_count
                                    else:
                                        continue

                                fallback_translated_slice, fallback_success = _translate_batch_attempt(current_fallback_batch, "Fallback Batch")
                                if fallback_success:
                                    translated_segments_final.extend(fallback_translated_slice)
                                else:
                                    # Attempt 3: Final fallback to individual translation for this failed fallback_batch
                                    individual_translations = _translate_individually(current_fallback_batch, "Failed Fallback Batch")
                                    translated_segments_final.extend(individual_translations)
                                
                                current_fallback_batch = []
                                current_fallback_batch_char_count = 0
                                if not should_add_to_fallback_batch: # Add current segment to the next fallback batch
                                    current_fallback_batch.append(fallback_segment)
                                    current_fallback_batch_char_count += fallback_segment_char_count
                                    
                    # Reset for next primary batch
                    current_primary_batch = []
                    current_primary_batch_char_count = 0
                    if not should_add_to_primary_batch: # Add current segment to the next primary batch
                        current_primary_batch.append(segment)
                        current_primary_batch_char_count += segment_char_count
            
            print(f"--- Gemini batch translation processing complete. Total translated segments: {len(translated_segments_final)} ---")
            if len(translated_segments_final) != total_segments:
                 print(f"Critical Warning: Final translated segment count ({len(translated_segments_final)}) MISMATCHES total original segments ({total_segments}).")
            return translated_segments_final

        except Exception as e:
            print(f"A critical error occurred during Gemini setup or outer processing loop: {e}")
            return [f"[CRITICAL_ERROR_TRANSLATING] {s}" for s in text_segments]

    # Placeholder for OpenAI or other providers - you would add elif blocks here
    # elif config.LLM_PROVIDER == "openai":
    #     # ... OpenAI specific logic ...
    #     pass

    else:
        # Fallback to simulated translation if no provider is matched or configured
        print(f"Unsupported or misconfigured LLM_PROVIDER: {config.LLM_PROVIDER}. Using simulated translation.")
        print(f"--- Sending {len(text_segments)} segments for translation to {target_language} (SIMULATED) ---")
        # Simulate segment-wise processing for consistency in logging
        simulated_translated_segments = []
        for i, segment in enumerate(text_segments):
            translated_text = f"[译] {segment}" 
            simulated_translated_segments.append(translated_text)
            if (i + 1) % 100 == 0 or (i + 1) == len(text_segments): # Log every 100 or at the end
                print(f"Simulated translation for {i+1}/{len(text_segments)} segments...")
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
        start_time = format_time(entry.start)
        end_time = format_time(entry.start + entry.duration)
        text = translated_texts[i]
        srt_content.append(f"{i+1}\n{start_time} --> {end_time}\n{text}\n")
    return "\n".join(srt_content)

def reconstruct_translated_markdown(original_transcript_data, translated_texts, original_lang, source_type, target_lang="zh-CN", video_id=""):
    """Reconstructs Markdown from original timestamps and translated texts."""
    if len(original_transcript_data) != len(translated_texts):
        print("Warning: Mismatch between original transcript entries and translated texts count during MD reconstruction.")

    md_content = [f"# YouTube Video Translation: {video_id}\n"]
    md_content.append(f"**Original Language:** {original_lang} ({source_type})")
    md_content.append(f"**Translated Language:** {target_lang}\n")
    
    min_len = min(len(original_transcript_data), len(translated_texts))
    for i in range(min_len):
        entry = original_transcript_data[i]
        start_time = format_time(entry.start)
        end_time = format_time(entry.start + entry.duration)
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
    # Use default target language from config
    parser.add_argument("--target_lang", help="Target language for translation (e.g., 'zh-CN', 'zh-Hans').", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)

    args = parser.parse_args()
    
    # Load environment variables from .env file
    load_dotenv()

    video_id = get_video_id(args.video_url_or_id)
    base_filename = args.output_basename if args.output_basename else video_id

    print(f"Processing video: {video_id} (from input: {args.video_url_or_id})")
    transcript_data, lang_code, source_type = get_youtube_transcript(video_id)

    if not transcript_data:
        print("Could not retrieve transcript. Exiting.")
        return

    print(f"Successfully fetched transcript in '{lang_code}' ({source_type}).")

    # 1. Original Markdown with timestamps
    original_md = transcript_to_markdown(transcript_data, lang_code, source_type, video_id)
    original_md_filename = f"{base_filename}_original_{lang_code}.md"
    save_to_file(original_md, original_md_filename)
    
    # 2. Extract text segments for translation
    text_segments_to_translate = [entry.text for entry in transcript_data]
    
    # 3. Translate (using placeholder)
    print(f"\nStarting translation to {args.target_lang}...")
    translated_texts = translate_text_segments(text_segments_to_translate, args.target_lang)

    if not translated_texts : # Basic check, real LLM might return empty for some inputs
        print("Translation (simulated) failed or returned no segments. Exiting.")
        return
    if len(translated_texts) != len(text_segments_to_translate):
         print(f"Warning: Number of translated segments ({len(translated_texts)}) does not match original ({len(text_segments_to_translate)}). Results might be incomplete or misaligned.")


    # 4. Reconstruct translated Markdown
    translated_md_filename = f"{base_filename}_translated_{args.target_lang}.md"
    translated_md_content = reconstruct_translated_markdown(transcript_data, translated_texts, lang_code, source_type, args.target_lang, video_id)
    save_to_file(translated_md_content, translated_md_filename)

    # 5. Reconstruct translated SRT
    translated_srt_filename = f"{base_filename}_translated_{args.target_lang}.srt"
    translated_srt_content = reconstruct_translated_srt(transcript_data, translated_texts)
    save_to_file(translated_srt_content, translated_srt_filename)

    print("\nAll tasks completed!")
    print(f"Original transcript (MD): {original_md_filename}")
    print(f"Translated transcript (MD): {translated_md_filename}")
    print(f"Translated transcript (SRT): {translated_srt_filename}")

if __name__ == "__main__":
    main()