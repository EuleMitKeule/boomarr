"""Audio language filter implementation."""

import logging

from boomarr.const import AudioLanguageMatchMode
from boomarr.filters.base import PostProbeFilter
from boomarr.languages import normalize_language
from boomarr.models import MediaInfo

_LOGGER = logging.getLogger(__name__)


class AudioLanguageFilter(PostProbeFilter):
    """Filters media files based on audio track languages.

    Language codes are normalised before comparison, so ``deu``, ``ger``,
    ``de`` and ``de-DE`` are all treated as the same language. Each
    configured language may additionally list alias codes (e.g. ``und`` for
    untagged tracks) that count as that language.

    In ``any`` mode (default) a file matches if at least one configured
    language is present; in ``all`` mode every configured language must be
    present. The output suffix is derived solely from the configured
    canonical codes, not from aliases or normalisation.
    """

    def __init__(
        self,
        languages: list[str],
        *,
        aliases: dict[str, list[str]] | None = None,
        suffix: str | None = None,
        mode: AudioLanguageMatchMode = AudioLanguageMatchMode.ANY,
    ) -> None:
        super().__init__(suffix=suffix)
        self._languages = [lang.strip().lower() for lang in languages]
        self._mode = mode
        # One accepted-code set per configured language.
        self._groups: dict[str, set[str]] = {}
        alias_map = {k.strip().lower(): v for k, v in (aliases or {}).items()}
        for lang in self._languages:
            group = {normalize_language(lang)}
            group.update(normalize_language(alt) for alt in alias_map.get(lang, []))
            self._groups[lang] = group
        self._match_languages: set[str] = set().union(*self._groups.values())

    def matches(self, info: MediaInfo) -> bool:
        if not info.audio_tracks:
            _LOGGER.debug(
                "No audio tracks found in '%s', skipping", info.file_path.name
            )
            return False

        found = {normalize_language(track.language) for track in info.audio_tracks}
        if self._mode == AudioLanguageMatchMode.ALL:
            matched = all(group & found for group in self._groups.values())
        else:
            matched = bool(found & self._match_languages)

        if not matched:
            _LOGGER.debug(
                "'%s': no matching audio language (wanted %s %s, found %s)",
                info.file_path.name,
                self._mode.value,
                sorted(self._match_languages),
                sorted(found),
            )
        return matched

    def default_suffix(self) -> str:
        """Return canonical languages joined by '-' as the default suffix."""
        return "-".join(sorted(self._languages))
