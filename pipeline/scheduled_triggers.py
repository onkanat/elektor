import os
import time
import json
import sqlite3
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

from pipeline.judge_engine import JudgeEngine
from pipeline.gemini_client import get_gemini_client
from pipeline.project_logger import get_project_logger

class ScheduledTriggersManager:
    """
    Manages automated triggers and recurring batch auditing for the Elektor dataset pipeline.
    Executes off-peak quality arbitration, DPO validation, and token-budgeted batch curation.
    """
    def __init__(self, config_or_path: Any = "config.json"):
        if isinstance(config_or_path, dict):
            self.config = config_or_path
        else:
            cpath = Path(config_or_path)
            if cpath.exists():
                with open(cpath, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
            else:
                self.config = {}

        self.logger = get_project_logger()
        self.db_path = self.config.get("db_path", "database/elektor_archive.db")
        db_path_obj = Path(self.db_path)
        if len(db_path_obj.parts) == 1:
            self.db_path = str(Path("database") / self.db_path)

        self._running_triggers = {}
        self._lock = threading.Lock()

    def run_trigger_audit_pass(
        self,
        limit: int = 50,
        mode: str = "strict",
        threshold: float = 7.0,
        auto_rewrite: bool = True
    ) -> Dict[str, Any]:
        """
        Scans SQLite database for unjudged enrichments and executes an automated Judge pass
        within the active token budget limit.
        """
        self.logger.info(f"Trigger started: Running {mode} judge pass on unreviewed records (limit: {limit})...", module="scheduled_triggers")
        
        # 1. Check Token Budget
        client = get_gemini_client(self.config)
        budget_info = client.budget_manager.get_monthly_consumption()
        if budget_info.get("budget_percent", 0) >= 100:
            msg = f"Trigger halted: Monthly token budget cap reached ({budget_info.get('total_tokens', 0):,} tokens)."
            self.logger.warning(msg, module="scheduled_triggers")
            return {"status": "budget_exceeded", "message": msg, "stats": {}}

        # 2. Check pending unjudged count
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='enrichments'")
        if not cursor.fetchone():
            conn.close()
            return {"status": "no_data", "message": "Enrichments table not found.", "stats": {}}

        cursor.execute("""
            SELECT COUNT(*) FROM enrichments
            WHERE judge_status IS NULL OR judge_status = ''
        """)
        unjudged_count = cursor.fetchone()[0]
        conn.close()

        if unjudged_count == 0:
            msg = "All enrichment records have already been judged. Trigger finished with 0 actions."
            self.logger.info(msg, module="scheduled_triggers")
            return {"status": "up_to_date", "message": msg, "stats": {"unjudged_count": 0}}

        # 3. Execute Judge Engine
        target_mode = "hybrid_editor" if (auto_rewrite and mode == "hybrid_editor") else mode
        engine = JudgeEngine(self.config)
        stats = engine.judge_all(limit=limit, mode=target_mode, threshold=threshold)

        return {
            "status": "completed",
            "message": f"Successfully evaluated {stats.get('total', 0)} records.",
            "stats": stats,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        }

    def start_recurring_scheduler(
        self,
        interval_seconds: int = 3600,
        max_iterations: Optional[int] = None,
        limit_per_run: int = 25,
        mode: str = "strict"
    ) -> threading.Thread:
        """
        Starts a background daemon thread that fires the trigger periodically.
        """
        def _worker():
            iteration = 0
            while True:
                iteration += 1
                try:
                    self.run_trigger_audit_pass(limit=limit_per_run, mode=mode)
                except Exception as e:
                    self.logger.error(f"Error during trigger execution iteration {iteration}: {e}", module="scheduled_triggers")

                if max_iterations and iteration >= max_iterations:
                    break

                time.sleep(interval_seconds)

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()
        return thread
