from format_converters.book_schema import SubtitleTrack, SubtitleSegment
import html
from bs4 import BeautifulSoup
import logging
from typing import List, Callable, Dict, Any
import config

# ==============================================================================
# 1. 通用分批逻辑 (Generic Batching Logic) - 已修改
# ==============================================================================

def create_batched_tasks(
    items: List[Any],
    serialize_func: Callable[[Any], str],
    task_type_name: str,
    base_id: str,
    logger: logging.Logger,
    batch_size_limit_tokens: int = 4000
) -> List[Dict]:
    """
    一个通用的函数，用于将项目列表按Token数量智能分批，创建翻译任务。
    此版本将原始项目对象存储在任务中，以实现更可靠的更新。

    Args:
        items: 需要处理的项目列表 (例如 SubtitleSegment 对象)。
        serialize_func: 一个函数，接收单个项目并返回其HTML字符串表示。
        task_type_name: 任务类型标识符 (例如 'html_subtitle_batch')。
        base_id: 用于生成任务ID的基础ID (例如 video_id)。
        logger: 日志记录器。
        batch_size_limit_tokens: 每个批次的目标Token上限。

    Returns:
        一个翻译任务的列表，每个任务都包含原始项目。
    """
    tasks = []
    current_batch_items = []
    current_batch_html_parts = []
    current_batch_tokens = 0
    batch_index = 1

    for item in items:
        item_html = serialize_func(item)
        item_tokens = len(item_html) // 3

        if current_batch_items and (current_batch_tokens + item_tokens > batch_size_limit_tokens):
            logger.info(f"Finalizing batch {batch_index} with {current_batch_tokens} tokens.")
            batch_html_content = "\n".join(current_batch_html_parts)
            tasks.append({
                "llm_processing_id": f"{task_type_name}_{base_id}_part_{batch_index}",
                "text_to_translate": batch_html_content,
                "source_data": {
                    "type": task_type_name,
                    "id": base_id,
                    "original_segments": current_batch_items  # 存储原始对象
                }
            })
            current_batch_items = []
            current_batch_html_parts = []
            current_batch_tokens = 0
            batch_index += 1

        current_batch_items.append(item)
        current_batch_html_parts.append(item_html)
        current_batch_tokens += item_tokens

    if current_batch_items:
        logger.info(f"Finalizing the last batch {batch_index} with {current_batch_tokens} tokens.")
        batch_html_content = "\n".join(current_batch_html_parts)
        tasks.append({
            "llm_processing_id": f"{task_type_name}_{base_id}_part_{batch_index}",
            "text_to_translate": batch_html_content,
            "source_data": {
                "type": task_type_name,
                "id": base_id,
                "original_segments": current_batch_items  # 存储最后一个批次的原始对象
            }
        })

    return tasks

# ==============================================================================
# 2. 字幕专用处理器 (Subtitle Specific Processors) - 已修改
# ==============================================================================

def _serialize_subtitle_segment(segment: SubtitleSegment) -> str:
    """序列化单个SubtitleSegment为HTML字符串，不再包含data-id。"""
    escaped_text = html.escape(segment.source_text)
    # 我们不再依赖ID，但保留其他元数据可能对调试有用
    return (
        f'<div class="segment" data-start="{segment.start}" data-end="{segment.end}">'
        f'<p>{escaped_text}</p>'
        f'</div>'
    )

def subtitle_track_to_html_tasks(track: SubtitleTrack, logger: logging.Logger) -> list[dict]:
    """
    将 SubtitleTrack 转换为分批的、适合LLM的HTML任务列表。
    """
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

def update_track_from_html_response(
    original_segments_in_batch: List[SubtitleSegment],
    translated_html: str,
    logger: logging.Logger
) -> int:
    """
    使用LLM返回的已翻译HTML内容，按顺序更新原始的SubtitleSegment对象列表。
    采用三步走策略来提取翻译文本，以提高健壮性。
    """
    soup = BeautifulSoup(translated_html, 'html.parser')
    translated_divs = soup.find_all('div', class_='segment')

    if len(translated_divs) != len(original_segments_in_batch):
        logger.warning(
            f"Mismatch in segment count for batch. "
            f"Original: {len(original_segments_in_batch)}, "
            f"Translated: {len(translated_divs)}. "
            f"Will attempt to update based on sequence, but results may be inaccurate."
        )

    updated_count = 0
    for original_segment, translated_div in zip(original_segments_in_batch, translated_divs):
        translated_text = ""
        
        # 1. 首选路径：尝试获取 <p> 标签的文本
        p_tag = translated_div.find('p')
        if p_tag and p_tag.get_text(strip=True):
            translated_text = p_tag.get_text(strip=True)
        else:
            # 2. 备用路径：如果<p>不存在或为空，尝试获取整个<div>的直接文本
            div_text = translated_div.get_text(strip=True)
            if div_text:
                translated_text = div_text
                logger.info(
                    f"Found translation in <div> for original text: '{original_segment.source_text}'. "
                    f"Recovered text: '{translated_text}'"
                )
            else:
                # 3. 最终路径：如果两者都失败，则记录警告
                logger.warning(
                    f"No translation found in <p> or <div> for original text: '{original_segment.source_text}'. "
                    f"Updating with empty string."
                )
        
        original_segment.translated_text = translated_text
        updated_count += 1
        
    logger.debug(f"Successfully updated {updated_count} segments in the current batch by sequence.")
    return updated_count