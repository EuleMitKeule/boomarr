"""Domain data models for Boomarr.

Contains value objects representing media metadata, audio track information,
and scan operation results used throughout the application.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class AudioTrack:
    """A single audio track extracted from a media file."""

    index: int
    language: str
    codec: str
    title: str | None = None


@dataclass(frozen=True)
class MediaInfo:
    """Probed metadata for a single media file."""

    file_path: Path
    audio_tracks: list[AudioTrack] = field(default_factory=list)
    size: int = 0
    mtime: float = 0.0


@dataclass
class ScanResult:
    """Aggregated results from processing a library."""

    created: int = 0
    removed: int = 0
    unchanged: int = 0
    skipped: int = 0
    errors: int = 0

    @property
    def total(self) -> int:
        return self.created + self.removed + self.unchanged + self.skipped + self.errors

    def merge(self, other: ScanResult) -> ScanResult:
        """Merge another result into this one, returning self for chaining."""
        self.created += other.created
        self.removed += other.removed
        self.unchanged += other.unchanged
        self.skipped += other.skipped
        self.errors += other.errors
        return self
