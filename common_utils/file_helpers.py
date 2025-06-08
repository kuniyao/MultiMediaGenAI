import re
import string
import logging
from pathlib import Path

from common_utils.time_utils import format_time


# Placeholder for file helper functions
def sanitize_filename(filename):
    """
    Sanitizes a string to be a valid filename.
    Removes or replaces invalid characters.
    """
    if not filename:
        return "untitled"
    # Replace problematic characters with underscores
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    sanitized_name = ''.join(c if c in valid_chars else '_' for c in filename)
    # Replace multiple underscores with a single one
    sanitized_name = re.sub(r'__+', '_', sanitized_name)
    # Remove leading/trailing underscores or spaces
    sanitized_name = sanitized_name.strip('_ ')
    # Limit length (optional, but good practice)
    max_len = 100
    if len(sanitized_name) > max_len:
        sanitized_name = sanitized_name[:max_len].rsplit('_', 1)[0] # try to cut at a separator
        if not sanitized_name : # if rsplit removed everything
             sanitized_name = filename[:max_len//2] # fallback to a hard cut of original
    if not sanitized_name: # If all else fails
        return "untitled_video"
    return sanitized_name

def save_to_file(content, filename, logger=None):
    """Saves content to a file."""
    logger_to_use = logger if logger else logging.getLogger(__name__)
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        logger_to_use.debug(f"Successfully saved to {filename}")
    except IOError as e:
        logger_to_use.error(f"Error saving file {filename}: {e}", exc_info=True) 