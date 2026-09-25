"""Post-probe filters for video resolution, codecs and audio channels."""

import logging

from boomarr.filters.base import PostProbeFilter
from boomarr.models import MediaInfo

_LOGGER = logging.getLogger(__name__)

# Frequently used alternative spellings of codec names reported by ffprobe.
CODEC_ALIASES: dict[str, str] = {
    "h265": "hevc",
    "x265": "hevc",
    "avc": "h264",
    "x264": "h264",
    "avc1": "h264",
    "vp09": "vp9",
    "ac-3": "ac3",
    "e-ac-3": "eac3",
    "ddp": "eac3",
    "dts-hd": "dts",
    "dtshd": "dts",
    "mlp": "truehd",
}

_TOLERANCE = 0.05


def normalize_codec(codec: str) -> str:
    """Return a canonical lower-case codec name."""
    value = codec.strip().lower()
    return CODEC_ALIASES.get(value, value)


def effective_height(width: int | None, height: int | None) -> int | None:
    """Return the height a video would have at 16:9.

    Cropped "scope" encodes (e.g. 1920x800) are still 1080p releases, so the
    width is taken into account: ``max(height, width * 9 / 16)``.
    """
    candidates = [h for h in (height, round(width * 9 / 16) if width else None) if h]
    return max(candidates) if candidates else None


class ResolutionFilter(PostProbeFilter):
    """Matches files whose video resolution lies within the given bounds."""

    def __init__(
        self,
        *,
        min_height: int | None = None,
        max_height: int | None = None,
        suffix: str | None = None,
        invert: bool = False,
    ) -> None:
        super().__init__(suffix=suffix, invert=invert)
        self._min = min_height
        self._max = max_height

    def evaluate(self, info: MediaInfo) -> bool:
        heights = [
            h
            for v in info.video_tracks
            if (h := effective_height(v.width, v.height)) is not None
        ]
        if not heights:
            _LOGGER.debug("'%s': no video resolution known", info.file_path.name)
            return False
        height = max(heights)
        if self._min is not None and height < self._min * (1 - _TOLERANCE):
            return False
        return not (self._max is not None and height > self._max * (1 + _TOLERANCE))

    def default_suffix(self) -> str:
        if self._min is not None and self._max is not None:
            return f"{self._min}p-{self._max}p"
        if self._min is not None:
            return f"{self._min}p-plus"
        return f"max-{self._max}p"


class _CodecFilter(PostProbeFilter):
    def __init__(
        self, codecs: list[str], *, suffix: str | None = None, invert: bool = False
    ) -> None:
        super().__init__(suffix=suffix, invert=invert)
        self._codecs = sorted({normalize_codec(c) for c in codecs})

    def default_suffix(self) -> str:
        return "-".join(self._codecs)


class VideoCodecFilter(_CodecFilter):
    """Matches files with at least one video track in one of the given codecs."""

    def evaluate(self, info: MediaInfo) -> bool:
        return any(normalize_codec(v.codec) in self._codecs for v in info.video_tracks)


class AudioCodecFilter(_CodecFilter):
    """Matches files with at least one audio track in one of the given codecs."""

    def evaluate(self, info: MediaInfo) -> bool:
        return any(normalize_codec(a.codec) in self._codecs for a in info.audio_tracks)


class AudioChannelsFilter(PostProbeFilter):
    """Matches files with at least one audio track with ``min_channels`` or more."""

    def __init__(
        self, *, min_channels: int, suffix: str | None = None, invert: bool = False
    ) -> None:
        super().__init__(suffix=suffix, invert=invert)
        self._min = min_channels

    def evaluate(self, info: MediaInfo) -> bool:
        return any((a.channels or 0) >= self._min for a in info.audio_tracks)

    def default_suffix(self) -> str:
        return f"{self._min}ch"
