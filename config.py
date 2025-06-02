# config.py
"""
Configuration settings for the YouTube Translator script.
"""

# LLM Configuration
LLM_PROVIDER = "gemini"  # Options: "gemini", "openai", "azure_openai", or "custom"
# Specify the model for the selected provider
LLM_MODEL_GEMINI = "gemini-2.5-flash-preview-05-20" # Example for Gemini
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

# LLM Batching Configuration
# Target character limit for input segments in a single batch.
# This is NOT the model's absolute token limit, but a practical limit for batching.
# (1 token ~ 4 chars for English. 50,000 chars ~ 12,500 tokens, well within limits)
# Adjust based on typical segment length and desired batch size.
TARGET_INPUT_CHAR_LIMIT_PER_BATCH = 50000

# Separator used to join multiple text segments for batch translation
# and to split the translated output. Ensure it's unique enough.
SEGMENT_SEPARATOR = "\n<segment_separator_youtube_translator>\n"

# Fallback Batching Configuration (when a primary large batch fails segment count check)
FALLBACK_BATCH_MAX_SEGMENTS = 100  # Max segments in a smaller fallback batch
FALLBACK_BATCH_CHAR_LIMIT = 15000  # Approx char limit for a fallback batch

# Placeholder for future batching/rate-limiting settings for LLM calls
# LLM_BATCH_SIZE = 5 # Number of segments to translate per API call
# LLM_REQUEST_DELAY = 1 # Seconds to wait between batch API calls

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
