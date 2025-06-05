import logging

# Placeholder for logging configuration functions

def setup_task_logger(logger_name, log_file_path, level=logging.INFO):
    """Sets up a specific logger for a task, outputting to a file.""" # Docstring updated
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    # Prevent duplicate handlers if this function might be called multiple times
    # for the same logger instance with the same name.
    if logger.hasHandlers():
        logger.handlers.clear()

    # File Handler
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')

    # Format: TIMESTAMP - LOGGER_NAME - LEVEL - (MODULE.FUNCTION:LINENO) - MESSAGE
    log_format = '%(asctime)s - %(name)s - %(levelname)s - (%(module)s.%(funcName)s:%(lineno)d) - %(message)s'
    formatter = logging.Formatter(log_format)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger 