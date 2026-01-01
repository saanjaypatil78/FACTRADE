import os
import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional
import structlog
from pythonjsonlogger import jsonlogger


class LoggerManager:
    _instance: Optional['LoggerManager'] = None
    _configured = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LoggerManager, cls).__new__(cls)
        return cls._instance

    def setup(
        self,
        log_level: str = "INFO",
        log_directory: str = "./logs",
        max_log_size_mb: int = 100,
        backup_count: int = 10,
        structured: bool = True
    ):
        if self._configured:
            return

        Path(log_directory).mkdir(parents=True, exist_ok=True)

        log_level_num = getattr(logging, log_level.upper(), logging.INFO)

        timestamper = structlog.processors.TimeStamper(fmt="iso")

        shared_processors = [
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            timestamper,
            structlog.processors.StackInfoRenderer(),
        ]

        if structured:
            structlog.configure(
                processors=shared_processors + [
                    structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
                ],
                logger_factory=structlog.stdlib.LoggerFactory(),
                wrapper_class=structlog.stdlib.BoundLogger,
                context_class=dict,
                cache_logger_on_first_use=True,
            )

            formatter = structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=shared_processors,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer(),
                ],
            )
        else:
            structlog.configure(
                processors=shared_processors + [
                    structlog.dev.ConsoleRenderer(),
                ],
                logger_factory=structlog.stdlib.LoggerFactory(),
                wrapper_class=structlog.stdlib.BoundLogger,
                context_class=dict,
                cache_logger_on_first_use=True,
            )
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )

        root_logger = logging.getLogger()
        root_logger.setLevel(log_level_num)
        root_logger.handlers.clear()

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level_num)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        log_file = Path(log_directory) / "rag_system.log"
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_log_size_mb * 1024 * 1024,
            backupCount=backup_count
        )
        file_handler.setLevel(log_level_num)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

        error_log_file = Path(log_directory) / "errors.log"
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=max_log_size_mb * 1024 * 1024,
            backupCount=backup_count
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        root_logger.addHandler(error_handler)

        self._configured = True

    def get_logger(self, name: str):
        return structlog.get_logger(name)


def setup_logging(
    log_level: str = "INFO",
    log_directory: str = "./logs",
    max_log_size_mb: int = 100,
    backup_count: int = 10,
    structured: bool = True
):
    manager = LoggerManager()
    manager.setup(log_level, log_directory, max_log_size_mb, backup_count, structured)


def get_logger(name: str = __name__):
    return structlog.get_logger(name)
