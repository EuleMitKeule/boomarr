"""Tests for the probe cache (state stores)."""

import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from boomarr.models import AudioTrack, MediaInfo
from boomarr.state import (
    SCHEMA_VERSION,
    InMemoryStateStore,
    SQLiteStateStore,
    StateStore,
)

FILE_A = Path("/media/movies/a.mkv")
FILE_B = Path("/media/movies/b.mkv")
FILE_OTHER = Path("/media/shows/c.mkv")


def _info(
    path: Path = FILE_A,
    size: int = 100,
    mtime: float = 1.0,
    languages: tuple[str, ...] = ("deu",),
) -> MediaInfo:
    return MediaInfo(
        file_path=path,
        audio_tracks=[
            AudioTrack(index=i + 1, language=lang, codec="aac", title=f"T{i}")
            for i, lang in enumerate(languages)
        ],
        size=size,
        mtime=mtime,
    )


@pytest.fixture(params=["memory", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[StateStore]:
    """Run every contract test against both implementations."""
    s: StateStore
    if request.param == "memory":
        s = InMemoryStateStore()
    else:
        s = SQLiteStateStore(tmp_path / "state.db")
    yield s
    s.close()


class TestStateStoreContract:
    def test_unknown_file_is_a_miss(self, store: StateStore) -> None:
        assert store.get(FILE_A, 100, 1.0) is None

    def test_hit_returns_cached_tracks(self, store: StateStore) -> None:
        store.put(_info(languages=("deu", "eng")))
        cached = store.get(FILE_A, 100, 1.0)
        assert cached is not None
        assert [t.language for t in cached.audio_tracks] == ["deu", "eng"]
        assert cached.audio_tracks[0].codec == "aac"
        assert cached.audio_tracks[0].title == "T0"
        assert cached.file_path == FILE_A

    def test_no_audio_tracks_roundtrip(self, store: StateStore) -> None:
        store.put(_info(languages=()))
        cached = store.get(FILE_A, 100, 1.0)
        assert cached is not None
        assert cached.audio_tracks == []

    @pytest.mark.parametrize(("size", "mtime"), [(101, 1.0), (100, 2.0)])
    def test_changed_file_is_a_miss_and_invalidated(
        self, store: StateStore, size: int, mtime: float
    ) -> None:
        store.put(_info())
        assert store.get(FILE_A, size, mtime) is None
        # The stale entry was dropped, so the original key misses as well.
        assert store.get(FILE_A, 100, 1.0) is None

    def test_put_overwrites(self, store: StateStore) -> None:
        store.put(_info(languages=("deu",)))
        store.put(_info(size=200, mtime=2.0, languages=("eng",)))
        cached = store.get(FILE_A, 200, 2.0)
        assert cached is not None
        assert [t.language for t in cached.audio_tracks] == ["eng"]

    def test_remove(self, store: StateStore) -> None:
        store.put(_info())
        store.remove(FILE_A)
        assert store.get(FILE_A, 100, 1.0) is None

    def test_prune_only_touches_root(self, store: StateStore) -> None:
        store.put(_info(FILE_A))
        store.put(_info(FILE_B))
        store.put(_info(FILE_OTHER))
        removed = store.prune(Path("/media/movies"), keep={FILE_A})
        assert removed == 1
        assert store.get(FILE_A, 100, 1.0) is not None
        assert store.get(FILE_B, 100, 1.0) is None
        assert store.get(FILE_OTHER, 100, 1.0) is not None

    def test_prune_does_not_match_sibling_prefix(self, store: StateStore) -> None:
        sibling = Path("/media/movies-4k/x.mkv")
        store.put(_info(sibling))
        assert store.prune(Path("/media/movies"), keep=set()) == 0
        assert store.get(sibling, 100, 1.0) is not None

    def test_stats_empty(self, store: StateStore) -> None:
        stats = store.get_stats()
        assert stats["total_cached"] == 0
        assert stats["without_audio"] == 0
        assert stats["languages"] == {}
        assert stats["last_probe_time"] is None
        assert stats["hit_rate"] == 0.0

    def test_stats_counts_languages(self, store: StateStore) -> None:
        store.put(_info(FILE_A, languages=("deu", "eng")))
        store.put(_info(FILE_B, languages=("DEU",)))
        store.put(_info(FILE_OTHER, languages=()))
        stats = store.get_stats()
        assert stats["total_cached"] == 3
        assert stats["without_audio"] == 1
        assert stats["languages"] == {"deu": 2, "eng": 1}
        assert stats["last_probe_time"] is not None

    def test_hit_rate(self, store: StateStore) -> None:
        store.put(_info())
        store.get(FILE_A, 100, 1.0)
        store.get(FILE_B, 100, 1.0)
        assert store.get_stats()["hit_rate"] == pytest.approx(0.5)

    def test_thread_safety(self, store: StateStore) -> None:
        def worker(n: int) -> None:
            for i in range(50):
                path = Path(f"/media/movies/{n}-{i}.mkv")
                store.put(_info(path))
                assert store.get(path, 100, 1.0) is not None

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert store.get_stats()["total_cached"] == 200


class TestSQLiteStateStore:
    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        store = SQLiteStateStore(db)
        store.put(_info())
        store.close()

        store2 = SQLiteStateStore(db)
        assert store2.get(FILE_A, 100, 1.0) is not None
        assert store2.was_reset is False
        store2.close()

    def test_fresh_db_is_not_reported_as_reset(self, tmp_path: Path) -> None:
        store = SQLiteStateStore(tmp_path / "fresh.db")
        assert store.was_reset is False
        store.close()

    def test_schema_version_set(self, tmp_path: Path) -> None:
        db = tmp_path / "ver.db"
        SQLiteStateStore(db).close()
        conn = sqlite3.connect(str(db))
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        conn.close()

    def test_old_schema_is_rebuilt(self, tmp_path: Path) -> None:
        db = tmp_path / "old.db"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE file_cache (path TEXT PRIMARY KEY, mtime REAL, "
            "size INTEGER, has_match INTEGER, checked_at REAL)"
        )
        conn.execute("INSERT INTO file_cache VALUES ('/x.mkv', 1.0, 1, 1, 1.0)")
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
        conn.close()

        store = SQLiteStateStore(db)
        assert store.was_reset is True
        assert store.get_stats()["total_cached"] == 0
        store.put(_info())
        assert store.get(FILE_A, 100, 1.0) is not None
        store.close()

    @pytest.mark.parametrize("content", [b"not a sqlite database", b"\x00" * 4096])
    def test_corrupt_db_is_reset(self, tmp_path: Path, content: bytes) -> None:
        db = tmp_path / "corrupt.db"
        db.write_bytes(content)
        store = SQLiteStateStore(db)
        store.put(_info())
        assert store.get(FILE_A, 100, 1.0) is not None
        store.close()

    def test_corrupt_db_sets_was_reset(self, tmp_path: Path) -> None:
        db = tmp_path / "corrupt.db"
        db.write_bytes(b"garbage" * 100)
        store = SQLiteStateStore(db)
        assert store.was_reset is True
        store.close()

    def test_corrupt_reset_removes_stale_wal(self, tmp_path: Path) -> None:
        db = tmp_path / "corrupt.db"
        db.write_bytes(b"garbage" * 100)
        wal = Path(f"{db}-wal")
        wal.write_bytes(b"old wal")
        SQLiteStateStore(db).close()
        assert not wal.exists() or wal.read_bytes() != b"old wal"

    def test_unreadable_cache_entry_is_discarded(self, tmp_path: Path) -> None:
        db = tmp_path / "state.db"
        store = SQLiteStateStore(db)
        store.put(_info())
        store._conn.execute("UPDATE file_cache SET tracks = 'not json'")
        store._conn.commit()
        assert store.get(FILE_A, 100, 1.0) is None
        assert store.get_stats()["total_cached"] == 0
        store.close()

    def test_reset_clears_entries(self, tmp_path: Path) -> None:
        store = SQLiteStateStore(tmp_path / "state.db")
        store.put(_info())
        store.reset()
        assert store.get_stats()["total_cached"] == 0
        store.put(_info(FILE_B))
        assert store.get(FILE_B, 100, 1.0) is not None
        store.close()

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        db = tmp_path / "nested" / "dir" / "state.db"
        store = SQLiteStateStore(db)
        assert db.exists()
        assert store.db_path == db
        store.close()
