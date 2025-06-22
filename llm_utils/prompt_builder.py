# llm_utils/prompt_builder.py (MODIFIED FOR STEP 1)

import json
from typing import List, Dict, Optional

def construct_prompt_for_batch(segments_list_for_payload, src_lang, tgt_lang, out_text_key, use_simplified_ids=False):
    """
    Constructs the full prompt string for a batch of segments to be translated by the LLM.
    (This function is for the YouTube workflow and remains unchanged.)
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

def build_translation_prompt(system_prompt: str, user_prompt: str, task_list_json: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"{user_prompt}\n\n{task_list_json}"},
    ]

def build_book_translation_prompt(
    book_title: str,
    source_lang: str,
    target_lang: str,
    tone_style: str,
    writing_style: str,
    task_list_json: str,
    glossary: Optional[Dict[str, str]] = None
) -> str:
    """
    (This function remains unchanged, useful for other potential book-related tasks.)
    """
    
    # 1. 构建Prompt的主要部分
    prompt_parts = [
        f"# ROLE\nYou are an expert literary translator, tasked with translating a chapter from a non-fiction book titled \"{book_title}\" from {source_lang} to {target_lang}.",
        
        f"# TONE & STYLE\nThe original author's tone is {tone_style}. Your translation MUST faithfully capture this specific tone. The writing style is {writing_style}. You must replicate this style in the translated text.",
        
        "# ACCURACY & FIDELITY\nYou must be extremely faithful to the original text. Do not add information that is not present, and do not omit any details. Your primary goal is to convey the author's exact meaning with precision.",
        
        f"# FLUENCY & NATURALNESS\nWhile maintaining accuracy, the final translation must be fluent, natural, and idiomatic in {target_lang}. It should read like it was originally written by a native speaker, not like a literal, robotic translation."
    ]

    # 2. 如果有术语表，则添加术语表部分
    if glossary:
        glossary_items = "\n".join([f'* "{term}": "{translation}"' for term, translation in glossary.items()])
        glossary_section = f"# GLOSSARY (Optional but highly recommended)\nUse the following terms and names consistently. Do not translate them differently.\n{glossary_items}"
        prompt_parts.append(glossary_section)

    # 3. 添加技术指令和任务描述
    prompt_parts.extend([
        "# TECHNICAL INSTRUCTIONS\nThe input text may contain simplified HTML-like tags (e.g., <b> for bold, <i> for italic). You MUST preserve these tags in your translation, wrapping the corresponding translated words.\nFor example, if the input is \"This is <b>important</b>.\", your translated output should be \"这是<b>重要的</b>。\" (This is an example, use the actual translation).",
        
        "# TASK\nNow, please translate the `text_with_markup` field for each JSON object in the following array. Your output MUST be a valid JSON array with the exact same structure, containing the translated text.",
        
        "--- START OF INPUT DATA ---",
        task_list_json,
        "--- END OF INPUT DATA ---"
    ])
    
    return "\n\n".join(prompt_parts)

def build_json_batch_translation_prompt(json_task_string: str, source_lang: str, target_lang: str) -> str:
    """
    【新增函數】
    為包含多個章節HTML的JSON批處理任務構建一個強大的Prompt。
    """
    # 為了示例，我們創建一個小的偽JSON，以展示結構
    example_input = [
        {"id": "text/part0001.html", "html_content": "<h1>Chapter 1</h1><p>This is the <b>first</b> chapter.</p>"},
        {"id": "text/part0002.html", "html_content": "<p>A short second chapter.</p>"}
    ]
    example_output = [
        {"id": "text/part0001.html", "html_content": "<h1>第一章</h1><p>这是<b>第一</b>章。</p>"},
        {"id": "text/part0002.html", "html_content": "<p>一个简短的第二章。</p>"}
    ]

    prompt = f"""
# ROLE & GOAL
You are an expert translator specializing in processing structured JSON data for book translation. Your task is to translate HTML content embedded within a JSON array from {source_lang} to {target_lang}.

# CRITICAL RULES
1.  **INPUT FORMAT**: The user will provide a JSON string that represents an array of objects. Each object contains two keys: "id" (a string) and "html_content" (an HTML string).
2.  **OUTPUT FORMAT**: Your response MUST be a single, valid JSON array. The output array MUST contain the exact same number of objects as the input array.
3.  **ID PRESERVATION**: This is the most critical rule. For each object in your output array, the "id" field MUST be an IDENTICAL, UNCHANGED copy of the "id" from the corresponding input object. Do not alter it in any way.
4.  **TRANSLATION**: You MUST translate the text within the "html_content" field.
5.  **HTML TAG PRESERVATION**: You MUST preserve all HTML tags (e.g., `<h1>`, `<b>`, `<p class='foo'>`) and their attributes perfectly. Only translate the human-readable text content that appears between the HTML tags.

# EXAMPLE
-   **INPUT JSON STRING**:
    ```json
    {json.dumps(example_input, indent=2, ensure_ascii=False)}
    ```
-   **EXPECTED JSON OUTPUT (for a 'zh-CN' target)**:
    ```json
    {json.dumps(example_output, indent=2, ensure_ascii=False)}
    ```

# TASK
Now, please process the following JSON data according to all the rules above. Translate the `html_content` from {source_lang} to {target_lang}.

--- START OF JSON DATA ---
{json_task_string}
--- END OF JSON DATA ---
"""
    return prompt.strip()

def build_html_translation_prompt(html_content: str, source_lang: str, target_lang: str) -> str:
    """
    (This function remains unchanged, useful for the 'split' chapter parts.)
    """
    prompt = f"""
# ROLE & GOAL
You are an expert translator specializing in translating HTML documents from {source_lang} to {target_lang}. Your task is to translate the user-provided HTML content while perfectly preserving its structure.

# CRITICAL RULES
1.  PRESERVE ALL TAGS: You MUST keep all HTML tags (e.g., `<p>`, `<h1>`, `<i>`, `<span class="foo">`) and their attributes (`class`, `id`, `href`, etc.) completely unchanged.
2.  TRANSLATE ONLY TEXT: Only translate the human-readable text content that appears between the HTML tags. Do not translate tag names or attribute values.
3.  MAINTAIN STRUCTURE: The output MUST be a single, valid HTML document with the exact same structure as the input. Do not add, remove, or reorder any HTML elements.
4.  JSON OUTPUT: You MUST respond with a single, valid JSON object containing one key: "translated_html". The value of this key should be the complete translated HTML string.

# EXAMPLE
-   INPUT HTML: `<p class="title">The <b>Quick</b> Brown Fox</p>`
-   EXPECTED JSON OUTPUT: `{{"translated_html": "<p class=\\"title\\">敏捷的<b>棕色</b>狐狸</p>"}}`

# TASK
Now, please translate the following HTML content from {source_lang} to {target_lang}.

--- START OF HTML CONTENT ---
{html_content}
--- END OF HTML CONTENT ---
"""
    return prompt