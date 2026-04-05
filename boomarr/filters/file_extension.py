"""File extension filter implementation."""

import logging
from pathlib import Path

from boomarr.config import LibraryConfig
from boomarr.const import MEDIA_EXTENSIONS
from boomarr.filters.base import MediaFilter
from boomarr.models import MediaInfo

_LOGGER = logging.getLogger(__name__)


class FileExtensionFilter(MediaFilter):
    """Filters files based on their file extension.

    Only media files with recognized extensions are included.
    """

    def __init__(self, extensions: frozenset[str] = MEDIA_EXTENSIONS) -> None:
        self._extensions = extensions

    def matches(self, info: MediaInfo, library: LibraryConfig) -> bool:
        suffix = info.file_path.suffix.lower()
        if suffix not in self._extensions:
            _LOGGER.debug(
                "Skipping '%s': extension '%s' not in allowed set",
                info.file_path.name,
                suffix,
            )
            return False
        return True

    @staticmethod
    def is_media_file(
        path: Path, extensions: frozenset[str] = MEDIA_EXTENSIONS
    ) -> bool:
        """Quick check without needing a MediaInfo object."""
        return path.suffix.lower() in extensions
