"""Audio language filter implementation."""

import logging

from boomarr.filters.base import PostProbeFilter
from boomarr.models import MediaInfo

_LOGGER = logging.getLogger(__name__)


class AudioLanguageFilter(PostProbeFilter):
    """Filters media files based on audio track languages.

    A file matches if it contains at least one audio track whose language
    is in the configured language list (or any of its configured aliases).
    The output suffix is derived solely from the canonical language codes,
    not the aliases.
    """

    def __init__(
        self,
        languages: list[str],
        *,
        aliases: dict[str, list[str]] | None = None,
        suffix: str | None = None,
    ) -> None:
        super().__init__(suffix=suffix)
        self._languages = [lang.strip().lower() for lang in languages]
        self._match_languages: set[str] = set(self._languages)
        if aliases:
            for canonical, alts in aliases.items():
                canonical_lower = canonical.strip().lower()
                if canonical_lower in self._match_languages:
                    self._match_languages.update(alt.strip().lower() for alt in alts)

    def matches(self, info: MediaInfo) -> bool:
        if not info.audio_tracks:
            _LOGGER.debug(
                "No audio tracks found in '%s', skipping", info.file_path.name
            )
            return False

        found = {track.language.lower() for track in info.audio_tracks}
        matched = bool(found & self._match_languages)

        if not matched:
            _LOGGER.debug(
                "'%s': no matching audio language (wanted %s, found %s)",
                info.file_path.name,
                self._match_languages,
                found,
            )
        return matched

    def default_suffix(self) -> str:
        """Return canonical languages joined by '-' as the default suffix."""
        return "-".join(sorted(self._languages))
