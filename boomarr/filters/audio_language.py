"""Audio language filter implementation."""

import logging

from boomarr.config import LibraryConfig
from boomarr.filters.base import MediaFilter
from boomarr.models import MediaInfo

_LOGGER = logging.getLogger(__name__)


class AudioLanguageFilter(MediaFilter):
    """Filters media files based on audio track languages.

    A file matches if it contains at least one audio track whose language
    is in the library's configured language list.
    """

    def matches(self, info: MediaInfo, library: LibraryConfig) -> bool:
        if not info.audio_tracks:
            _LOGGER.debug(
                "No audio tracks found in '%s', skipping", info.file_path.name
            )
            return False

        desired = set(library.languages)
        found = {track.language.lower() for track in info.audio_tracks}
        matched = bool(found & desired)

        if not matched:
            _LOGGER.debug(
                "'%s': no matching audio language (wanted %s, found %s)",
                info.file_path.name,
                desired,
                found,
            )
        return matched
