"""FFprobe-based media prober implementation."""

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from boomarr.const import DEFAULT_FFPROBE_PATH, DEFAULT_FFPROBE_TIMEOUT
from boomarr.models import AudioTrack, MediaInfo, VideoTrack
from boomarr.probers.base import MediaProber

_LOGGER = logging.getLogger(__name__)


_FFPROBE_ARGS = [
    "-v",
    "error",
    "-print_format",
    "json",
    "-show_entries",
    "stream=index,codec_type,codec_name,channels,width,height"
    ":stream_tags=language,title:stream_disposition=attached_pic",
    "-analyzeduration",
    "0",
    "-probesize",
    "5000000",
]


class FFProbeProber(MediaProber):
    """Probes media files using the FFprobe CLI tool.

    Requires FFprobe (part of FFmpeg) to be installed.

    Args:
        path: FFprobe executable name (looked up on ``PATH``) or path.
        timeout: Seconds before a single probe is aborted.
    """

    def __init__(
        self,
        *,
        path: str = DEFAULT_FFPROBE_PATH,
        timeout: float = DEFAULT_FFPROBE_TIMEOUT,
    ) -> None:
        self._path = path
        self._timeout = timeout

    def check_available(self) -> str | None:
        """Return an error message if the FFprobe binary cannot be found."""
        if shutil.which(self._path) is None:
            return (
                f"FFprobe executable '{self._path}' not found. Install FFmpeg "
                f"or set the prober 'path' option."
            )
        return None

    def probe(self, file: Path) -> MediaInfo | None:
        """Probe a media file using FFprobe and extract audio track metadata."""
        _LOGGER.debug("Probing file: %s", file)

        if not file.is_file():
            _LOGGER.warning("File not found: %s", file)
            return None

        try:
            result = subprocess.run(
                [self._path, *_FFPROBE_ARGS, str(file)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            _LOGGER.error("FFprobe failed for '%s': %s", file, exc)
            return None

        if result.returncode != 0:
            _LOGGER.error(
                "FFprobe returned %d for '%s': %s",
                result.returncode,
                file,
                result.stderr.strip(),
            )
            return None

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            _LOGGER.error("Failed to parse FFprobe output for '%s': %s", file, exc)
            return None

        stat = file.stat()
        return MediaInfo(
            file_path=file,
            audio_tracks=_extract_audio_tracks(data),
            size=stat.st_size,
            mtime=stat.st_mtime,
            video_tracks=_extract_video_tracks(data),
        )


def _extract_audio_tracks(data: dict[str, Any]) -> list[AudioTrack]:
    """Extract audio tracks from parsed FFprobe JSON output."""
    tracks: list[AudioTrack] = []
    for stream in data.get("streams", []):
        if stream.get("codec_type") != "audio":
            continue
        tags = stream.get("tags", {})
        language = tags.get("language", "und")
        tracks.append(
            AudioTrack(
                index=stream.get("index", 0),
                language=language,
                codec=stream.get("codec_name", "unknown"),
                title=tags.get("title"),
                channels=_int_or_none(stream.get("channels")),
            )
        )
    return tracks


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None  # type: ignore[call-overload]
    except TypeError, ValueError:
        return None


def _extract_video_tracks(data: dict[str, Any]) -> list[VideoTrack]:
    """Extract real video tracks (no embedded cover art) from FFprobe JSON."""
    tracks: list[VideoTrack] = []
    for stream in data.get("streams", []):
        if stream.get("codec_type") != "video":
            continue
        if stream.get("disposition", {}).get("attached_pic"):
            continue
        tracks.append(
            VideoTrack(
                index=stream.get("index", 0),
                codec=stream.get("codec_name", "unknown"),
                width=_int_or_none(stream.get("width")),
                height=_int_or_none(stream.get("height")),
            )
        )
    return tracks
