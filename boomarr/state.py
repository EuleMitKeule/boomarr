"""State management module.

Manages persistent state and runtime execution state for Boomarr operations.
Handles tracking of processed files, configuration state, and synchronization
status to enable resumable operations and conflict detection.
"""

import abc
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION: int = 2


class StateStore(abc.ABC):
    """Persistent store tracking which files have been processed."""

    @abc.abstractmethod
    def is_unchanged(self, file: Path, size: int, mtime: float) -> bool:
        """Return True if the file was previously processed with the same size/mtime."""

    @abc.abstractmethod
    def update(self, file: Path, size: int, mtime: float, matched: bool) -> None:
        """Record that a file has been processed."""

    @abc.abstractmethod
    def remove(self, file: Path) -> None:
        """Remove a file's entry from the store."""

    @abc.abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics for the status command."""


class InMemoryStateStore(StateStore):
    """Simple in-memory state store (non-persistent across runs)."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[int, float, bool]] = {}
        self._hits: int = 0
        self._misses: int = 0
        self._last_scan_time: float | None = None

    def is_unchanged(self, file: Path, size: int, mtime: float) -> bool:
        key = str(file)
        if key not in self._entries:
            self._misses += 1
            return False
        stored_size, stored_mtime, _ = self._entries[key]
        if stored_size == size and stored_mtime == mtime:
            self._hits += 1
            return True
        # File changed — invalidate stale entry
        del self._entries[key]
        self._misses += 1
        return False

    def update(self, file: Path, size: int, mtime: float, matched: bool) -> None:
        self._entries[str(file)] = (size, mtime, matched)
        self._last_scan_time = time.time()

    def remove(self, file: Path) -> None:
        self._entries.pop(str(file), None)

    def get_stats(self) -> dict[str, Any]:
        total = len(self._entries)
        matched = sum(1 for _, _, m in self._entries.values() if m)
        total_probed = self._hits + self._misses
        hit_rate = self._hits / total_probed if total_probed > 0 else 0.0
        return {
            "total_cached": total,
            "matched": matched,
            "filtered_out": total - matched,
            "last_scan_time": self._last_scan_time,
            "hit_rate": hit_rate,
        }


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS file_cache (
    path      TEXT    PRIMARY KEY,
    mtime     REAL    NOT NULL,
    size      INTEGER NOT NULL,
    has_match INTEGER NOT NULL,
    checked_at REAL   NOT NULL
);
"""

_UPSERT_SQL = """
INSERT INTO file_cache (path, mtime, size, has_match, checked_at)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(path) DO UPDATE SET
    mtime      = excluded.mtime,
    size       = excluded.size,
    has_match  = excluded.has_match,
    checked_at = excluded.checked_at;
"""


class SQLiteStateStore(StateStore):
    """SQLite-backed persistent state store."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._hits: int = 0
        self._misses: int = 0
        self._lock = threading.Lock()
        self._was_reset: bool = False
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._open_or_reset(db_path)
        self._conn.executescript(_CREATE_TABLE_SQL)
        self._conn.commit()
        self._check_schema_version()
        _LOGGER.debug("SQLiteStateStore opened: %s", db_path)

    def _check_schema_version(self) -> None:
        """Verify the schema version and reset the database if it doesn't match."""
        row = self._conn.execute("PRAGMA user_version").fetchone()
        current_version = row[0] if row else 0
        if current_version != SCHEMA_VERSION:
            _LOGGER.warning(
                "Database schema version mismatch (got %d, expected %d), resetting",
                current_version,
                SCHEMA_VERSION,
            )
            self._conn.close()
            self._db_path.unlink(missing_ok=True)
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_CREATE_TABLE_SQL)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()
            self._was_reset = True

    @property
    def db_path(self) -> Path:
        """Return the path to the underlying database file."""
        return self._db_path

    @property
    def was_reset(self) -> bool:
        """Return True if the database was reset during initialisation."""
        return self._was_reset

    def _open_or_reset(self, db_path: Path) -> sqlite3.Connection:
        """Open the database, running an integrity check.

        If the file is corrupt or unreadable, delete it and create a fresh one.
        """
        try:
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            result = conn.execute("PRAGMA integrity_check").fetchone()
            if result and result[0] != "ok":
                raise sqlite3.DatabaseError(result[0])
            return conn
        except sqlite3.DatabaseError as exc:
            _LOGGER.warning("SQLite database corrupt (%s), resetting: %s", exc, db_path)
            try:
                conn.close()
            except Exception:
                pass
            db_path.unlink(missing_ok=True)
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            self._was_reset = True
            return conn

    def is_unchanged(self, file: Path, size: int, mtime: float) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT mtime, size FROM file_cache WHERE path = ?",
                (str(file),),
            ).fetchone()
            if row is None:
                self._misses += 1
                return False
            stored_mtime, stored_size = row
            if stored_mtime == mtime and stored_size == size:
                self._hits += 1
                return True
            # File changed — invalidate stale entry
            self._conn.execute("DELETE FROM file_cache WHERE path = ?", (str(file),))
            self._conn.commit()
            self._misses += 1
            return False

    def update(self, file: Path, size: int, mtime: float, matched: bool) -> None:
        with self._lock:
            self._conn.execute(
                _UPSERT_SQL,
                (str(file), mtime, size, 1 if matched else 0, time.time()),
            )
            self._conn.commit()

    def remove(self, file: Path) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM file_cache WHERE path = ?", (str(file),))
            self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        with self._lock:
            self._conn.close()

    def reset(self) -> None:
        """Close the connection, delete the DB file, and reinitialise."""
        self.close()
        self._db_path.unlink(missing_ok=True)
        self.__init__(self._db_path)  # type: ignore[misc]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            total: int = self._conn.execute(
                "SELECT COUNT(*) FROM file_cache"
            ).fetchone()[0]
            matched: int = self._conn.execute(
                "SELECT COUNT(*) FROM file_cache WHERE has_match = 1"
            ).fetchone()[0]
            last_scan_row = self._conn.execute(
                "SELECT MAX(checked_at) FROM file_cache"
            ).fetchone()
            last_scan_time: float | None = last_scan_row[0] if last_scan_row else None
            total_probed = self._hits + self._misses
            hit_rate = self._hits / total_probed if total_probed > 0 else 0.0
        return {
            "total_cached": total,
            "matched": matched,
            "filtered_out": total - matched,
            "last_scan_time": last_scan_time,
            "hit_rate": hit_rate,
        }
