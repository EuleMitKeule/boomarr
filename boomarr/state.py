"""State management module.

Manages persistent state and runtime execution state for Boomarr operations.
Handles tracking of processed files, configuration state, and synchronization
status to enable resumable operations and conflict detection.
"""

import abc
import logging
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


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
    """Simple in-memory state store for initial development.

    TODO: Replace with SQLiteStateStore for real persistence.
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[int, float, bool]] = {}

    def is_unchanged(self, file: Path, size: int, mtime: float) -> bool:
        key = str(file)
        if key not in self._entries:
            return False
        stored_size, stored_mtime, _ = self._entries[key]
        return stored_size == size and stored_mtime == mtime

    def update(self, file: Path, size: int, mtime: float, matched: bool) -> None:
        self._entries[str(file)] = (size, mtime, matched)

    def remove(self, file: Path) -> None:
        self._entries.pop(str(file), None)

    def get_stats(self) -> dict[str, Any]:
        total = len(self._entries)
        matched = sum(1 for _, _, m in self._entries.values() if m)
        return {
            "total_tracked": total,
            "matched": matched,
            "filtered_out": total - matched,
        }
