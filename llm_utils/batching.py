import json
import config
from llm_utils.prompt_builder import construct_prompt_for_batch
import logging

# Configure a basic logger if no configuration is provided
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# A conservative estimate for characters per token. 2.5 is a safe bet for JSON with English.
CHARS_PER_TOKEN_ESTIMATE = 2.5 

def get_batches_for_translation(task_list: list, text_key: str = "text_with_markup") -> list:
    """
    一个简化的包装函数，用于将翻译任务列表分割成适合LLM处理的批次。

    Args:
        task_list (list): 待翻译的任务字典列表。
        text_key (str): 任务字典中包含待翻译文本的键。

    Returns:
        list: 一个批次列表，其中每个批次是任务字典的列表。
    """
    TARGET_CHAR_COUNT_PER_BATCH = config.TARGET_PROMPT_TOKENS_PER_BATCH * CHARS_PER_TOKEN_ESTIMATE

    all_batches = []
    current_batch = []
    current_char_count = 0

    if not task_list:
        return []

    for task in task_list:
        # 估算任务的字符成本 (以JSON字符串形式)
        # 我们只关心文本字段的长度，因为其他字段（如ID）的开销相对较小且固定。
        text_content = task.get(text_key, "")
        task_char_count = len(text_content) # 主要成本

        # 检查如果添加这个任务是否会超出限制
        if current_batch and (current_char_count + task_char_count > TARGET_CHAR_COUNT_PER_BATCH):
            # 完成当前批次
            all_batches.append(list(current_batch))
            # 开始新批次
            current_batch = [task]
            current_char_count = task_char_count
        else:
            # 添加到当前批次
            current_batch.append(task)
            current_char_count += task_char_count
            
    # 添加最后一个批次
    if current_batch:
        all_batches.append(list(current_batch))

    logger.info(f"Prepared {len(all_batches)} batches for translation.")
    return all_batches

def create_batches_by_char_limit(
    all_segments, 
    source_lang_code, 
    target_lang, 
    output_text_field_key, 
    use_simplified_ids,
    logger
):
    """
    Creates batches of segments based on an estimated character count to stay
    within a target token limit for an LLM prompt.

    Args:
        all_segments (list): The full list of segment objects to batch.
        source_lang_code (str): The source language.
        target_lang (str): The target language.
        output_text_field_key (str): The JSON key for the translated text.
        use_simplified_ids (bool): Whether to use simplified IDs in the prompt.
        logger: A logger instance.

    Returns:
        list: A list of lists, where each inner list is a batch of segments.
    """
    TARGET_CHAR_COUNT_PER_BATCH = config.TARGET_PROMPT_TOKENS_PER_BATCH * CHARS_PER_TOKEN_ESTIMATE

    # 1. Calculate the character count of the prompt template *without* any segments.
    base_prompt_template = construct_prompt_for_batch(
        [], # Empty list of segments
        source_lang_code, 
        target_lang, 
        output_text_field_key,
        use_simplified_ids=use_simplified_ids
    )
    base_char_count = len(base_prompt_template)

    all_batches = []
    current_batch_segments = []
    current_batch_char_count = base_char_count

    # 2. Iterate through segments, adding their character cost to the current batch count.
    for seg_obj in all_segments:
        # Estimate token cost of adding this segment by its character length in JSON form.
        segment_json_str = json.dumps(seg_obj, ensure_ascii=False) + " , " 
        segment_char_count = len(segment_json_str)

        # Check if adding this segment would exceed limits
        if current_batch_segments and \
           ((current_batch_char_count + segment_char_count > TARGET_CHAR_COUNT_PER_BATCH) or \
            (len(current_batch_segments) + 1 > config.MAX_SEGMENTS_PER_GEMINI_JSON_BATCH)):
            
            # Finalize the current batch
            all_batches.append(list(current_batch_segments))
            
            # Start a new batch with the current segment
            current_batch_segments = [seg_obj]
            current_batch_char_count = base_char_count + segment_char_count
        else:
            # Add the segment to the current batch
            current_batch_segments.append(seg_obj)
            current_batch_char_count += segment_char_count

    # Add the last remaining batch to the list
    if current_batch_segments:
        all_batches.append(list(current_batch_segments))
    
    if all_batches:
        logger.info(f"Prepared {len(all_batches)} batches for translation.")
    else:
        logger.info("No batches to translate.")

    return all_batches 