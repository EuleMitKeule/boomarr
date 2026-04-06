"""FFprobe-based media prober implementation."""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from boomarr.models import AudioTrack, MediaInfo
from boomarr.probers.base import MediaProber

_LOGGER = logging.getLogger(__name__)

_FFPROBE_CMD = [
    "ffprobe",
    "-v",
    "quiet",
    "-print_format",
    "json",
    "-show_entries",
    "stream=index,codec_type,codec_name:stream_tags=language,title",
    "-analyzeduration",
    "0",
    "-probesize",
    "5000000",
]


class FFProbeProber(MediaProber):
    """Probes media files using the FFprobe CLI tool.

    Requires FFprobe (part of FFmpeg) to be installed and available on PATH.
    """

    def probe(self, file: Path) -> MediaInfo | None:
        """Probe a media file using FFprobe and extract audio track metadata."""
        _LOGGER.debug("Probing file: %s", file)

        if not file.is_file():
            _LOGGER.warning("File not found: %s", file)
            return None

        try:
            result = subprocess.run(
                [*_FFPROBE_CMD, str(file)],
                capture_output=True,
                text=True,
                timeout=30,
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

        audio_tracks = _extract_audio_tracks(data)

        stat = file.stat()
        return MediaInfo(
            file_path=file,
            audio_tracks=audio_tracks,
            size=stat.st_size,
            mtime=stat.st_mtime,
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
            )
        )
    return tracks
