import logging

# Placeholder for logging configuration functions

def setup_task_logger(logger_name, log_file_path, level=logging.INFO, console_level=logging.INFO):
    """
    Sets up a logger for a task with controlled file and console output.
    
    Args:
        logger_name (str): The name for the logger.
        log_file_path (str): The path to the log file.
        level (int, optional): The minimum level for logs to be written to the file. Defaults to logging.INFO.
        console_level (int, optional): The minimum level for logs to be displayed on the console. Defaults to logging.INFO.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(min(level, console_level)) # Set logger to the lower of the two levels

    # Prevent duplicate handlers
    if logger.hasHandlers():
        logger.handlers.clear()

    # File Formatter - for detailed logs
    file_log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    file_formatter = logging.Formatter(file_log_format)

    # Console Formatter - for cleaner, more readable output
    console_log_format = '%(asctime)s - WORKFLOW - %(message)s'
    console_formatter = logging.Formatter(console_log_format)

    # File Handler - for detailed logs
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console Handler - for higher-level feedback
    console_handler = logging.StreamHandler()
    console_handler.setLevel(console_level)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger 