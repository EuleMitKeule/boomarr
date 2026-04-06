"""Tests for InMemoryStateStore and SQLiteStateStore."""

from pathlib import Path

import pytest

from boomarr.state import InMemoryStateStore, SQLiteStateStore

# ---------------------------------------------------------------------------
# Shared behaviour expected from every StateStore implementation
# ---------------------------------------------------------------------------

FILE_A = Path("/media/movies/a.mkv")
FILE_B = Path("/media/movies/b.mkv")


class _SharedStateBehaviour:
    """Mixin with tests that must pass for every StateStore implementation."""

    def make_store(
        self, tmp_path: Path
    ) -> InMemoryStateStore | SQLiteStateStore:  # pragma: no cover
        raise NotImplementedError

    # --- cache miss (unknown file) ---

    def test_unknown_file_is_not_unchanged(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        assert store.is_unchanged(FILE_A, size=100, mtime=1.0) is False

    # --- cache hit ---

    def test_hit_after_update(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        assert store.is_unchanged(FILE_A, size=100, mtime=1.0) is True

    # --- invalidation on mtime change ---

    def test_miss_on_mtime_change(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        assert store.is_unchanged(FILE_A, size=100, mtime=2.0) is False

    def test_entry_removed_after_mtime_change(self, tmp_path: Path) -> None:
        """After a mtime-triggered miss, the entry must be gone (invalidated)."""
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        store.is_unchanged(FILE_A, size=100, mtime=2.0)  # triggers invalidation
        # A second call with the ORIGINAL mtime should still miss
        assert store.is_unchanged(FILE_A, size=100, mtime=1.0) is False

    # --- invalidation on size change ---

    def test_miss_on_size_change(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        assert store.is_unchanged(FILE_A, size=200, mtime=1.0) is False

    # --- explicit remove ---

    def test_remove_clears_entry(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        store.remove(FILE_A)
        assert store.is_unchanged(FILE_A, size=100, mtime=1.0) is False

    def test_remove_nonexistent_is_noop(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.remove(FILE_A)  # must not raise

    # --- stats: total_cached / matched ---

    def test_stats_empty(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        stats = store.get_stats()
        assert stats["total_cached"] == 0
        assert stats["matched"] == 0
        assert stats["filtered_out"] == 0

    def test_stats_after_updates(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        store.update(FILE_B, size=200, mtime=2.0, matched=False)
        stats = store.get_stats()
        assert stats["total_cached"] == 2
        assert stats["matched"] == 1
        assert stats["filtered_out"] == 1

    def test_stats_filtered_out_equals_total_minus_matched(
        self, tmp_path: Path
    ) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=False)
        store.update(FILE_B, size=200, mtime=2.0, matched=False)
        stats = store.get_stats()
        assert stats["filtered_out"] == stats["total_cached"] - stats["matched"]

    # --- hit rate tracking ---

    def test_hit_rate_zero_when_no_probes(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        assert store.get_stats()["hit_rate"] == 0.0

    def test_hit_rate_one_after_pure_hits(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        store.is_unchanged(FILE_A, size=100, mtime=1.0)  # hit
        stats = store.get_stats()
        assert stats["hit_rate"] == pytest.approx(1.0)

    def test_hit_rate_zero_after_pure_misses(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.is_unchanged(FILE_A, size=100, mtime=1.0)  # miss
        stats = store.get_stats()
        assert stats["hit_rate"] == pytest.approx(0.0)

    def test_hit_rate_half_on_equal_hits_and_misses(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        store.is_unchanged(FILE_A, size=100, mtime=1.0)  # hit
        store.is_unchanged(FILE_B, size=200, mtime=2.0)  # miss
        stats = store.get_stats()
        assert stats["hit_rate"] == pytest.approx(0.5)

    # --- upsert: re-update same path ---

    def test_update_overwrites_existing_entry(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        store.update(FILE_A, size=200, mtime=2.0, matched=False)
        # Only one entry should exist (upsert, not insert)
        assert store.get_stats()["total_cached"] == 1
        assert store.get_stats()["matched"] == 0
        # Current values produce a hit
        assert store.is_unchanged(FILE_A, size=200, mtime=2.0) is True


# ---------------------------------------------------------------------------
# InMemoryStateStore
# ---------------------------------------------------------------------------


class TestInMemoryStateStore(_SharedStateBehaviour):
    def make_store(self, tmp_path: Path) -> InMemoryStateStore:
        return InMemoryStateStore()

    def test_last_scan_time_none_before_update(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        assert store.get_stats()["last_scan_time"] is None

    def test_last_scan_time_set_after_update(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        assert store.get_stats()["last_scan_time"] is not None


# ---------------------------------------------------------------------------
# SQLiteStateStore
# ---------------------------------------------------------------------------


class TestSQLiteStateStore(_SharedStateBehaviour):
    def make_store(self, tmp_path: Path) -> SQLiteStateStore:
        return SQLiteStateStore(tmp_path / "test.db")

    def test_db_file_created(self, tmp_path: Path) -> None:
        db_path = tmp_path / "mydb.db"
        SQLiteStateStore(db_path)
        assert db_path.exists()

    def test_db_dir_created_when_missing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "subdir" / "nested" / "test.db"
        SQLiteStateStore(db_path)
        assert db_path.exists()

    def test_last_scan_time_none_when_empty(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        assert store.get_stats()["last_scan_time"] is None

    def test_last_scan_time_set_after_update(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        assert store.get_stats()["last_scan_time"] is not None

    def test_persistence_across_instances(self, tmp_path: Path) -> None:
        """Data written by one instance must be readable by a new instance."""
        db_path = tmp_path / "persist.db"
        store1 = SQLiteStateStore(db_path)
        store1.update(FILE_A, size=100, mtime=1.0, matched=True)
        store1.close()

        store2 = SQLiteStateStore(db_path)
        assert store2.is_unchanged(FILE_A, size=100, mtime=1.0) is True
        stats = store2.get_stats()
        assert stats["total_cached"] == 1
        assert stats["matched"] == 1

    def test_invalidation_persists_across_instances(self, tmp_path: Path) -> None:
        """An invalidated entry must stay gone after reopening the DB."""
        db_path = tmp_path / "persist.db"
        store1 = SQLiteStateStore(db_path)
        store1.update(FILE_A, size=100, mtime=1.0, matched=True)
        # Trigger invalidation via size change
        store1.is_unchanged(FILE_A, size=999, mtime=1.0)
        store1.close()

        store2 = SQLiteStateStore(db_path)
        assert store2.is_unchanged(FILE_A, size=100, mtime=1.0) is False
        assert store2.get_stats()["total_cached"] == 0

    def test_close_is_idempotent(self, tmp_path: Path) -> None:
        store = self.make_store(tmp_path)
        store.close()
        # Second close should not raise
        store.close()

    def test_corrupt_db_is_reset(self, tmp_path: Path) -> None:
        """A corrupt database file should be silently replaced."""
        db_path = tmp_path / "corrupt.db"
        db_path.write_bytes(b"this is not a sqlite database")

        store = SQLiteStateStore(db_path)
        # Should be usable after reset
        store.update(FILE_A, size=100, mtime=1.0, matched=True)
        assert store.is_unchanged(FILE_A, size=100, mtime=1.0) is True
        store.close()

    def test_has_threading_lock(self, tmp_path: Path) -> None:
        """SQLiteStateStore should have a threading lock for thread safety."""
        import threading

        store = self.make_store(tmp_path)
        assert hasattr(store, "_lock")
        assert isinstance(store._lock, type(threading.Lock()))
