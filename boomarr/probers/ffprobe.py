"""FFprobe-based media prober implementation."""

import logging
from pathlib import Path

from boomarr.models import MediaInfo
from boomarr.probers.base import MediaProber

_LOGGER = logging.getLogger(__name__)


class FFProbeProber(MediaProber):
    """Probes media files using the FFprobe CLI tool.

    Requires FFprobe (part of FFmpeg) to be installed and available on PATH.
    """

    def probe(self, file: Path) -> MediaInfo | None:
        """Probe a media file using FFprobe.

        TODO: Implement actual FFprobe subprocess call.
        Currently returns a stub MediaInfo with file stats only.
        """
        _LOGGER.debug("Probing file: %s", file)

        if not file.is_file():
            _LOGGER.warning("File not found: %s", file)
            return None

        stat = file.stat()
        return MediaInfo(
            file_path=file,
            audio_tracks=[],
            size=stat.st_size,
            mtime=stat.st_mtime,
        )
