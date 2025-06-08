import json
import logging
from format_converters import format_time # Assuming this is accessible

def create_pre_translate_json_objects(processed_segments, video_id, original_lang, source_type, logger=None):
    """
    Creates a list of JSON objects ready for translation, including rich metadata.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    output_json_objects = []

    if not processed_segments:
        logger_to_use.info("No processed segments provided to create_pre_translate_json_objects.")
        return output_json_objects

    for i, segment in enumerate(processed_segments):
        if not isinstance(segment, dict) or 'start' not in segment or 'text' not in segment:
            logger_to_use.warning(f"Segment {i} is not a valid dict or missing 'start'/'text': {segment}. Skipping.")
            continue

        start_seconds = segment['start']
        text_to_translate = segment['text']
        duration_seconds = 0 # Default value

        if 'duration' in segment:
            # Use duration directly if it exists (e.g., from YouTube API)
            duration_seconds = segment['duration']
        elif 'end' in segment:
            # Calculate duration if 'end' exists (e.g., from local SRT file)
            duration_seconds = segment['end'] - start_seconds
        else:
            # If neither duration nor end is available, we cannot proceed with this segment.
            logger_to_use.warning(f"Segment {i} is missing a 'duration' or 'end' key to calculate timing: {segment}. Skipping.")
            continue
        
        if duration_seconds < 0:
            logger_to_use.warning(f"Segment {i} has a negative duration ({duration_seconds:.3f}s). Skipping. Data: {segment}")
            continue

        # Create the ID that will be used for LLM processing (matches existing format)
        llm_processing_id = f"{format_time(start_seconds)} --> {format_time(start_seconds + duration_seconds)}"
        
        # Create a more general unique ID for this segment
        segment_guid = f"{video_id}_seg_{i:04d}"

        json_obj = {
            "segment_guid": segment_guid,
            "llm_processing_id": llm_processing_id,
            "text_to_translate": text_to_translate,
            "source_data": {
                "video_id": video_id,
                "original_lang": original_lang,
                "source_type": source_type, # e.g., "manual", "generated"
                "start_seconds": start_seconds,
                "duration_seconds": duration_seconds,
                "start": segment['start'],
                "end": segment.get('end', start_seconds + duration_seconds),
                "text": segment['text']
            }
        }
        output_json_objects.append(json_obj)
    
    logger_to_use.debug(f"Created {len(output_json_objects)} JSON objects for pre-translation.")
    return output_json_objects

def save_json_objects_to_jsonl(json_objects, output_filepath, logger=None):
    """
    Saves a list of JSON objects to a file in JSON Lines format.
    Each JSON object is written to a new line.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    try:
        os.makedirs(os.path.dirname(output_filepath), exist_ok=True) # Ensure directory exists
        with open(output_filepath, 'w', encoding='utf-8') as f:
            for json_obj in json_objects:
                f.write(json.dumps(json_obj, ensure_ascii=False) + '\n')
        logger_to_use.debug(f"Successfully saved {len(json_objects)} JSON objects to {output_filepath}")
        return True
    except IOError as e:
        logger_to_use.error(f"Failed to save JSON objects to {output_filepath}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger_to_use.error(f"An unexpected error occurred while saving JSON objects to {output_filepath}: {e}", exc_info=True)
        return False

# Helper to load from JSONL if needed later (though primary use is saving pre-translate)
def load_json_objects_from_jsonl(input_filepath, logger=None):
    """
    Loads a list of JSON objects from a JSON Lines formatted file.
    """
    logger_to_use = logger if logger else logging.getLogger(__name__)
    json_objects = []
    try:
        with open(input_filepath, 'r', encoding='utf-8') as f:
            for line_number, line in enumerate(f, 1):
                try:
                    stripped_line = line.strip()
                    if stripped_line: # Avoid trying to parse empty lines
                        json_objects.append(json.loads(stripped_line))
                except json.JSONDecodeError as e_json:
                    logger_to_use.error(f"Error decoding JSON on line {line_number} in {input_filepath}: {e_json}. Line content: '{line.strip()[:100]}...'")
                    # Optionally, continue to try and load other lines or re-raise
        logger_to_use.info(f"Successfully loaded {len(json_objects)} JSON objects from {input_filepath}")
        return json_objects
    except FileNotFoundError:
        logger_to_use.error(f"File not found: {input_filepath}")
        return [] # Or raise error
    except IOError as e:
        logger_to_use.error(f"Failed to load JSON objects from {input_filepath}: {e}", exc_info=True)
        return [] # Or raise error
    except Exception as e:
        logger_to_use.error(f"An unexpected error occurred while loading JSON objects from {input_filepath}: {e}", exc_info=True)
        return []

# Need to ensure os is imported if os.makedirs is used
import os 