# config.py
"""
Configuration settings for the YouTube Translator script.
"""

# LLM Configuration
LLM_PROVIDER = "gemini"  # Options: "gemini", "openai", "azure_openai", or "custom"
# Specify the model for the selected provider
LLM_MODEL_GEMINI = "gemini-2.5-flash-lite-preview-06-17" # Example for Gemini
LLM_MODEL_OPENAI = "gpt-3.5-turbo" # Example for OpenAI
LLM_MODEL_AZURE = "your-azure-deployment-name" # Example for Azure OpenAI

# You might want to add specific API endpoints if not using standard SDK behavior
# GEMINI_API_ENDPOINT = ""
# OPENAI_API_BASE = "" # For custom OpenAI-compatible endpoints

# Transcript Preferences
# Languages to prioritize for fetching transcripts (in order of preference)
# See: https://github.com/jdepoix/youtube-transcript-api for supported language codes
PREFERRED_TRANSCRIPT_LANGUAGES = ['en'] # Default to English

# Translation Preferences
DEFAULT_TARGET_TRANSLATION_LANGUAGE = "zh-CN" # Default target language for translation

# LLM Batching Configuration for Gemini JSON Mode
TARGET_PROMPT_TOKENS_PER_BATCH = 8000  # Target token limit for the entire prompt string sent to Gemini. A safer, more reasonable value.
MAX_SEGMENTS_PER_GEMINI_JSON_BATCH = 100 # Max segments in a single batch for Gemini JSON translation

# Separator used to join multiple text segments for batch translation (OLD METHOD - no longer used by Gemini JSON)
# and to split the translated output. Ensure it's unique enough.
SEGMENT_SEPARATOR = "\n<segment_separator_youtube_translator>\n"

# LLM Request Delay
SECONDS_BETWEEN_BATCHES = 1 # Seconds to wait between batch API calls

# === New Configurations for Transcript Segment Merging ===
# Maximum duration in seconds for a merged transcript segment.
MERGE_MAX_DURATION_SECONDS = 10.0

# Maximum character length for a merged transcript segment.
MERGE_MAX_CHAR_LENGTH = 120 # Increased slightly for more context

# Punctuation marks that strongly indicate the end of a sentence.
# Used to decide if a segment should be finalized even if below max length/duration.
# Includes both full-width (Chinese, Japanese) and half-width (English) punctuations.
SENTENCE_END_PUNCTUATIONS = ['。', '？', '！', '.', '?', '!']

# Punctuation marks that indicate a sub-clause or a pause within a sentence.
# If a segment ends with one of these, the script will be more inclined to merge
# it with the next segment, provided it doesn't exceed other limits.
SUB_CLAUSE_PUNCTUATIONS = ['，', ',', '、', '；', ';', '：', ':']

# === New Configurations for EPUB Chapter Splitting ===
# The absolute maximum output tokens the model can generate in a single call.
# This is based on the model's specification (e.g., 64k for Gemini 1.5 Flash).
OUTPUT_TOKEN_LIMIT = 64000

# A safety margin to account for unexpected variations and prompt overhead.
# 0.9 means we'll only aim to use 90% of the available token space.
SAFETY_MARGIN = 0.9

# Estimated token expansion factor when translating from source to target language.
# For EN -> ZH, output tokens can be ~2.0x the input tokens.
# For other languages, this might be different (e.g., EN -> ES is closer to 1.3).
# This is a critical parameter to prevent exceeding the model's *output* token limit.
LANGUAGE_EXPANSION_FACTOR = 3.0
