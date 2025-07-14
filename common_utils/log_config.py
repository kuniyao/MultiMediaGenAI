import logging

# Placeholder for logging configuration functions

def setup_task_logger(logger_name, log_file_path: str | None = None, level=logging.INFO, console_level=logging.INFO):
    """
    Sets up a logger for a task with controlled file and console output.
    If log_file_path is None, only console logging is configured.
    """
    logger = logging.getLogger(logger_name)
    # If file logging is enabled, the logger's level must be low enough to capture all desired file logs.
    # Otherwise, just use the console level.
    file_log_level = level if log_file_path else console_level
    logger.setLevel(min(file_log_level, console_level))

    # Prevent duplicate handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # File Handler - only if a path is provided
    if log_file_path:
        # File Formatter - for detailed logs
        file_log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        file_formatter = logging.Formatter(file_log_format)
        file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

    # Console Handler - for cleaner, more readable output
    console_log_format = '%(asctime)s - WORKFLOW - %(message)s'
    console_formatter = logging.Formatter(console_log_format)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger 