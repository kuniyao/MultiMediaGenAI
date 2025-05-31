# config.py
"""
Configuration settings for the YouTube Translator script.
"""

# LLM Configuration
LLM_PROVIDER = "gemini"  # Options: "gemini", "openai", "azure_openai", or "custom"
# Specify the model for the selected provider
LLM_MODEL_GEMINI = "gemini-pro" # Example for Gemini
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

# Placeholder for future batching/rate-limiting settings for LLM calls
# LLM_BATCH_SIZE = 5 # Number of segments to translate per API call
# LLM_REQUEST_DELAY = 1 # Seconds to wait between batch API calls
