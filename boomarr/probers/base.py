"""Abstract base class for media probers."""

import abc
from pathlib import Path

from boomarr.models import MediaInfo


class MediaProber(abc.ABC):
    """Extracts audio/video metadata from media files.

    Subclasses implement the actual probing logic (e.g. FFprobe subprocess,
    Radarr/Sonarr API query).
    """

    @abc.abstractmethod
    def probe(self, file: Path) -> MediaInfo | None:
        """Probe a media file and return its metadata.

        Returns None if the file cannot be probed (unsupported format,
        corrupted, inaccessible, etc.).
        """
