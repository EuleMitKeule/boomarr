"""Tests for resolution/codec/channel filters, invert and richer probe data."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from boomarr.config import (
    AudioChannelsFilterConfig,
    AudioLanguageFilterConfig,
    Config,
    GeneralConfig,
    LoggingConfig,
    ResolutionFilterConfig,
    VideoCodecFilterConfig,
)
from boomarr.filters.audio_language import AudioLanguageFilter
from boomarr.filters.media import (
    AudioChannelsFilter,
    AudioCodecFilter,
    ResolutionFilter,
    VideoCodecFilter,
    effective_height,
)
from boomarr.models import AudioTrack, MediaInfo, VideoTrack
from boomarr.pipeline import PipelineFactory
from boomarr.probers.ffprobe import _extract_video_tracks
from boomarr.state import InMemoryStateStore, SQLiteStateStore


def _info(
    width: int | None = 1920,
    height: int | None = 1080,
    vcodec: str = "hevc",
    acodec: str = "eac3",
    channels: int | None = 6,
    lang: str = "deu",
) -> MediaInfo:
    return MediaInfo(
        file_path=Path("/m/f.mkv"),
        audio_tracks=[AudioTrack(1, lang, acodec, None, channels)],
        video_tracks=[VideoTrack(0, vcodec, width, height)],
    )


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (1920, 1080, 1080),
        (1920, 800, 1080),
        (1440, 1080, 1080),
        (None, 720, 720),
        (None, None, None),
    ],
)
def test_effective_height(
    width: int | None, height: int | None, expected: int | None
) -> None:
    assert effective_height(width, height) == expected


class TestResolutionFilter:
    def test_min(self) -> None:
        f = ResolutionFilter(min_height=1080)
        assert f.matches(_info(1920, 1080))
        assert f.matches(_info(1920, 800))  # cropped scope release is still 1080p
        assert f.matches(_info(3840, 2160))
        assert not f.matches(_info(1280, 720))

    def test_max(self) -> None:
        f = ResolutionFilter(max_height=720)
        assert f.matches(_info(1280, 720))
        assert f.matches(_info(720, 576))
        assert not f.matches(_info(1920, 1080))

    def test_no_video_never_matches(self) -> None:
        info = MediaInfo(Path("/x.mkv"))
        assert not ResolutionFilter(min_height=1).matches(info)

    @pytest.mark.parametrize(
        ("kwargs", "suffix"),
        [
            ({"min_height": 1080}, "1080p-plus"),
            ({"max_height": 720}, "max-720p"),
            ({"min_height": 720, "max_height": 1080}, "720p-1080p"),
        ],
    )
    def test_suffix(self, kwargs: dict[str, int], suffix: str) -> None:
        assert ResolutionFilter(**kwargs).suffix == suffix  # type: ignore[arg-type]
        cfg = ResolutionFilterConfig(**kwargs)  # type: ignore[arg-type]
        assert cfg.effective_suffix() == suffix


class TestCodecAndChannels:
    def test_video_codec_aliases(self) -> None:
        f = VideoCodecFilter(["x265", "AV1"])
        assert f.matches(_info(vcodec="hevc"))
        assert f.matches(_info(vcodec="av1"))
        assert not f.matches(_info(vcodec="h264"))
        assert f.suffix == "av1-hevc"

    def test_audio_codec(self) -> None:
        f = AudioCodecFilter(["truehd", "e-ac-3"])
        assert f.matches(_info(acodec="eac3"))
        assert not f.matches(_info(acodec="aac"))

    def test_channels(self) -> None:
        f = AudioChannelsFilter(min_channels=6)
        assert f.matches(_info(channels=8))
        assert not f.matches(_info(channels=2))
        assert not f.matches(_info(channels=None))
        assert f.suffix == "6ch"


class TestInvert:
    def test_invert_negates(self) -> None:
        f = AudioLanguageFilter(["eng"], invert=True)
        assert f.matches(_info(lang="deu"))
        assert not f.matches(_info(lang="eng"))
        assert f.suffix == "not-eng"

    def test_config_suffix_matches_runtime(self) -> None:
        cfg = AudioLanguageFilterConfig.model_validate(
            {"languages": ["eng"], "invert": True}
        )
        assert cfg.effective_suffix() == "not-eng"


class TestConfig:
    @pytest.mark.parametrize(
        ("raw", "height"),
        [("1080p", 1080), ("4k", 2160), ("UHD", 2160), (720, 720), ("720", 720)],
    )
    def test_height_parsing(self, raw: object, height: int) -> None:
        assert (
            ResolutionFilterConfig.model_validate({"min_height": raw}).min_height
            == height
        )

    def test_resolution_needs_bound(self) -> None:
        with pytest.raises(ValidationError, match="min_height"):
            ResolutionFilterConfig()

    def test_resolution_bounds_ordered(self) -> None:
        with pytest.raises(ValidationError, match="greater"):
            ResolutionFilterConfig(min_height=2160, max_height=720)

    def test_codecs_required(self) -> None:
        with pytest.raises(ValidationError):
            VideoCodecFilterConfig(codecs=[])

    def test_channels_positive(self) -> None:
        with pytest.raises(ValidationError):
            AudioChannelsFilterConfig(min_channels=0)

    def test_combined_filters_build_and_name(self) -> None:
        cfg = Config.model_validate(
            dict(
                config_dir=Path("."),
                config_file="t.yml",
                general=GeneralConfig(),
                logging=LoggingConfig(),
                output_path="/out",
                libraries=[
                    {
                        "name": "Movies",
                        "input_path": "/in",
                        "symlink_libraries": [
                            {
                                "filters": [
                                    {"type": "audio_language", "languages": ["deu"]},
                                    {"type": "resolution", "min_height": "4k"},
                                    {"type": "video_codec", "codecs": ["h265"]},
                                    {"type": "audio_codec", "codecs": ["truehd"]},
                                    {"type": "audio_channels", "min_channels": 6},
                                ]
                            }
                        ],
                    }
                ],
            )
        )
        lib = cfg.libraries[0]
        out = cfg.symlink_library_output(lib, lib.symlink_libraries[0])
        assert out == Path("/out/movies-deu-2160p-plus-hevc-truehd-6ch")
        pipeline = PipelineFactory().for_scan(cfg, lib)
        assert [f.suffix for f in pipeline.symlink_libraries[0].filters] == [
            "deu",
            "2160p-plus",
            "hevc",
            "truehd",
            "6ch",
        ]
        assert pipeline.symlink_libraries[0].output_path == out


def test_ffprobe_skips_cover_art() -> None:
    data = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
            },
            {
                "index": 3,
                "codec_type": "video",
                "codec_name": "mjpeg",
                "width": 600,
                "height": 900,
                "disposition": {"attached_pic": 1},
            },
        ]
    }
    tracks = _extract_video_tracks(data)
    assert [t.codec for t in tracks] == ["hevc"]


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_cache_roundtrip_video_and_channels(kind: str, tmp_path: Path) -> None:
    store = (
        InMemoryStateStore()
        if kind == "memory"
        else SQLiteStateStore(tmp_path / "s.db")
    )
    info = MediaInfo(
        Path("/m/f.mkv"),
        [AudioTrack(1, "deu", "truehd", "Atmos", 8)],
        10,
        1.0,
        [VideoTrack(0, "hevc", 3840, 2160)],
    )
    store.put(info)
    cached = store.get(Path("/m/f.mkv"), 10, 1.0)
    assert cached is not None
    assert cached.audio_tracks[0].channels == 8
    assert cached.video_tracks == [VideoTrack(0, "hevc", 3840, 2160)]
    assert cached.height == 2160
    store.close()
