# Placeholder for the YouTube translation workflow 

import argparse
import os
import logging
import logging.handlers
from datetime import datetime
from dotenv import load_dotenv
import sys # Add sys
import json

# Determine project root and add to sys.path
# In this new structure, __file__ will refer to this workflow script's path.
script_path = os.path.abspath(__file__)
script_dir = os.path.dirname(script_path) # .../workflows
project_root_dir = os.path.dirname(script_dir) # This should be the project root
if project_root_dir not in sys.path:
    sys.path.insert(0, project_root_dir)

# Now, imports that rely on the project root being in sys.path should work
import config # Assuming config.py is in the project root or PYTHONPATH

# Import functions from our new modules
from common_utils.file_helpers import sanitize_filename, save_to_file
from common_utils.log_config import setup_task_logger
from format_converters import (
    reconstruct_translated_markdown,
    generate_post_processed_srt
)
from format_converters.book_schema import SubtitleTrack, SubtitleSegment
from youtube_utils.data_fetcher import get_video_id, get_youtube_video_title, fetch_and_prepare_transcript
from llm_utils.translator import execute_translation_async
from llm_utils.subtitle_processor import subtitle_track_to_html_tasks, update_track_from_html_response

# Placeholder for the YouTube translation workflow

# --- Global Logger for general script messages (console output) ---
# This logger is now removed. All logging will be handled by the task_logger.
# --- End of Global Logger Setup ---

def _parse_args():
    """Parses command-line arguments for the YouTube translation workflow."""
    # Determine the script's directory and the desired default output directory
    script_path = os.path.abspath(__file__)
    script_dir = os.path.dirname(script_path) # .../workflows
    project_root_dir = os.path.dirname(script_dir) # This should be the project root
    
    parent_of_project_root = os.path.dirname(project_root_dir)
    default_parallel_output_folder_name = "GlobalWorkflowOutputs"
    default_base_output_dir_path = os.path.join(parent_of_project_root, default_parallel_output_folder_name)

    parser = argparse.ArgumentParser(description="Translate YouTube video subtitles.")
    parser.add_argument("video_url_or_id", help="The URL or ID of the YouTube video.")
    parser.add_argument("--output_basename", help="Basename for output files (e.g., 'my_video'). Overrides fetched video title for naming.", default=None)
    parser.add_argument("--target_lang", help="Target language for translation (e.g., 'zh-CN', 'zh-Hans').", default=config.DEFAULT_TARGET_TRANSLATION_LANGUAGE)
    parser.add_argument("--output_dir", 
                        help=f"Base directory for all output. Default: A folder named '{default_parallel_output_folder_name}' located parallel to the project directory (e.g., in '{parent_of_project_root}'). Video-specific subfolders will be created inside this directory.", 
                        default=default_base_output_dir_path)
    parser.add_argument("--log_level", help="Set the logging level for the video-specific log file (DEBUG, INFO, WARNING, ERROR, CRITICAL)", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

    return parser.parse_args()

def _setup_environment_and_logging(args):
    """Sets up the environment, including directories, logging, and initial variables."""
    # --- Video and Path Setup ---
    video_id = get_video_id(args.video_url_or_id)
    
    # --- Logger Setup (early, so we can use it for title fetching) ---
    # We create a preliminary logger here to capture early setup messages.
    # It will be replaced by the more specific task_logger later.
    temp_logger = logging.getLogger('TempSetup')
    
    video_title = get_youtube_video_title(args.video_url_or_id, logger=temp_logger) # Use a temp logger for the first fetch
    
    sanitized_title = sanitize_filename(video_title)
    specific_output_dir_name = sanitized_title if sanitized_title and sanitized_title != video_id else video_id
    
    video_output_path = os.path.join(args.output_dir, specific_output_dir_name)
    os.makedirs(video_output_path, exist_ok=True)

    # --- Full Logger Setup ---
    log_file_name_base = sanitized_title if sanitized_title and sanitized_title != video_id else video_id
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file_name = f"{sanitize_filename(log_file_name_base)}_{timestamp_str}.log"
    log_file_full_path = os.path.join(video_output_path, log_file_name)

    numeric_log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    task_logger_name = f"VideoTaskWorkflow.{sanitize_filename(log_file_name_base)}.{timestamp_str}"
    task_logger = setup_task_logger(task_logger_name, log_file_full_path, level=numeric_log_level)
    
    task_logger.info(f"Video-specific output directory created: {video_output_path}")
    task_logger.info(f"Task-specific logger initialized. Logging to file: {log_file_full_path}")
    
    # --- Filename Basename ---
    if video_title == video_id: 
        task_logger.warning(f"Could not fetch a distinct video title; using video ID '{video_id}' for directory and filenames.")
    
    file_basename_prefix = sanitize_filename(args.output_basename) if args.output_basename else specific_output_dir_name

    task_logger.info(f"Processing Video URL: {args.video_url_or_id}")
    task_logger.info(f"Video ID for transcript: {video_id}")
    task_logger.info(f"Fetched video title (used for naming): '{video_title}'")
    task_logger.info(f"Target language for translation: {args.target_lang}")
    task_logger.info(f"Output files will be prefixed with: '{file_basename_prefix}'")
    
    return {
        "task_logger": task_logger,
        "video_output_path": video_output_path,
        "file_basename_prefix": file_basename_prefix,
        "video_id": video_id,
        "video_title": video_title
    }

def _generate_output_files(translated_track: SubtitleTrack, target_lang, video_output_path, file_basename_prefix, logger):
    """Generates and saves the final output files (SRT, Markdown) from a SubtitleTrack object."""
    
    # Generate translated Markdown
    translated_md_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{target_lang}.md")
    translated_md_content = reconstruct_translated_markdown(
        subtitle_track=translated_track,
        target_lang=target_lang,
        logger=logger
    )
    save_to_file(translated_md_content, translated_md_filename, logger=logger)

    # Generate translated SRT
    translated_srt_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{target_lang}.srt")
    translated_srt_content = generate_post_processed_srt(
        subtitle_track=translated_track,
        logger=logger
    )
    save_to_file(translated_srt_content, translated_srt_filename, logger=logger)

def _log_summary(video_output_path, file_basename_prefix, lang_code, target_lang, logger):
    """Logs a summary of all generated output files."""
    translated_md_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{target_lang}.md")
    translated_srt_filename = os.path.join(video_output_path, f"{file_basename_prefix}_translated_{target_lang}.srt")
    raw_llm_log_expected_filename = os.path.join(video_output_path, f"llm_raw_responses_{target_lang.lower().replace('-', '_')}.jsonl")
    
    # We need to find the actual log file path from the logger's handlers
    log_file_full_path = None
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            log_file_full_path = handler.baseFilename
            break

    logger.info("\n--- Summary of Output Files ---")
    if os.path.exists(translated_md_filename):
        logger.info(f"Translated transcript (MD): {translated_md_filename}")
    if os.path.exists(translated_srt_filename):
        logger.info(f"Translated transcript (SRT): {translated_srt_filename}")
    if os.path.exists(raw_llm_log_expected_filename):
        logger.info(f"Raw LLM responses log: {raw_llm_log_expected_filename}")
    if log_file_full_path and os.path.exists(log_file_full_path):
        logger.info(f"Video processing log: {log_file_full_path}")

async def main_async():
    """Main async function to orchestrate the YouTube video translation workflow."""
    args = _parse_args()
    
    setup_results = _setup_environment_and_logging(args)
    task_logger = setup_results["task_logger"]
    project_root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    prompts = {}
    try:
        prompts_path = os.path.join(project_root_dir, 'prompts.json')
        with open(prompts_path, 'r', encoding='utf-8') as f:
            prompts = json.load(f)
        task_logger.info(f"Successfully loaded prompts from {prompts_path}")
    except Exception as e:
        task_logger.error(f"FATAL: Failed to load or parse prompts.json: {e}")
        return

    try:
        task_logger.info(f"--- YouTube Translator workflow started for input: {args.video_url_or_id} ---")
        
        # 1. Fetch and process transcript
        merged_transcript_data, lang_code, source_type = fetch_and_prepare_transcript(
            video_id=setup_results['video_id'],
            logger=task_logger
        )
        if not merged_transcript_data:
            task_logger.error("Workflow terminated due to failure in transcript processing.")
            return

        # 2. 将获取的数据实例化为 SubtitleTrack 对象
        task_logger.info("创建 SubtitleTrack 数据模型...")
        subtitle_track = SubtitleTrack(
            video_id=setup_results['video_id'],
            source_lang=lang_code,
            source_type=source_type
        )
        for i, seg_data in enumerate(merged_transcript_data):
            subtitle_track.segments.append(
                SubtitleSegment(
                    id=f"seg_{i:04d}", # 使用简单递增ID
                    start=seg_data['start'],
                    end=seg_data.get('end', seg_data['start'] + seg_data.get('duration', 0)),
                    source_text=seg_data['text']
                )
            )
        
        # 1. 创建批处理任务
        tasks_to_translate = subtitle_track_to_html_tasks(subtitle_track, logger=task_logger)
        
        # 2. 调用通用的翻译模块
        task_logger.info("调用核心翻译模块...")
        translation_results = await execute_translation_async(
            tasks_to_translate=tasks_to_translate,
            source_lang_code=lang_code,
            target_lang=args.target_lang,
            video_specific_output_path=setup_results['video_output_path'],
            logger=task_logger,
            prompts=prompts
        )

        if not translation_results:
            task_logger.error("Workflow terminated due to translation failure.")
            return

        # 3. 在工作流内部处理返回的结果，更新字幕轨道
        task_logger.info("从LLM响应中解析所有HTML批次并更新字幕轨道...")
        total_updated_count = 0
        for result in translation_results:
            translated_html = result.get("translated_text")
            task_id = result.get("llm_processing_id")
            if not translated_html:
                task_logger.warning(f"翻译结果批次 {task_id} 中缺少 'translated_text'，跳过此批次。")
                continue
            updated_in_batch = update_track_from_html_response(
                track=subtitle_track,
                translated_html=translated_html,
                logger=task_logger
            )
            total_updated_count += updated_in_batch
        
        # 4. 在这里进行最终的数量检查
        final_segment_count = len(subtitle_track.segments)
        if total_updated_count != final_segment_count:
             task_logger.warning(f"最终更新的片段总数 ({total_updated_count}) 与原始片段总数 ({final_segment_count}) 不匹配。")
        else:
             task_logger.info(f"成功更新了全部 {total_updated_count}/{final_segment_count} 个片段。")

        # 5. 生成输出文件 (现在传递的是已经就地更新的 subtitle_track)
        _generate_output_files(
            translated_track=subtitle_track,
            target_lang=args.target_lang,
            video_output_path=setup_results['video_output_path'],
            file_basename_prefix=setup_results['file_basename_prefix'],
            logger=task_logger
        )

        # 6. Log summary of generated files
        _log_summary(
            video_output_path=setup_results['video_output_path'],
            file_basename_prefix=setup_results['file_basename_prefix'],
            lang_code=lang_code,
            target_lang=args.target_lang,
            logger=task_logger
        )

        task_logger.info("All tasks completed for this video!")
        task_logger.info(f"--- YouTube Translator workflow finished for input: {args.video_url_or_id} ---")

    except Exception as e:
        task_logger.critical(f"An unexpected error terminated the workflow: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main_async()) 