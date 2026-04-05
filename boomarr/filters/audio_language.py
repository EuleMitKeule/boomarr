"""Audio language filter implementation."""

import logging

from boomarr.filters.base import PostProbeFilter
from boomarr.models import MediaInfo

_LOGGER = logging.getLogger(__name__)


class AudioLanguageFilter(PostProbeFilter):
    """Filters media files based on audio track languages.

    A file matches if it contains at least one audio track whose language
    is in the configured language list.
    """

    def __init__(self, languages: list[str], *, suffix: str | None = None) -> None:
        super().__init__(suffix=suffix)
        self._languages = [lang.strip().lower() for lang in languages]

    def matches(self, info: MediaInfo) -> bool:
        if not info.audio_tracks:
            _LOGGER.debug(
                "No audio tracks found in '%s', skipping", info.file_path.name
            )
            return False

        desired = set(self._languages)
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

    def default_suffix(self) -> str:
        """Return languages joined by '-' as the default suffix."""
        return "-".join(sorted(self._languages))
