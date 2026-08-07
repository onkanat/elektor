import logging
import os
from pathlib import Path
from typing import Optional

class ProjectWarningErrorFilter(logging.Filter):
    """Filter that allows ONLY WARNING, ERROR, and CRITICAL log records."""
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.WARNING

class ProjectLogger:
    """
    Project-isolated logger utility that records ONLY WARNING and ERROR entries
    to exports/<project_id>/errors_and_warnings.log.
    """
    def __init__(self, project_id: str, exports_dir: str = "exports"):
        self.project_id = project_id or "default_project"
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

def get_project_logger(project_id: str) -> ProjectLogger:
    return ProjectLogger(project_id)
