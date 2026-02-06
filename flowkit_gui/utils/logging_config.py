"""
Logging Configuration - Setup logging for FlowKit GUI.

Provides:
- Console handler (INFO level) for immediate feedback
- File handler (DEBUG level) for detailed diagnostics in flowkit_debug.log
"""

import logging
import sys
from pathlib import Path


def setup_logging(log_file: str = "flowkit_debug.log") -> logging.Logger:
    """
    Configure logging for FlowKit GUI.

    Args:
        log_file: Path to the debug log file

    Returns:
        The root logger for the flowkit_gui package
    """
    # Create logger for flowkit_gui package
    logger = logging.getLogger("flowkit_gui")

    # Only configure if not already configured
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # Console handler - INFO level for user-visible messages
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter(
        "[%(levelname)s] %(message)s"
    )
    console_handler.setFormatter(console_format)

    # File handler - DEBUG level for detailed diagnostics
    import sys as _sys
    if getattr(_sys, 'frozen', False):
        _log_dir = Path.home() / ".flowkit_gui"
        _log_dir.mkdir(exist_ok=True)
        log_file = str(_log_dir / log_file)
    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_format)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a specific module.

    Args:
        name: Module name (e.g., 'workspace_model')

    Returns:
        Logger instance for the module
    """
    return logging.getLogger(f"flowkit_gui.{name}")
