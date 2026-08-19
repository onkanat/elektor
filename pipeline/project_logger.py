import logging
import sys
import os
import json
import traceback
from pathlib import Path
from typing import Optional

def resolve_project_id(config_path: str = "config.json") -> str:
    """Resolves active project_id from config.json or database basename."""
    if Path(config_path).exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                if cfg.get("project_id"):
                    return str(cfg["project_id"]).strip()
                if cfg.get("db_path"):
                    return Path(cfg["db_path"]).stem
        except Exception:
            pass
    return "default_project"

class ProjectWarningErrorFilter(logging.Filter):
    """Filter that allows ONLY WARNING, ERROR, and CRITICAL log records."""
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING

class ProjectLogger:
    """
    Project-isolated logger utility that records ONLY WARNING and ERROR entries
    to exports/<project_id>/errors_and_warnings.log.
    """
    def __init__(self, project_id: Optional[str] = None, exports_dir: str = "exports"):
        self.project_id = project_id or resolve_project_id()
        self.log_dir = Path(exports_dir) / self.project_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / "errors_and_warnings.log"

        self.logger = logging.getLogger(f"project_logger_{self.project_id}")
        self.logger.setLevel(logging.WARNING)

        # Avoid duplicate handlers if logger already initialized
        if not self.logger.handlers:
            handler = logging.FileHandler(self.log_file, encoding="utf-8")
            handler.setLevel(logging.WARNING)
            handler.addFilter(ProjectWarningErrorFilter())
            formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def info(self, message: str, module: str = "pipeline"):
        # Log info messages or print them gracefully
        print(f"[{module}] {message}")

    def warning(self, message: str, module: str = "pipeline"):
        self.logger.warning(f"[{module}] {message}")

    def error(self, message: str, module: str = "pipeline"):
        self.logger.error(f"[{module}] {message}")

    def get_log_content(self, max_lines: int = 100) -> str:
        if not self.log_file.exists():
            return "Henüz uyarı veya hata günlüğü kaydedilmedi."
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                return "".join(lines[-max_lines:])
        except Exception as e:
            return f"Log okuma hatası: {str(e)}"

_GLOBAL_LOGGER_INSTANCES = {}

def get_project_logger(project_id: Optional[str] = None) -> ProjectLogger:
    pid = project_id or resolve_project_id()
    if pid not in _GLOBAL_LOGGER_INSTANCES:
        _GLOBAL_LOGGER_INSTANCES[pid] = ProjectLogger(pid)
    return _GLOBAL_LOGGER_INSTANCES[pid]

def setup_global_project_logging(project_id: Optional[str] = None):
    """
    Sets up Python root logger and unhandled exception hook so ANY warning or error
    in the process is automatically recorded to exports/<project_id>/errors_and_warnings.log.
    """
    proj_logger = get_project_logger(project_id)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)

    # Attach handler if not present
    handler_exists = any(isinstance(h, logging.FileHandler) and h.baseFilename == str(proj_logger.log_file.resolve()) for h in root_logger.handlers)
    if not handler_exists:
        file_h = logging.FileHandler(proj_logger.log_file, encoding="utf-8")
        file_h.setLevel(logging.WARNING)
        file_h.addFilter(ProjectWarningErrorFilter())
        file_h.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        root_logger.addHandler(file_h)

    # Global unhandled exception hook
    def custom_excepthook(exc_type, exc_value, exc_traceback):
        tb_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        proj_logger.error(f"Unhandled Exception: {exc_type.__name__}: {exc_value}\n{tb_msg}", module="sys_excepthook")
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = custom_excepthook
    return proj_logger
