from format_converters.book_schema import SubtitleTrack, SubtitleSegment
import html
from bs4 import BeautifulSoup
import logging
from typing import List, Callable, Dict, Any
import config

# ==============================================================================
# 1. 通用分批逻辑 (Generic Batching Logic)
# ==============================================================================

def create_batched_tasks(
    items: List[Any],
    serialize_func: Callable[[Any], str],
    task_type_name: str,
    base_id: str,
    logger: logging.Logger,
    batch_size_limit_tokens: int = 4000  # A reasonable default token limit per batch
) -> List[Dict]:
    """
    一个通用的函数，用于将项目列表按Token数量智能分批，创建翻译任务。

    Args:
        items: 需要处理的项目列表 (例如 SubtitleSegment 对象)。
        serialize_func: 一个函数，接收单个项目并返回其HTML字符串表示。
        task_type_name: 任务类型标识符 (例如 'html_subtitle_batch')。
        base_id: 用于生成任务ID的基础ID (例如 video_id)。
        logger: 日志记录器。
        batch_size_limit_tokens: 每个批次的目标Token上限。

    Returns:
        一个翻译任务的列表。
    """
    tasks = []
    current_batch_html_parts = []
    current_batch_tokens = 0
    batch_index = 1

    for item in items:
        item_html = serialize_func(item)
        # A simple approximation: 3 chars ~ 1 token. This can be refined.
        item_tokens = len(item_html) // 3

        # 如果当前项目加入后会超出限制，并且当前批次不为空，则最终化当前批次
        if current_batch_html_parts and (current_batch_tokens + item_tokens > batch_size_limit_tokens):
            logger.info(f"Finalizing batch {batch_index} with {current_batch_tokens} tokens.")
            batch_html_content = "\\n".join(current_batch_html_parts)
            tasks.append({
                "llm_processing_id": f"{task_type_name}_{base_id}_part_{batch_index}",
                "text_to_translate": batch_html_content,
                "source_data": {"type": task_type_name, "id": base_id}
            })
            # 重置批次
            current_batch_html_parts = []
            current_batch_tokens = 0
            batch_index += 1

        # 将当前项目添加到批次中
        current_batch_html_parts.append(item_html)
        current_batch_tokens += item_tokens

    # 处理最后一个剩余的批次
    if current_batch_html_parts:
        logger.info(f"Finalizing the last batch {batch_index} with {current_batch_tokens} tokens.")
        batch_html_content = "\\n".join(current_batch_html_parts)
        tasks.append({
            "llm_processing_id": f"{task_type_name}_{base_id}_part_{batch_index}",
            "text_to_translate": batch_html_content,
            "source_data": {"type": task_type_name, "id": base_id}
        })

    return tasks

# ==============================================================================
# 2. 字幕专用处理器 (Subtitle Specific Processors)
# ==============================================================================

def _serialize_subtitle_segment(segment: SubtitleSegment) -> str:
    """序列化单个SubtitleSegment为HTML字符串。"""
    escaped_text = html.escape(segment.source_text)
    return (
        f'<div class="segment" data-id="{segment.id}" '
        f'data-start="{segment.start}" data-end="{segment.end}">'
        f'<p>{escaped_text}</p>'
        f'</div>'
    )

def subtitle_track_to_html_tasks(track: SubtitleTrack, logger: logging.Logger) -> list[dict]:
    """
    将 SubtitleTrack 转换为分批的、适合LLM的HTML任务列表。
    现在调用通用的分批函数。
    """
    # 从配置计算批次大小
    # (与 book_processor.py 中的逻辑保持一致)
    effective_input_limit = config.OUTPUT_TOKEN_LIMIT / config.LANGUAGE_EXPANSION_FACTOR
    target_token_per_chunk = int(effective_input_limit * config.SAFETY_MARGIN)
    logger.info(f"Target tokens per subtitle batch calculated: {target_token_per_chunk}")

    return create_batched_tasks(
        items=track.segments,
        serialize_func=_serialize_subtitle_segment,
        task_type_name="html_subtitle_batch",
        base_id=track.video_id,
        logger=logger,
        batch_size_limit_tokens=target_token_per_chunk
    )

def update_track_from_html_response(track: SubtitleTrack, translated_html: str, logger: logging.Logger) -> int:
    """
    使用LLM返回的已翻译HTML内容来更新SubtitleTrack对象。
    
    Args:
        track: 原始的SubtitleTrack对象，其segments将被就地更新。
        translated_html: LLM返回的包含翻译文本的HTML字符串。
        logger: 用于记录日志的Logger对象。

    Returns:
        一个整数，代表此批次中成功更新的片段数量。
    """
    soup = BeautifulSoup(translated_html, 'html.parser')
    segments = soup.find_all('div', class_='segment')
    
    track_segments_map = {seg.id: seg for seg in track.segments}
    
    updated_count = 0
    
    for segment_div in segments:
        seg_id = segment_div.get('data-id')
        if not seg_id:
            logger.warning(f"发现一个没有 data-id 的 segment div，跳过: {segment_div}")
            continue
            
        p_tag = segment_div.find('p')
        if not p_tag:
            logger.warning(f"在 data-id={seg_id} 的 segment 中没有找到 <p> 标签，跳过。")
            continue
            
        translated_text = p_tag.get_text()
        
        if seg_id in track_segments_map:
            track_segments_map[seg_id].translated_text = translated_text
            updated_count += 1
        else:
            logger.warning(f"在原始 SubtitleTrack 中找不到ID为 {seg_id} 的片段，无法更新翻译。")
            
    logger.debug(f"从当前HTML批次中成功解析并更新了 {updated_count} 个字幕片段。")
        
    return updated_count 