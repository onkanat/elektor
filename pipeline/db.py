"""Centralized Database Session & Connection Management for Elektor."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional, Union


@contextmanager
def get_db_connection(
    db_path: Union[str, Path],
    timeout: float = 60.0,
    wal_mode: bool = True,
    row_factory: Optional[Any] = None
) -> Generator[sqlite3.Connection, None, None]:
    """Provides a managed SQLite connection with WAL mode, busy timeout,
    automatic commit on normal exit, automatic rollback on exception,
    and guaranteed conn.close() in a finally block.
    """
    path_str = str(db_path)
    if path_str != ":memory:" and not path_str.startswith("file:"):
        parent_dir = Path(path_str).parent
        if parent_dir and not parent_dir.exists():
            parent_dir.mkdir(parents=True, exist_ok=True)

    busy_timeout_ms = int(timeout * 1000)
    conn = sqlite3.connect(path_str, timeout=timeout)
    if row_factory is not None:
        conn.row_factory = row_factory

    try:
        if wal_mode and path_str != ":memory:":
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except sqlite3.OperationalError:
                pass
        try:
            conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms};")
        except sqlite3.OperationalError:
            pass

        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def get_db_cursor(
    db_path: Union[str, Path],
    timeout: float = 60.0,
    row_factory: Optional[Any] = None
) -> Generator[sqlite3.Cursor, None, None]:
    """Provides a managed cursor that automatically commits on normal exit,
    rolls back on exception, and guarantees connection teardown.
    """
    with get_db_connection(db_path, timeout=timeout, wal_mode=True, row_factory=row_factory) as conn:
        cursor = conn.cursor()
        try:
            yield cursor
        finally:
            try:
                cursor.close()
            except Exception:
                pass
