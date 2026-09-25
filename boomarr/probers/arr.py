"""Sonarr/Radarr based prober.

Reads the audio languages Sonarr/Radarr already determined for every file
(``mediaInfo``) instead of running ffprobe. The whole library is fetched in
one go and cached for ``cache_ttl`` seconds, so probing is a dictionary
lookup. Files unknown to Sonarr/Radarr return ``None`` so that the next
prober in the chain (usually ffprobe) takes over.
"""

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from boomarr.config import PathMapping, map_to_local
from boomarr.languages import language_from_name_or_code
from boomarr.models import AudioTrack, MediaInfo, VideoTrack
from boomarr.probers.base import MediaProber

_LOGGER = logging.getLogger(__name__)


def _parse_languages(raw: object) -> list[str]:
    """Parse ``"ger/eng"``, ``"German / English"`` or ``"eng, fre"``."""
    if not isinstance(raw, str):
        return []
    codes: list[str] = []
    for token in raw.replace(",", "/").split("/"):
        code = language_from_name_or_code(token)
        if code is not None and code not in codes:
            codes.append(code)
    return codes


def _parse_channels(raw: object) -> int | None:
    """Turn ``5.1`` / ``7.1`` / ``2`` into a channel count."""
    try:
        value = float(raw)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None
    main = int(value)
    lfe = round((value - main) * 10)
    return main + lfe if value > 0 else None


def _parse_resolution(raw: object) -> tuple[int | None, int | None]:
    if isinstance(raw, str) and "x" in raw:
        width, _, height = raw.lower().partition("x")
        if width.strip().isdigit() and height.strip().isdigit():
            return int(width), int(height)
    return None, None


def media_info_from_arr(path: Path, info: dict[str, Any]) -> MediaInfo | None:
    """Build a :class:`MediaInfo` from a Sonarr/Radarr ``mediaInfo`` object."""
    languages = _parse_languages(info.get("audioLanguages"))
    if not languages:
        return None
    codec = str(info.get("audioCodec") or "unknown").lower()
    channels = _parse_channels(info.get("audioChannels"))
    width, height = _parse_resolution(info.get("resolution"))
    video_codec = info.get("videoCodec")
    video = (
        [VideoTrack(0, str(video_codec).lower(), width, height)]
        if video_codec or height
        else []
    )
    return MediaInfo(
        file_path=path,
        audio_tracks=[
            AudioTrack(index=i + 1, language=lang, codec=codec, channels=channels)
            for i, lang in enumerate(languages)
        ],
        video_tracks=video,
    )


class ArrProber(MediaProber):
    """Looks up audio languages in Sonarr (``kind="sonarr"``) or Radarr.

    Args:
        kind: ``"sonarr"`` or ``"radarr"``.
        url: Base URL, e.g. ``http://radarr:7878``.
        api_key: API key from Settings → General.
        path_mappings: Translate paths between Sonarr/Radarr and Boomarr.
        cache_ttl: Seconds the fetched library is reused.
        timeout: HTTP timeout per request.
    """

    def __init__(
        self,
        *,
        kind: str,
        url: str,
        api_key: str,
        path_mappings: list[PathMapping] | None = None,
        cache_ttl: float = 300.0,
        timeout: float = 30.0,
    ) -> None:
        self._kind = kind
        self._url = url.rstrip("/")
        self._api_key = api_key
        self._mappings = path_mappings or []
        self._ttl = cache_ttl
        self._timeout = timeout
        self._lock = threading.Lock()
        self._index: dict[Path, dict[str, Any]] = {}
        self._fetched_at: float | None = None

    def _get(self, endpoint: str, **params: object) -> Any:
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{self._url}/api/v3/{endpoint}{query}"
        if not url.startswith(("http://", "https://")):  # pragma: no cover
            raise ValueError(f"Refusing non-HTTP URL: {url}")
        request = urllib.request.Request(  # noqa: S310 - scheme checked
            url, headers={"X-Api-Key": self._api_key, "Accept": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as resp:  # noqa: S310
            return json.load(resp)

    def _files(self) -> list[dict[str, Any]]:
        if self._kind == "radarr":
            return [
                movie["movieFile"]
                for movie in self._get("movie")
                if movie.get("movieFile")
            ]
        files: list[dict[str, Any]] = []
        for series in self._get("series"):
            files.extend(self._get("episodefile", seriesId=series["id"]))
        return files

    def _refresh(self) -> None:
        index: dict[Path, dict[str, Any]] = {}
        for file in self._files():
            path = file.get("path")
            info = file.get("mediaInfo")
            if isinstance(path, str) and isinstance(info, dict):
                index[map_to_local(path, self._mappings)] = info
        self._index = index
        self._fetched_at = time.monotonic()
        _LOGGER.info("Loaded %d files from %s", len(index), self._kind.capitalize())

    def _lookup(self, file: Path) -> dict[str, Any] | None:
        with self._lock:
            stale = (
                self._fetched_at is None
                or time.monotonic() - self._fetched_at > self._ttl
            )
            if stale:
                try:
                    self._refresh()
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    _LOGGER.warning(
                        "Cannot read library from %s (%s); falling back",
                        self._kind.capitalize(),
                        exc,
                    )
                    # Do not hammer an unreachable server for every file.
                    self._fetched_at = time.monotonic()
            return self._index.get(file)

    def probe(self, file: Path) -> MediaInfo | None:
        info = self._lookup(file)
        if info is None:
            return None
        return media_info_from_arr(file, info)

    def check_available(self) -> str | None:
        """Never fatal: an unreachable server only disables this prober."""
        try:
            self._get("system/status")
        except (OSError, ValueError) as exc:
            _LOGGER.warning(
                "%s at %s is not reachable (%s); files will be probed by the "
                "next prober",
                self._kind.capitalize(),
                self._url,
                exc,
            )
        return None
