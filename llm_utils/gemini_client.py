import os
import logging
import asyncio
import json
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Tuple, Dict, Optional

from .base_client import BaseLLMClient
import config

# 加载 .env 文件
project_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=project_root / '.env')

class GeminiClient(BaseLLMClient):
    """
    针对 Google Gemini 模型实现的 LLM 客户端。
    """

    def __init__(self, logger: Optional[logging.Logger] = None, generation_config_overrides: Optional[Dict] = None):
        super().__init__(logger)
        self.generation_config_overrides = generation_config_overrides

    async def initialize(self, **kwargs):
        """异步初始化 Gemini 模型客户端。"""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            self.logger.error("未在环境变量中找到 GEMINI_API_KEY。")
            raise ValueError("未在环境变量中找到 GEMINI_API_KEY。")
        
        try:
            genai.configure(api_key=api_key) # type: ignore

            config_params = {"temperature": 0.0}
            if self.generation_config_overrides:
                config_params.update(self.generation_config_overrides)
            
            # 类型检查工具可能不认识 types，但运行时是正确的
            generation_config = genai.types.GenerationConfig(**config_params) # type: ignore
            
            # 类型检查工具可能不认识 GenerativeModel，但运行时是正确的
            self.model = genai.GenerativeModel( # type: ignore
                config.LLM_MODEL_GEMINI,
                generation_config=generation_config
            )
            self.logger.debug(f"成功初始化 Gemini 模型客户端，配置为: {config_params}")
        except Exception as e:
            self.logger.error(f"初始化 Gemini 模型客户端失败: {e}", exc_info=True)
            raise

    async def call_api_async(self, messages: List[Dict[str, str]], task_id: str) -> Tuple[Optional[str], Optional[str]]:
        """
        带重试逻辑地异步调用 Gemini API。
        """
        if not self.model:
            self.logger.error(f"Gemini 模型未初始化。无法为任务 {task_id} 调用 API。")
            raise RuntimeError("模型未初始化。")

        raw_text = None
        log_entry_json_string = None
        
        MAX_RETRIES = 5
        INITIAL_BACKOFF_SECONDS = 2
        
        for attempt in range(MAX_RETRIES):
            try:
                self.logger.debug(f"为任务 {task_id} 请求翻译 (尝试 {attempt + 1}/{MAX_RETRIES})...")
                # 使用异步调用，并设置超时
                response = await self.model.generate_content_async(messages, request_options={'timeout': 300})
                raw_text = response.text
                # 【诊断日志】 在进行任何处理之前，记录最原始的输出
                # self.logger.error(f"DIAGNOSTIC LOG FOR {task_id} | RAW LLM OUTPUT: {raw_text}")
                self.logger.debug(f"在第 {attempt + 1} 次尝试时收到任务 {task_id} 的响应。")
                break  # 成功，退出重试循环
            except (google_exceptions.GoogleAPICallError, asyncio.TimeoutError) as e:
                self.logger.warning(f"任务 {task_id} 在第 {attempt + 1} 次尝试时发生 API 错误: {e}")
                if attempt < MAX_RETRIES - 1:
                    backoff_time = INITIAL_BACKOFF_SECONDS * (2 ** attempt)
                    self.logger.info(f"将在 {backoff_time} 秒后重试任务 {task_id}...")
                    await asyncio.sleep(backoff_time)
                else:
                    self.logger.error(f"任务 {task_id} 的所有 {MAX_RETRIES} 次尝试均失败: {e}", exc_info=True)
                    raw_text = None  # 最终失败时确保 raw_text 为 None
                    break
            except Exception as e:
                self.logger.error(f"任务 {task_id} 发生意外错误: {e}", exc_info=True)
                raw_text = None  # 发生意外错误时确保 raw_text 为 None
                break
        
        # 无论成功或失败，都准备日志条目
        log_entry = {"task_id": task_id, "response_text": raw_text}
        log_entry_json_string = json.dumps(log_entry, ensure_ascii=False)
        
        return raw_text, log_entry_json_string 