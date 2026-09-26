"""State management module.

Caches probe results so that unchanged media files never have to be probed
twice. Filters are *not* cached: every scan re-evaluates the cached audio
tracks against the current configuration, so changing languages or adding a
symlink library takes effect on the next scan without re-probing anything.
"""

import abc
import json
import logging
import sqlite3
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from boomarr.models import AudioTrack, MediaInfo, VideoTrack

_LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION: int = 3
SCAN_HISTORY_LIMIT = 500
"""Number of scans kept in the history."""


def _without_changes(record: dict[str, Any]) -> dict[str, Any]:
    result = record.get("result")
    if not isinstance(result, dict) or "changes" not in result:
        return record
    slim = {k: v for k, v in result.items() if k != "changes"}
    slim["changes_count"] = len(result["changes"])
    return {**record, "result": slim}


def _encode_tracks(info: MediaInfo) -> str:
    return json.dumps(
        {
            "a": [
                [t.index, t.language, t.codec, t.title, t.channels]
                for t in info.audio_tracks
            ],
            "v": [[v.index, v.codec, v.width, v.height] for v in info.video_tracks],
        },
        separators=(",", ":"),
    )


def _decode_tracks(raw: str) -> tuple[list[AudioTrack], list[VideoTrack]]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("unexpected cache entry format")
    audio = [
        AudioTrack(
            index=entry[0],
            language=entry[1],
            codec=entry[2],
            title=entry[3],
            channels=entry[4] if len(entry) > 4 else None,
        )
        for entry in data.get("a", [])
    ]
    video = [
        VideoTrack(index=i, codec=codec, width=width, height=height)
        for i, codec, width, height in data.get("v", [])
    ]
    return audio, video


class StateStore(abc.ABC):
    """Persistent cache of probe results keyed by path, size and mtime."""

    @property
    def was_reset(self) -> bool:
        """Return True if the store was wiped during initialisation."""
        return False

    @abc.abstractmethod
    def get(self, file: Path, size: int, mtime: float) -> MediaInfo | None:
        """Return the cached probe result if the file is unchanged, else None."""

    @abc.abstractmethod
    def put(self, info: MediaInfo) -> None:
        """Store the probe result for ``info.file_path``."""

    @abc.abstractmethod
    def remove(self, file: Path) -> None:
        """Remove a file's entry from the store."""

    @abc.abstractmethod
    def prune(self, root: Path, keep: set[Path]) -> int:
        """Drop all entries below *root* that are not in *keep*.

        Returns the number of removed entries.
        """

    @abc.abstractmethod
    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics for the status command."""

    def count(self) -> int:
        """Return the number of cached entries."""
        return int(self.get_stats()["total_cached"])

    @abc.abstractmethod
    def set_meta(self, key: str, value: dict[str, Any]) -> None:
        """Persist a small JSON document (e.g. the last scan report)."""

    @abc.abstractmethod
    def get_meta(self, key: str) -> dict[str, Any] | None:
        """Return a document stored with :meth:`set_meta`, or None."""

    @abc.abstractmethod
    def add_scan(self, record: dict[str, Any]) -> int:
        """Append a scan report to the history and return its id."""

    @abc.abstractmethod
    def list_scans(
        self, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        """Return the newest scans (without change lists) and the total count."""

    @abc.abstractmethod
    def get_scan(self, scan_id: int) -> dict[str, Any] | None:
        """Return one scan including its change list."""

    def close(self) -> None:  # noqa: B027 - optional hook
        """Release resources held by the store."""


class InMemoryStateStore(StateStore):
    """Simple in-memory state store (non-persistent across runs)."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[MediaInfo, float]] = {}
        self._meta: dict[str, dict[str, Any]] = {}
        self._scans: list[dict[str, Any]] = []
        self._next_scan_id = 1
        self._lock = threading.Lock()
        self._hits: int = 0
        self._misses: int = 0

    def get(self, file: Path, size: int, mtime: float) -> MediaInfo | None:
        with self._lock:
            entry = self._entries.get(str(file))
            if entry is None:
                self._misses += 1
                return None
            info, _ = entry
            if info.size == size and info.mtime == mtime:
                self._hits += 1
                return info
            del self._entries[str(file)]
            self._misses += 1
            return None

    def put(self, info: MediaInfo) -> None:
        with self._lock:
            self._entries[str(info.file_path)] = (info, time.time())

    def set_meta(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._meta[key] = json.loads(json.dumps(value, default=str))

    def get_meta(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            return self._meta.get(key)

    def add_scan(self, record: dict[str, Any]) -> int:
        with self._lock:
            scan_id = self._next_scan_id
            self._next_scan_id += 1
            stored = json.loads(json.dumps({**record, "id": scan_id}, default=str))
            self._scans.append(stored)
            del self._scans[:-SCAN_HISTORY_LIMIT]
            return scan_id

    def list_scans(
        self, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            newest = list(reversed(self._scans))
            page = [_without_changes(r) for r in newest[offset : offset + limit]]
            return page, len(newest)

    def get_scan(self, scan_id: int) -> dict[str, Any] | None:
        with self._lock:
            return next((r for r in self._scans if r["id"] == scan_id), None)

    def remove(self, file: Path) -> None:
        with self._lock:
            self._entries.pop(str(file), None)

    def prune(self, root: Path, keep: set[Path]) -> int:
        keep_keys = {str(p) for p in keep}
        with self._lock:
            stale = [
                key
                for key in self._entries
                if Path(key).is_relative_to(root) and key not in keep_keys
            ]
            for key in stale:
                del self._entries[key]
        return len(stale)

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            infos = [info for info, _ in self._entries.values()]
            last = max((ts for _, ts in self._entries.values()), default=None)
            hits, misses = self._hits, self._misses
        return _build_stats(infos, last, hits, misses)


def _build_stats(
    infos: list[MediaInfo], last_probe: float | None, hits: int, misses: int
) -> dict[str, Any]:
    languages: Counter[str] = Counter()
    for info in infos:
        languages.update({t.language.lower() for t in info.audio_tracks})
    lookups = hits + misses
    return {
        "total_cached": len(infos),
        "without_audio": sum(1 for i in infos if not i.audio_tracks),
        "languages": dict(languages.most_common()),
        "last_probe_time": last_probe,
        "hit_rate": hits / lookups if lookups else 0.0,
    }


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS file_cache (
    path       TEXT    PRIMARY KEY,
    mtime      REAL    NOT NULL,
    size       INTEGER NOT NULL,
    tracks     TEXT    NOT NULL,
    probed_at  REAL    NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    finished_at REAL    NOT NULL,
    record      TEXT    NOT NULL
);
"""

_UPSERT_SQL = """
INSERT INTO file_cache (path, mtime, size, tracks, probed_at)
VALUES (?, ?, ?, ?, ?)
ON CONFLICT(path) DO UPDATE SET
    mtime     = excluded.mtime,
    size      = excluded.size,
    tracks    = excluded.tracks,
    probed_at = excluded.probed_at;
"""


def _delete_database_files(db_path: Path) -> None:
    """Delete a SQLite database including its WAL and shared-memory files.

    Leaving a stale ``-wal`` file behind would let SQLite replay old pages
    into the freshly created database.
    """
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{db_path}{suffix}").unlink(missing_ok=True)


class SQLiteStateStore(StateStore):
    """SQLite-backed persistent state store (thread-safe)."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._hits: int = 0
        self._misses: int = 0
        self._lock = threading.Lock()
        self._was_reset: bool = False
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = self._open_or_reset(db_path)
        self._check_schema_version()
        _LOGGER.debug("SQLiteStateStore opened: %s", db_path)

    @staticmethod
    def _connect(db_path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.DatabaseError:
            conn.close()  # e.g. not a database: don't leak the handle
            raise
        return conn

    def _open_or_reset(self, db_path: Path) -> sqlite3.Connection:
        """Open the database, running an integrity check.

        If the file is corrupt or unreadable, delete it and create a fresh one.
        """
        conn: sqlite3.Connection | None = None
        try:
            conn = self._connect(db_path)
            result = conn.execute("PRAGMA quick_check").fetchone()
            if result and result[0] != "ok":
                raise sqlite3.DatabaseError(result[0])
            return conn
        except sqlite3.DatabaseError as exc:
            _LOGGER.warning("SQLite database corrupt (%s), resetting: %s", exc, db_path)
            if conn is not None:
                conn.close()
            _delete_database_files(db_path)
            self._was_reset = True
            return self._connect(db_path)

    def _check_schema_version(self) -> None:
        """Create the schema, or rebuild it if the stored version differs.

        The probe cache only holds derived data, so an incompatible schema is
        simply dropped and rebuilt; files are re-probed on the next scan.
        Existing symlinks are left alone and reconciled by that scan.
        """
        row = self._conn.execute("PRAGMA user_version").fetchone()
        current_version = row[0] if row else 0
        has_table = (
            self._conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='file_cache'"
            ).fetchone()
            is not None
        )
        if current_version != SCHEMA_VERSION:
            if has_table:
                _LOGGER.warning(
                    "Probe cache schema changed (v%d -> v%d): rebuilding cache, "
                    "all files will be probed again on the next scan",
                    current_version,
                    SCHEMA_VERSION,
                )
                self._was_reset = True
            self._conn.execute("DROP TABLE IF EXISTS file_cache")
        self._conn.executescript(_CREATE_TABLE_SQL)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION:d}")
        self._conn.commit()

    @property
    def db_path(self) -> Path:
        """Return the path to the underlying database file."""
        return self._db_path

    @property
    def was_reset(self) -> bool:
        """Return True if the database was reset during initialisation."""
        return self._was_reset

    def get(self, file: Path, size: int, mtime: float) -> MediaInfo | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT mtime, size, tracks FROM file_cache WHERE path = ?",
                (str(file),),
            ).fetchone()
            if row is None:
                self._misses += 1
                return None
            stored_mtime, stored_size, tracks = row
            if stored_mtime == mtime and stored_size == size:
                try:
                    audio_tracks, video_tracks = _decode_tracks(tracks)
                except ValueError, TypeError, IndexError:
                    _LOGGER.warning("Discarding unreadable cache entry for '%s'", file)
                else:
                    self._hits += 1
                    return MediaInfo(
                        file_path=file,
                        audio_tracks=audio_tracks,
                        video_tracks=video_tracks,
                        size=size,
                        mtime=mtime,
                    )
            self._conn.execute("DELETE FROM file_cache WHERE path = ?", (str(file),))
            self._conn.commit()
            self._misses += 1
            return None

    def put(self, info: MediaInfo) -> None:
        with self._lock:
            self._conn.execute(
                _UPSERT_SQL,
                (
                    str(info.file_path),
                    info.mtime,
                    info.size,
                    _encode_tracks(info),
                    time.time(),
                ),
            )
            self._conn.commit()

    def remove(self, file: Path) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM file_cache WHERE path = ?", (str(file),))
            self._conn.commit()

    def prune(self, root: Path, keep: set[Path]) -> int:
        keep_keys = {str(p) for p in keep}
        with self._lock:
            rows = self._conn.execute("SELECT path FROM file_cache").fetchall()
            stale = [
                (path,)
                for (path,) in rows
                if path not in keep_keys and Path(path).is_relative_to(root)
            ]
            if stale:
                self._conn.executemany("DELETE FROM file_cache WHERE path = ?", stale)
                self._conn.commit()
        return len(stale)

    def close(self) -> None:
        """Close the underlying database connection."""
        with self._lock:
            self._conn.close()

    def count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM file_cache").fetchone()
        return int(row[0])

    def set_meta(self, key: str, value: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, default=str)),
            )
            self._conn.commit()

    def get_meta(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        try:
            value = json.loads(row[0])
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def add_scan(self, record: dict[str, Any]) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO scan_history (finished_at, record) VALUES (?, ?)",
                (
                    float(record.get("finished_at") or time.time()),
                    json.dumps(record, default=str),
                ),
            )
            scan_id = int(cursor.lastrowid or 0)
            self._conn.execute(
                "DELETE FROM scan_history WHERE id <= ?",
                (scan_id - SCAN_HISTORY_LIMIT,),
            )
            self._conn.commit()
        return scan_id

    def _decode_scan(self, scan_id: int, raw: str) -> dict[str, Any] | None:
        try:
            record = json.loads(raw)
        except ValueError:
            return None
        return {**record, "id": scan_id} if isinstance(record, dict) else None

    def list_scans(
        self, limit: int = 50, offset: int = 0
    ) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            total = int(
                self._conn.execute("SELECT COUNT(*) FROM scan_history").fetchone()[0]
            )
            rows = self._conn.execute(
                "SELECT id, record FROM scan_history ORDER BY id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        records = [self._decode_scan(scan_id, raw) for scan_id, raw in rows]
        return [_without_changes(r) for r in records if r is not None], total

    def get_scan(self, scan_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, record FROM scan_history WHERE id = ?", (scan_id,)
            ).fetchone()
        return None if row is None else self._decode_scan(row[0], row[1])

    def reset(self) -> None:
        """Delete all cached entries."""
        with self._lock:
            self._conn.execute("DELETE FROM file_cache")
            self._conn.commit()

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT path, size, mtime, tracks, probed_at FROM file_cache"
            ).fetchall()
            hits, misses = self._hits, self._misses
        infos: list[MediaInfo] = []
        last: float | None = None
        for path, size, mtime, tracks, probed_at in rows:
            try:
                audio, video = _decode_tracks(tracks)
            except ValueError, TypeError, IndexError:
                continue
            infos.append(MediaInfo(Path(path), audio, size, mtime, video))
            last = probed_at if last is None else max(last, probed_at)
        return _build_stats(infos, last, hits, misses)
