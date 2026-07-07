"""
Centralized logging configuration for Cargonovo Automation.
Supports: console output, file rotation, critical errors to chat.
"""

import logging
import sys
import time
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler

# Log format
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Colors for console output
COLORS = {
    "DEBUG": "\033[36m",     # Cyan
    "INFO": "\033[32m",      # Green
    "WARNING": "\033[33m",   # Yellow
    "ERROR": "\033[31m",     # Red
    "CRITICAL": "\033[35m",  # Magenta
    "RESET": "\033[0m",
}


class ColoredFormatter(logging.Formatter):
    """Formatter with colors for console output."""
    def format(self, record):
        color = COLORS.get(record.levelname, COLORS["RESET"])
        reset = COLORS["RESET"]
        record.levelname = f"{color}{record.levelname}{reset}"
        return super().format(record)


class ChatAlertHandler(logging.Handler):
    """Send CRITICAL errors to Bitrix24 chat."""
    def __init__(self, chat_id=2954):
        super().__init__(level=logging.CRITICAL)
        self.chat_id = chat_id
        self._last_alert = 0
        self._cooldown = 300  # 5 minutes between alerts
    
    def emit(self, record):
        now = time.time()
        if now - self._last_alert < self._cooldown:
            return
        
        try:
            from api_client import log_to_chat
            msg = (
                f"рџљЁ **РљР РРўРР§Р•РЎРљРђРЇ РћРЁРР‘РљРђ**\n"
                f"РњРѕРґСѓР»СЊ: `{record.name}`\n"
                f"РћС€РёР±РєР°: `{record.getMessage()}`\n"
                f"Р’СЂРµРјСЏ: `{datetime.now().strftime('%H:%M:%S')}`"
            )
            if record.exc_info:
                exc = traceback.format_exception(*record.exc_info)
                msg += f"\n```\n{''.join(exc)[-500:]}\n```"
            
            log_to_chat(msg, chat_id=self.chat_id)
            self._last_alert = now
        except Exception:
            pass  # Don't fail if chat notification fails


def setup_logger(name, log_file=None, level=logging.INFO, chat_alerts=True):
    """Setup logger with console and file handlers.
    
    Args:
        name: Logger name (usually __name__)
        log_file: Path to log file (optional)
        level: Logging level
        chat_alerts: Send CRITICAL errors to chat
    
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Console handler with colors
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console_fmt = ColoredFormatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    console.setFormatter(console_fmt)
    logger.addHandler(console)
    
    # File handler with rotation (10MB max, 5 backups)
    if log_file:
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(level)
        file_fmt = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)
    
    # Chat alerts for critical errors
    if chat_alerts:
        chat_handler = ChatAlertHandler()
        logger.addHandler(chat_handler)
    
    return logger


def get_module_logger(module_name):
    """Get pre-configured logger for a module."""
    from config import LOG_FILE
    return setup_logger(f"cargonovo.{module_name}", LOG_FILE)
