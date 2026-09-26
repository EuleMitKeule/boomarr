"""Domain data models for Boomarr.

Contains value objects representing media metadata, audio track information,
and scan operation results used throughout the application.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_RECORDED_CHANGES = 500
"""Maximum number of individual link changes kept per scan (for the UI)."""

ProgressCallback = Callable[[dict[str, Any]], None]
"""Receives progress updates such as ``{"library": ..., "phase": ...}``."""


@dataclass(frozen=True)
class AudioTrack:
    """A single audio track extracted from a media file."""

    index: int
    language: str
    codec: str
    title: str | None = None
    channels: int | None = None


@dataclass(frozen=True)
class VideoTrack:
    """A single video track extracted from a media file (cover art excluded)."""

    index: int
    codec: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class MediaInfo:
    """Probed metadata for a single media file."""

    file_path: Path
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    size: int = 0
    mtime: float = 0.0
    video_tracks: list[VideoTrack] = field(default_factory=list)

    @property
    def height(self) -> int | None:
        """Return the height of the largest video track, if any."""
        heights = [v.height for v in self.video_tracks if v.height]
        return max(heights) if heights else None


@dataclass(frozen=True)
class ScanEvent:
    """A trigger event requesting a full library rescan.

    All trigger sources produce these events into the shared watcher queue.
    The watcher debounces and processes them.
    """

    source: str
    timestamp: float
    dry_run: bool = False
    force: bool = False


@dataclass
class ScanResult:
    """Aggregated results from processing a library."""

    created: int = 0
    removed: int = 0
    unchanged: int = 0
    probed: int = 0
    skipped: int = 0
    filtered: int = 0
    errors: int = 0
    blocked: int = 0
    links: dict[str, int] = field(default_factory=dict)
    changed_outputs: set[str] = field(default_factory=set)
    changes: list[dict[str, str]] = field(default_factory=list)

    def record_change(
        self, action: str, path: Path, target: Path | None = None
    ) -> None:
        """Remember an individual link change (capped at ``MAX_RECORDED_CHANGES``)."""
        if len(self.changes) >= MAX_RECORDED_CHANGES:
            return
        change = {"action": action, "path": str(path)}
        if target is not None:
            change["target"] = str(target)
        self.changes.append(change)

    @property
    def total(self) -> int:
        return (
            self.created
            + self.removed
            + self.unchanged
            + self.probed
            + self.skipped
            + self.filtered
            + self.errors
        )

    def merge(self, other: ScanResult) -> ScanResult:
        """Merge another result into this one, returning self for chaining."""
        self.created += other.created
        self.removed += other.removed
        self.unchanged += other.unchanged
        self.probed += other.probed
        self.skipped += other.skipped
        self.filtered += other.filtered
        self.errors += other.errors
        self.blocked += other.blocked
        self.links.update(other.links)
        self.changed_outputs |= other.changed_outputs
        room = MAX_RECORDED_CHANGES - len(self.changes)
        self.changes.extend(other.changes[: max(room, 0)])
        return self


@dataclass(frozen=True)
class RemovalGuard:
    """Refuses mass deletions that are more likely an accident than intended.

    A reconciliation is blocked when it would remove more than
    ``min_count`` symlinks *and* more than ``max_percent`` of the existing
    symlinks of an output directory.
    """

    max_percent: float
    min_count: int

    def blocks(self, removals: int, existing: int) -> bool:
        if removals <= self.min_count or existing <= 0:
            return False
        return removals * 100 / existing > self.max_percent
