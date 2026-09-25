"""Tests for language normalisation and the audio language filter modes."""

from pathlib import Path

import pytest

from boomarr.const import AudioLanguageMatchMode
from boomarr.filters.audio_language import AudioLanguageFilter
from boomarr.languages import normalize_language
from boomarr.models import AudioTrack, MediaInfo


def _info(*langs: str) -> MediaInfo:
    return MediaInfo(
        file_path=Path("/m/movie.mkv"),
        audio_tracks=[
            AudioTrack(index=i, language=lang, codec="aac")
            for i, lang in enumerate(langs)
        ],
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("deu", "deu"),
        ("ger", "deu"),
        ("de", "deu"),
        ("DE", "deu"),
        (" de-DE ", "deu"),
        ("de_AT", "deu"),
        ("fre", "fra"),
        ("fr", "fra"),
        ("chi", "zho"),
        ("dut", "nld"),
        ("en", "eng"),
        ("pt-BR", "por"),
        ("und", "und"),
        ("xyz", "xyz"),
        ("", ""),
    ],
)
def test_normalize_language(raw: str, expected: str) -> None:
    assert normalize_language(raw) == expected


class TestAudioLanguageFilterNormalisation:
    @pytest.mark.parametrize("track_lang", ["deu", "ger", "de", "de-DE", "GER"])
    def test_all_spellings_match(self, track_lang: str) -> None:
        assert AudioLanguageFilter(["deu"]).matches(_info(track_lang))

    @pytest.mark.parametrize("configured", ["ger", "de", "DEU"])
    def test_configured_spelling_does_not_matter(self, configured: str) -> None:
        assert AudioLanguageFilter([configured]).matches(_info("deu"))

    def test_suffix_keeps_configured_spelling(self) -> None:
        """Output directory names must not change when normalisation is added."""
        assert AudioLanguageFilter(["ger", "EN"]).suffix == "en-ger"

    def test_alias_is_normalised(self) -> None:
        f = AudioLanguageFilter(["deu"], aliases={"deu": ["und"]})
        assert f.matches(_info("und"))
        assert not f.matches(_info("eng"))


class TestAudioLanguageFilterModes:
    def test_any_mode(self) -> None:
        f = AudioLanguageFilter(["deu", "eng"])
        assert f.matches(_info("deu"))
        assert f.matches(_info("eng"))
        assert not f.matches(_info("fra"))

    def test_all_mode_requires_every_language(self) -> None:
        f = AudioLanguageFilter(["deu", "eng"], mode=AudioLanguageMatchMode.ALL)
        assert f.matches(_info("ger", "en"))
        assert not f.matches(_info("deu"))
        assert not f.matches(_info("eng", "fra"))

    def test_all_mode_accepts_alias_per_language(self) -> None:
        f = AudioLanguageFilter(
            ["deu", "eng"],
            aliases={"deu": ["und"]},
            mode=AudioLanguageMatchMode.ALL,
        )
        assert f.matches(_info("und", "eng"))

    def test_no_tracks_never_match(self) -> None:
        f = AudioLanguageFilter(["deu"], mode=AudioLanguageMatchMode.ALL)
        assert not f.matches(_info())
