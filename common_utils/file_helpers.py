import re
import string
import logging
from pathlib import Path

from format_converters.time_utils import format_time


# Placeholder for file helper functions
def sanitize_filename(filename):
    """
    Sanitizes a string to be a valid filename.
    Converts to lowercase, replaces spaces with hyphens, and removes invalid characters.
    """
    if not filename:
        return "untitled"
    
    # Convert to lowercase and replace spaces with hyphens
    filename = filename.lower().replace(' ', '-')
    
    # Keep only a-z, 0-9, underscore, hyphen, and period
    valid_chars = string.ascii_lowercase + string.digits + "-_."
    sanitized_name = ''.join(c for c in filename if c in valid_chars)
    
    # Replace multiple hyphens/underscores with a single hyphen
    sanitized_name = re.sub(r'[-_]+', '-', sanitized_name)
    
    # Remove leading/trailing hyphens or underscores
    sanitized_name = sanitized_name.strip('-_')
    
    # Limit length (optional, but good practice)
    max_len = 100
    if len(sanitized_name) > max_len:
        sanitized_name = sanitized_name[:max_len]
        # Ensure it doesn't end with a hyphen
        sanitized_name = sanitized_name.rsplit('-', 1)[0]

    if not sanitized_name: # If all else fails
        return "untitled"
        
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