import json

def construct_prompt_for_batch(segments_list_for_payload, src_lang, tgt_lang, out_text_key, use_simplified_ids=False):
    """
    Constructs the full prompt string for a batch of segments to be translated by the LLM.

    Args:
        segments_list_for_payload (list): The list of segment objects for this batch.
        src_lang (str): The source language code.
        tgt_lang (str): The target language code.
        out_text_key (str): The key to be used for the translated text in the output JSON.
        use_simplified_ids (bool): If True, use simplified 'seg_N' IDs and instructions.

    Returns:
        str: The complete prompt string to be sent to the LLM.
    """
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