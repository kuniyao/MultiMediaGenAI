from format_converters.book_schema import SubtitleTrack, SubtitleSegment
import json
import logging
from typing import List, Callable, Dict, Any, Union
import config

# ==============================================================================
# 1. 通用分批逻辑 (Generic Batching Logic) - 修改为JSON适用
# ==============================================================================

def create_batched_json_tasks(
    items: List[SubtitleSegment],
    task_type_name: str,
    base_id: str,
    logger: logging.Logger,
    batch_size_limit_tokens: int = 4000
) -> List[Dict]:
    """
    一个通用的函数，用于将 SubtitleSegment 列表按Token数量智能分批，创建适合JSON的翻译任务。
    每个任务的 text_to_translate 是一个序列化后的JSON字符串。

    Args:
        items: 需要处理的 SubtitleSegment 对象列表。
        task_type_name: 任务类型标识符 (例如 'json_subtitle_batch')。
        base_id: 用于生成任务ID的基础ID (例如 video_id)。
        logger: 日志记录器。
        batch_size_limit_tokens: 每个批次的目标Token上限 (基于序列化后的JSON字符串长度)。

    Returns:
        一个翻译任务的列表。
    """
    tasks = []
    current_batch_segments = []
    current_batch_tokens = 0
    batch_index = 1

    # 估算单个JSON对象开销, e.g., "{\"id\": \"\", \"text\": \"\"}," -> ~20 tokens
    JSON_OVERHEAD_PER_ITEM = 20

    for segment in items:
        # 估算 segment 加入批次后的 token 增加量
        # 长度/3 是一个粗略的估算
        item_tokens = (len(segment.id) + len(segment.source_text)) // 3 + JSON_OVERHEAD_PER_ITEM

        # 如果当前批次非空，且加入新项目会超限，则完成当前批次
        if current_batch_segments and (current_batch_tokens + item_tokens > batch_size_limit_tokens):
            logger.info(f"Finalizing batch {batch_index} with {current_batch_tokens} estimated tokens.")
            
            # 序列化当前批次
            batch_data = [{"id": s.id, "text": s.source_text} for s in current_batch_segments]
            batch_json_string = json.dumps(batch_data, ensure_ascii=False)

            tasks.append({
                "llm_processing_id": f"{task_type_name}_{base_id}_part_{batch_index}",
                "text_to_translate": batch_json_string,
                "source_data": {
                    "type": task_type_name,
                    "id": base_id,
                    "original_segments": current_batch_segments # 存储原始对象用于更新
                }
            })
            
            # 重置批次
            current_batch_segments = []
            current_batch_tokens = 0
            batch_index += 1

        # 将当前项目加入批次
        current_batch_segments.append(segment)
        current_batch_tokens += item_tokens

    # 处理最后一个批次
    if current_batch_segments:
        logger.info(f"Finalizing the last batch {batch_index} with {current_batch_tokens} estimated tokens.")
        batch_data = [{"id": s.id, "text": s.source_text} for s in current_batch_segments]
        batch_json_string = json.dumps(batch_data, ensure_ascii=False)
        
        tasks.append({
            "llm_processing_id": f"{task_type_name}_{base_id}_part_{batch_index}",
            "text_to_translate": batch_json_string,
            "source_data": {
                "type": task_type_name,
                "id": base_id,
                "original_segments": current_batch_segments
            }
        })

    return tasks


# ==============================================================================
# 2. 字幕专用处理器 (Subtitle Specific Processors) - 新的JSON实现
# ==============================================================================

def update_track_from_json_response(track: SubtitleTrack, response_text: str, logger: logging.Logger):
    """
    【关键修改】从可能包含无效字符的 LLM 响应中解析 JSON 并更新轨道。
    这个函数现在更加健壮，能够处理不完整或被污染的 JSON 响应。
    """
    if not response_text:
        logger.warning("Received empty response text. Nothing to update.")
        return

    parsed_data = None
    try:
        # 优先尝试直接解析，这是最理想的情况
        parsed_data = json.loads(response_text)
        logger.debug("Successfully parsed JSON response directly.")
    except json.JSONDecodeError:
        logger.warning(f"Initial JSON parsing failed. Attempting lenient parsing for response: '{response_text[:200]}...'")
        # 尝试“宽容”解析：找到最后一个 '}'，并假设它是一个完整的对象列表的结尾
        try:
            # 清理开头可能存在的非JSON字符
            start_index = response_text.find('[')
            if start_index == -1:
                logger.error("Lenient parsing failed: Could not find opening '[' in response.")
                return

            last_brace_index = response_text.rfind('}')
            if last_brace_index != -1:
                # 截取从第一个 '[' 到最后一个 '}' 的部分，并手动闭合数组
                json_candidate = response_text[start_index : last_brace_index + 1]
                # 有些模型可能会生成一个逗号在最后，先清理掉
                if json_candidate.strip().endswith(','):
                    json_candidate = json_candidate.strip()[:-1]
                
                json_string = f"{json_candidate}]"
                
                parsed_data = json.loads(json_string)
                logger.info(f"Successfully performed lenient parsing. Recovered {len(parsed_data)} items.")
            else:
                logger.error("Lenient parsing failed: Could not find any closing '}' in response.")
        except json.JSONDecodeError as e:
            logger.error(f"Lenient JSON parsing also failed: {e}. Raw text part: '{response_text[start_index : last_brace_index + 100]}...'")
            # 如果宽容解析也失败了，就直接返回，让重试逻辑处理
            return

    if not parsed_data:
        logger.error("After all parsing attempts, no data was successfully parsed.")
        return

    # 使用ID查找表来优化更新
    segment_map = {seg.id: seg for seg in track.segments}
    
    # 确保 parsed_data 是一个列表
    if not isinstance(parsed_data, list):
        logger.warning(f"Parsed data is not a list, but {type(parsed_data)}. Skipping update.")
        return

    for item in parsed_data:
        segment_id = item.get("id")
        translated_text = item.get("text")
        if segment_id in segment_map:
            # 只更新文本，保留其他所有属性
            segment_map[segment_id].translated_text = translated_text
        else:
            logger.warning(f"Segment ID '{segment_id}' from LLM response not found in track.")

def subtitle_track_to_json_tasks(
    segments: list[SubtitleSegment], 
    logger: logging.Logger, 
    base_id: str
) -> list[dict]:
    """
    将 SubtitleTrack 或 SubtitleSegment 列表转换为分批的、适合LLM的JSON任务列表。
    
    Args:
        input_data: SubtitleTrack 对象或 SubtitleSegment 对象的列表。
        logger: 日志记录器。
        base_id: 用于生成任务ID的基础ID (例如 video_id 或 filename)。

    Returns:
        一个翻译任务的列表，每个任务包含一段JSON字符串。
    """
    effective_input_limit = config.OUTPUT_TOKEN_LIMIT / config.LANGUAGE_EXPANSION_FACTOR
    target_token_per_chunk = int(effective_input_limit * config.SAFETY_MARGIN)
    logger.info(f"Target tokens per subtitle JSON batch calculated: {target_token_per_chunk}")

    items_to_batch: List[SubtitleSegment]
    effective_base_id: str

    if isinstance(segments, SubtitleTrack):
        items_to_batch = segments.segments
        effective_base_id = segments.video_id
    elif isinstance(segments, List):
        items_to_batch = segments
        effective_base_id = base_id
    else:
        raise TypeError("input_data must be a SubtitleTrack or a List[SubtitleSegment]")

    return create_batched_json_tasks(
        items=items_to_batch,
        task_type_name="json_subtitle_batch",
        base_id=effective_base_id,
        logger=logger,
        batch_size_limit_tokens=target_token_per_chunk
    )