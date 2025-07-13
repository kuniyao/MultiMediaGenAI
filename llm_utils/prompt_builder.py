# llm_utils/prompt_builder.py (refactored)

import json
from typing import List, Dict, Optional, Any
from pathlib import Path

# 全局的、预加载的提示词模板
PROMPT_TEMPLATES = {}

# 在文件顶部定义，以便在多个函数中使用
PROMPT_CONFIG = {
    'json_batch': {'system': 'json_batch_system_prompt', 'user': 'json_batch_user_prompt', 'var_name': 'json_task_string'},
    'text_file': {'system': 'text_file_system_prompt', 'user': 'text_file_user_prompt', 'var_name': 'text_content'},
    'json_subtitle_batch': {'system': 'json_subtitle_system_prompt', 'user': 'json_subtitle_user_prompt', 'var_name': "json_task_string"}
}

def _load_prompts():
    """
    私有函数，用于加载所有提示词模板到全局变量中。
    """
    global PROMPT_TEMPLATES
    if PROMPT_TEMPLATES:
        return

    try:
        # 定位到项目根目录下的 prompts.json 文件
        # __file__ 指向当前文件 (prompt_builder.py)
        # .parent 指向 llm_utils/
        # .parent 指向项目根目录
        prompt_file_path = Path(__file__).resolve().parent.parent / "prompts.json"
        with open(prompt_file_path, 'r', encoding='utf-8') as f:
            PROMPT_TEMPLATES = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        # 在实际应用中，这里应该使用日志记录错误
        print(f"Error loading prompts: {e}")
        PROMPT_TEMPLATES = {}

class PromptBuilder:
    """
    一个用于构建和管理发送给LLM的提示的类。
    """
    def __init__(self, source_lang: str, target_lang: str, glossary: Optional[Dict[str, str]] = None):
        _load_prompts()
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.glossary = glossary
        self.glossary_section = self._create_glossary_section()

    def _create_glossary_section(self) -> str:
        """
        如果提供了术语表，则创建格式化的术语表部分。
        """
        if not self.glossary:
            return ""
        
        template = PROMPT_TEMPLATES.get("glossary_injection_template", {}).get("content", "")
        if not template:
            return ""
        
        glossary_items = "\n".join([f'* "{term}": "{translation}"' for term, translation in self.glossary.items()])
        return template.format(glossary_items=glossary_items)

    def build_messages(self, task_type: str, task_string: str) -> List[Dict[str, Any]]:
        """
        根据任务类型构建最终的消息列表。
        """
        prompt_details = PROMPT_CONFIG.get(task_type)
        if not prompt_details:
            raise ValueError(f"No prompt configuration found for task type: {task_type}")

        system_prompt_template = PROMPT_TEMPLATES.get(prompt_details['system'], {})
        user_prompt_template = PROMPT_TEMPLATES.get(prompt_details['user'], {})
        
        variables = {
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "glossary_section": self.glossary_section,
            prompt_details['var_name']: task_string
        }
        
        system_content = system_prompt_template.get('content', '').format(**variables)
        user_content = user_prompt_template.get('content', '').format(**variables)
        
        # 为了兼容不同的模型，将 system prompt 的内容合并到 user prompt 的开头
        full_user_content = f"{system_content}\n\n{user_content}".strip()
        
        messages = [
            {"role": "user", "parts": [full_user_content]}
        ]
        
        return messages

# 保持此独立函数以实现向后兼容或用于其他简单场景
def build_prompt_from_template(
    system_prompt_template: Optional[Dict[str, Any]], 
    user_prompt_template: Optional[Dict[str, Any]],
    variables: Dict[str, Any],
    glossary: Optional[Dict[str, str]] = None,
    glossary_template_content: Optional[str] = None # 接受模板内容而不是整个模板
) -> List[Dict[str, Any]]:
    """
    A generic prompt generator that creates a prompt from templates and variables,
    formatted correctly for the Google Gemini API.
    """
    
    # Handle glossary
    glossary_section = ""
    if glossary and glossary_template_content:
        # 直接在这里处理术语表创建
        glossary_items = "\n".join([f'* "{term}": "{translation}"' for term, translation in glossary.items()])
        glossary_section = glossary_template_content.format(glossary_items=glossary_items)

    # Add the glossary section to the variables for formatting
    variables['glossary_section'] = glossary_section
    
    messages = []
    
    # Format system and user prompts
    system_content = ""
    if system_prompt_template and 'content' in system_prompt_template:
        system_content = system_prompt_template['content'].format(**variables)
        
    user_content = ""
    if user_prompt_template and 'content' in user_prompt_template:
        user_content = user_prompt_template['content'].format(**variables)

    # Merge system and user prompts into a single user message
    full_user_content = f"{system_content}\n\n{user_content}".strip()
    
    if full_user_content:
        # Build a message structure compatible with the Google Gemini API
        messages.append({
            "role": "user",
            "parts": [full_user_content]
        })
        
    return messages

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
        glossary_items = "\n".join([f'* \"{term}\": \"{translation}\"' for term, translation in glossary.items()])
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
    # 為了示例，我們創建一個小的���JSON，以展示結構
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

def build_text_file_translation_prompt(text_content: str, source_lang: str, target_lang: str) -> str:
    """
    一個經過強化的、用於翻譯帶有HTML標籤的文本塊的Prompt。
    """
    prompt = f"""
# ROLE & GOAL
You are an expert technical translator. Your SOLE task is to translate the text content within an HTML snippet from {source_lang} to {target_lang}, while preserving the HTML structure perfectly.

# CRITICAL RULES
1.  **HTML TAG PRESERVATION**: This is your most important instruction. You MUST preserve all HTML tags (e.g., `<h1>`, `<p>`, `<p class="indent">`, `<b>`, `<i>`, `<a href="...">`) and their attributes EXACTLY as they appear in the source text. DO NOT alter, add, or remove any tags or attributes.
2.  **TRANSLATE TEXT ONLY**: Only translate the human-readable text content that is between the HTML tags.
3.  **NO PLAIN TEXT**: Your output MUST be a valid HTML snippet. It MUST NOT be plain text.
4.  **NO EXTRA COMMENTARY**: Do not add any explanations, greetings, or apologies in your response. Your output should only be the translated HTML snippet.

# EXAMPLE
-   **INPUT TEXT**:
    ```html
    <h1 class="title">Chapter 1</h1><p class="indent">This is the <b>first</b> paragraph.</p>
    ```
-   **EXPECTED OUTPUT (for target_lang 'zh-CN')**:
    ```html
    <h1 class="title">第一章</h1><p class="indent">这是<b>第一</b>段。</p>
    ```

# TASK
Now, translate the following HTML snippet from {source_lang} to {target_lang}. Follow all the rules above.

--- START OF HTML SNIPPET ---
{text_content}
--- END OF HTML SNIPPET ---
"""
    return prompt.strip()
