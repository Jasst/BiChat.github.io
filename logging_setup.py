"""
logging_setup.py — Настройка ротирующего логирования
"""
import os
import logging
import logging.handlers
from config import CONFIG


def setup_logging() -> logging.Logger:
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'messenger.log')

    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=CONFIG['LOG_MAX_BYTES'],
        backupCount=CONFIG['LOG_BACKUP_COUNT'],
        encoding='utf-8',
        delay=True,
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))

    is_prod   = os.getenv('FLASK_ENV') == 'production'
    log_level = logging.WARNING if is_prod else logging.INFO
    handlers  = [file_handler] if is_prod else [file_handler, console_handler]

    logging.basicConfig(level=log_level, handlers=handlers, force=True)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('sqlite3').setLevel(logging.ERROR)
    logging.getLogger('cryptography').setLevel(logging.WARNING)

    logger = logging.getLogger(__name__)
    logger.warning(f"=== App started, log path: {log_path} ===")
    return logger
