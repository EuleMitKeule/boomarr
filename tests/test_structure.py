"""Tests for directory structure preservation and multi-season filtering.

Verifies that:
  - Subdirectory hierarchies are mirrored in symlink output.
  - Nested directories (multiple levels) are correctly preserved.
  - Non-media files are NOT symlinked (pre-probe filter skips them).
  - Multi-season show with mixed languages filters correctly per-episode.

Most tests use a mocked SymlinkManager so they run on all platforms
(including Windows where symlink creation needs elevated privileges).
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from boomarr.config import (
    AudioLanguageFilterConfig,
    LanguageEntry,
    LibraryConfig,
    SymlinkLibraryConfig,
)
from boomarr.filters.audio_language import AudioLanguageFilter
from boomarr.filters.file_extension import FileExtensionFilter
from boomarr.models import AudioTrack, MediaInfo
from boomarr.pipeline import Pipeline, ResolvedSymlinkLibrary
from boomarr.processor import LibraryProcessor
from boomarr.state import InMemoryStateStore
from boomarr.symlinks import SymlinkManager
from tests.test_processor import StubProber

_skip_no_symlink = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Symlink creation requires elevated privileges on Windows",
)


def _media_info(path: Path, languages: list[str]) -> MediaInfo:
    """Create a MediaInfo with audio tracks for given ISO 639-1 language codes."""
    return MediaInfo(
        file_path=path,
        audio_tracks=[
            AudioTrack(index=i, language=lang, codec="aac")
            for i, lang in enumerate(languages)
        ],
        size=100,
        mtime=1.0,
    )


def _resolved_sym_lib(
    output_path: Path, languages: list[str] | None = None
) -> ResolvedSymlinkLibrary:
    langs = languages or ["de"]
    return ResolvedSymlinkLibrary(
        filters=[AudioLanguageFilter(languages=langs)],
        output_path=output_path,
    )


def _mock_symlinks() -> MagicMock:
    """Build a mock SymlinkManager that records calls."""
    symlinks = MagicMock(spec=SymlinkManager)
    symlinks.ensure_link.return_value = True
    symlinks.remove_link.return_value = False
    symlinks.clean_stale.return_value = 0
    return symlinks


# ---------------------------------------------------------------------------
# Fixture helpers — build realistic directory trees inside tmp_path
# ---------------------------------------------------------------------------


def _create_movies_tree(input_dir: Path) -> dict[str, Path]:
    """Create movie fixtures: root-level files, subfolder, nested dirs.

    Returns a dict of label → Path for every created file.
    """
    files: dict[str, Path] = {}

    # Root-level movies
    for name in [
        "Sample.Movie.DE.mkv",
        "Sample.Movie.EN.mkv",
        "Sample.Movie.DE.EN.mkv",
    ]:
        p = input_dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.touch()
        files[name] = p

    # Movie in subfolder with non-media sidecars
    sub = input_dir / "Movie.In.Folder"
    sub.mkdir(parents=True, exist_ok=True)
    mkv = sub / "Movie.In.Folder.DE.EN.mkv"
    mkv.touch()
    files["Movie.In.Folder/Movie.In.Folder.DE.EN.mkv"] = mkv

    poster = sub / "poster.jpg"
    poster.write_text("stub", encoding="utf-8")
    files["Movie.In.Folder/poster.jpg"] = poster

    nfo = sub / "movie.nfo"
    nfo.write_text("<nfo/>", encoding="utf-8")
    files["Movie.In.Folder/movie.nfo"] = nfo

    # Nested two levels deep
    nested = input_dir / "Collection" / "Sequel"
    nested.mkdir(parents=True, exist_ok=True)
    sequel = nested / "Sequel.Movie.DE.mkv"
    sequel.touch()
    files["Collection/Sequel/Sequel.Movie.DE.mkv"] = sequel

    srt = nested / "Sequel.Movie.DE.srt"
    srt.write_text("1\n00:00:00 --> 00:00:01\nSub\n", encoding="utf-8")
    files["Collection/Sequel/Sequel.Movie.DE.srt"] = srt

    return files


def _create_shows_tree(input_dir: Path) -> dict[str, Path]:
    """Create a multi-season show with mixed languages and non-media files.

    Sample.Show/
        Season 1/
            S01E01.DE.mkv       - German only
            S01E02.EN.mkv       - English only
            S01E03.DE.EN.mkv    - German + English
            banner.jpg          - non-media
        Season 2/
            S02E01.DE.EN.mkv    - German + English
            S02E02.EN.mkv       - English only
            S02E03.DE.mkv       - German only
            show.nfo            - non-media
    """
    files: dict[str, Path] = {}

    s1 = input_dir / "Sample.Show" / "Season 1"
    s2 = input_dir / "Sample.Show" / "Season 2"
    s1.mkdir(parents=True)
    s2.mkdir(parents=True)

    episodes = [
        ("Sample.Show/Season 1/S01E01.DE.mkv", s1 / "S01E01.DE.mkv"),
        ("Sample.Show/Season 1/S01E02.EN.mkv", s1 / "S01E02.EN.mkv"),
        ("Sample.Show/Season 1/S01E03.DE.EN.mkv", s1 / "S01E03.DE.EN.mkv"),
        ("Sample.Show/Season 2/S02E01.DE.EN.mkv", s2 / "S02E01.DE.EN.mkv"),
        ("Sample.Show/Season 2/S02E02.EN.mkv", s2 / "S02E02.EN.mkv"),
        ("Sample.Show/Season 2/S02E03.DE.mkv", s2 / "S02E03.DE.mkv"),
    ]
    for label, p in episodes:
        p.touch()
        files[label] = p

    # Non-media sidecars
    banner = s1 / "banner.jpg"
    banner.write_text("stub", encoding="utf-8")
    files["Sample.Show/Season 1/banner.jpg"] = banner

    nfo = s2 / "show.nfo"
    nfo.write_text("<nfo/>", encoding="utf-8")
    files["Sample.Show/Season 2/show.nfo"] = nfo

    return files


_SHOW_LANG_MAP: dict[str, list[str]] = {
    "Sample.Show/Season 1/S01E01.DE.mkv": ["de"],
    "Sample.Show/Season 1/S01E02.EN.mkv": ["en"],
    "Sample.Show/Season 1/S01E03.DE.EN.mkv": ["de", "en"],
    "Sample.Show/Season 2/S02E01.DE.EN.mkv": ["de", "en"],
    "Sample.Show/Season 2/S02E02.EN.mkv": ["en"],
    "Sample.Show/Season 2/S02E03.DE.mkv": ["de"],
}


def _build_show_prober(
    files: dict[str, Path],
    lang_map: dict[str, list[str]] | None = None,
) -> StubProber:
    """Build a StubProber for the shows tree using the given language map."""
    lm = lang_map or _SHOW_LANG_MAP
    return StubProber(
        {
            str(files[label]): _media_info(files[label], langs)
            for label, langs in lm.items()
        }
    )


def _build_movie_prober(files: dict[str, Path]) -> StubProber:
    """Build a StubProber for the movies tree, mapping each MKV to German audio."""
    movie_langs: dict[str, list[str]] = {
        "Sample.Movie.DE.mkv": ["de"],
        "Sample.Movie.EN.mkv": ["en"],
        "Sample.Movie.DE.EN.mkv": ["de", "en"],
        "Movie.In.Folder/Movie.In.Folder.DE.EN.mkv": ["de", "en"],
        "Collection/Sequel/Sequel.Movie.DE.mkv": ["de"],
    }
    return StubProber(
        {
            str(files[label]): _media_info(files[label], langs)
            for label, langs in movie_langs.items()
            if label in files
        }
    )


def _make_library(input_dir: Path, output_dir: Path) -> LibraryConfig:
    return LibraryConfig(
        name="Test",
        input_path=input_dir,
        output_path=output_dir,
        symlink_libraries=[
            SymlinkLibraryConfig(
                filters=[
                    AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")])
                ]
            )
        ],
    )


# ---------------------------------------------------------------------------
# Movie structure tests
# ---------------------------------------------------------------------------


class TestMovieDirectoryStructure:
    """Verify subdirectory structure is preserved in symlink output for movies."""

    def test_subfolder_movie_dest_path(self, tmp_path: Path) -> None:
        """A movie inside a subfolder triggers ensure_link with the correct dest."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        files = _create_movies_tree(input_dir)

        mkv = files["Movie.In.Folder/Movie.In.Folder.DE.EN.mkv"]
        prober = StubProber({str(mkv): _media_info(mkv, ["de", "en"])})
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_dir)],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        processor.process_library(_make_library(input_dir, output_dir))

        expected = output_dir / "Movie.In.Folder" / "Movie.In.Folder.DE.EN.mkv"
        symlinks.ensure_link.assert_any_call(mkv, expected)

    def test_nested_two_levels_dest_path(self, tmp_path: Path) -> None:
        """A movie nested two levels deep gets the correct mirrored dest."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        files = _create_movies_tree(input_dir)

        mkv = files["Collection/Sequel/Sequel.Movie.DE.mkv"]
        prober = StubProber({str(mkv): _media_info(mkv, ["de"])})
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_dir)],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        processor.process_library(_make_library(input_dir, output_dir))

        expected = output_dir / "Collection" / "Sequel" / "Sequel.Movie.DE.mkv"
        symlinks.ensure_link.assert_any_call(mkv, expected)

    def test_non_media_files_not_symlinked(self, tmp_path: Path) -> None:
        """Non-media sidecar files (.jpg, .nfo, .srt) must not trigger ensure_link."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        files = _create_movies_tree(input_dir)

        prober = _build_movie_prober(files)
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_dir)],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        processor.process_library(_make_library(input_dir, output_dir))

        # Collect all dest paths passed to ensure_link
        linked_dests = {c.args[1] for c in symlinks.ensure_link.call_args_list}

        # Non-media files must NOT appear
        for label, path in files.items():
            if path.suffix in (".jpg", ".nfo", ".srt"):
                rel = path.relative_to(input_dir)
                assert output_dir / rel not in linked_dests, (
                    f"Non-media file {label} should not be symlinked"
                )

    def test_root_and_nested_movies_together(self, tmp_path: Path) -> None:
        """Root-level and nested movies should all be symlinked with correct paths."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        files = _create_movies_tree(input_dir)

        prober = _build_movie_prober(files)
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_dir)],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(_make_library(input_dir, output_dir))

        linked_dests = {c.args[1] for c in symlinks.ensure_link.call_args_list}

        # All German-containing MKVs should be linked
        assert output_dir / "Sample.Movie.DE.mkv" in linked_dests
        assert output_dir / "Sample.Movie.DE.EN.mkv" in linked_dests
        assert (
            output_dir / "Movie.In.Folder" / "Movie.In.Folder.DE.EN.mkv" in linked_dests
        )
        assert (
            output_dir / "Collection" / "Sequel" / "Sequel.Movie.DE.mkv" in linked_dests
        )

        # English-only should NOT be linked
        assert output_dir / "Sample.Movie.EN.mkv" not in linked_dests

        assert result.created == 4


# ---------------------------------------------------------------------------
# Multi-season show tests
# ---------------------------------------------------------------------------


class TestMultiSeasonFiltering:
    """Verify correct filtering behaviour for a multi-season, mixed-language show."""

    def test_german_filter_selects_correct_episodes(self, tmp_path: Path) -> None:
        """Only episodes with German audio should be symlinked."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        files = _create_shows_tree(input_dir)

        prober = _build_show_prober(files)
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_dir, ["de"])],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(_make_library(input_dir, output_dir))

        linked_dests = {c.args[1] for c in symlinks.ensure_link.call_args_list}

        # German-matching episodes (4 out of 6)
        assert output_dir / "Sample.Show" / "Season 1" / "S01E01.DE.mkv" in linked_dests
        assert (
            output_dir / "Sample.Show" / "Season 1" / "S01E03.DE.EN.mkv" in linked_dests
        )
        assert (
            output_dir / "Sample.Show" / "Season 2" / "S02E01.DE.EN.mkv" in linked_dests
        )
        assert output_dir / "Sample.Show" / "Season 2" / "S02E03.DE.mkv" in linked_dests

        # English-only episodes must NOT be linked
        assert (
            output_dir / "Sample.Show" / "Season 1" / "S01E02.EN.mkv"
            not in linked_dests
        )
        assert (
            output_dir / "Sample.Show" / "Season 2" / "S02E02.EN.mkv"
            not in linked_dests
        )

        assert result.created == 4

    def test_english_filter_selects_correct_episodes(self, tmp_path: Path) -> None:
        """Only episodes with English audio should be symlinked."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        files = _create_shows_tree(input_dir)

        prober = _build_show_prober(files)
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_dir, ["en"])],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(_make_library(input_dir, output_dir))

        linked_dests = {c.args[1] for c in symlinks.ensure_link.call_args_list}

        # English-matching episodes (4 out of 6)
        assert output_dir / "Sample.Show" / "Season 1" / "S01E02.EN.mkv" in linked_dests
        assert (
            output_dir / "Sample.Show" / "Season 1" / "S01E03.DE.EN.mkv" in linked_dests
        )
        assert (
            output_dir / "Sample.Show" / "Season 2" / "S02E01.DE.EN.mkv" in linked_dests
        )
        assert output_dir / "Sample.Show" / "Season 2" / "S02E02.EN.mkv" in linked_dests

        # German-only episodes must NOT be linked
        assert (
            output_dir / "Sample.Show" / "Season 1" / "S01E01.DE.mkv"
            not in linked_dests
        )
        assert (
            output_dir / "Sample.Show" / "Season 2" / "S02E03.DE.mkv"
            not in linked_dests
        )

        assert result.created == 4

    def test_season_dirs_preserved_in_dest_paths(self, tmp_path: Path) -> None:
        """Season subdirectories must appear in the destination paths."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        files = _create_shows_tree(input_dir)

        prober = _build_show_prober(files)
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_dir, ["de"])],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        processor.process_library(_make_library(input_dir, output_dir))

        linked_dests = {c.args[1] for c in symlinks.ensure_link.call_args_list}

        # Verify paths include Season subdirectories
        s1_dest = output_dir / "Sample.Show" / "Season 1" / "S01E01.DE.mkv"
        s2_dest = output_dir / "Sample.Show" / "Season 2" / "S02E03.DE.mkv"
        assert s1_dest in linked_dests
        assert s2_dest in linked_dests

    def test_non_media_files_in_seasons_not_symlinked(self, tmp_path: Path) -> None:
        """Non-media sidecar files inside season dirs must not be symlinked."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        files = _create_shows_tree(input_dir)

        prober = _build_show_prober(files)
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_dir, ["de"])],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        processor.process_library(_make_library(input_dir, output_dir))

        linked_dests = {c.args[1] for c in symlinks.ensure_link.call_args_list}

        assert (
            output_dir / "Sample.Show" / "Season 1" / "banner.jpg" not in linked_dests
        )
        assert output_dir / "Sample.Show" / "Season 2" / "show.nfo" not in linked_dests

    def test_dual_symlink_libraries_de_and_en(self, tmp_path: Path) -> None:
        """Two symlink libraries (DE + EN) should each get the correct episodes."""
        input_dir = tmp_path / "input"
        output_de = tmp_path / "output-de"
        output_en = tmp_path / "output-en"
        files = _create_shows_tree(input_dir)

        prober = _build_show_prober(files)
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[
                _resolved_sym_lib(output_de, ["de"]),
                _resolved_sym_lib(output_en, ["en"]),
            ],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        lib = LibraryConfig(
            name="Shows",
            input_path=input_dir,
            output_path=tmp_path / "output",
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")])
                    ]
                ),
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="en")])
                    ]
                ),
            ],
        )
        result = processor.process_library(lib)

        linked_dests = {c.args[1] for c in symlinks.ensure_link.call_args_list}

        # DE library: 4 episodes
        assert output_de / "Sample.Show" / "Season 1" / "S01E01.DE.mkv" in linked_dests
        assert (
            output_de / "Sample.Show" / "Season 1" / "S01E03.DE.EN.mkv" in linked_dests
        )
        assert (
            output_de / "Sample.Show" / "Season 2" / "S02E01.DE.EN.mkv" in linked_dests
        )
        assert output_de / "Sample.Show" / "Season 2" / "S02E03.DE.mkv" in linked_dests
        assert (
            output_de / "Sample.Show" / "Season 1" / "S01E02.EN.mkv" not in linked_dests
        )

        # EN library: 4 episodes
        assert output_en / "Sample.Show" / "Season 1" / "S01E02.EN.mkv" in linked_dests
        assert (
            output_en / "Sample.Show" / "Season 1" / "S01E03.DE.EN.mkv" in linked_dests
        )
        assert (
            output_en / "Sample.Show" / "Season 2" / "S02E01.DE.EN.mkv" in linked_dests
        )
        assert output_en / "Sample.Show" / "Season 2" / "S02E02.EN.mkv" in linked_dests
        assert (
            output_en / "Sample.Show" / "Season 2" / "S02E03.DE.mkv" not in linked_dests
        )

        # 4 DE + 4 EN = 8 created total
        assert result.created == 8

    def test_multi_language_episode_linked_to_both(self, tmp_path: Path) -> None:
        """An episode with both DE and EN audio appears in both libraries."""
        input_dir = tmp_path / "input"
        output_de = tmp_path / "output-de"
        output_en = tmp_path / "output-en"
        files = _create_shows_tree(input_dir)

        prober = _build_show_prober(files)
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[
                _resolved_sym_lib(output_de, ["de"]),
                _resolved_sym_lib(output_en, ["en"]),
            ],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        lib = LibraryConfig(
            name="Shows",
            input_path=input_dir,
            output_path=tmp_path / "output",
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")])
                    ]
                ),
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="en")])
                    ]
                ),
            ],
        )
        processor.process_library(lib)

        linked_dests = {c.args[1] for c in symlinks.ensure_link.call_args_list}

        # S01E03 (DE+EN) should appear in both outputs
        de_dest = output_de / "Sample.Show" / "Season 1" / "S01E03.DE.EN.mkv"
        en_dest = output_en / "Sample.Show" / "Season 1" / "S01E03.DE.EN.mkv"
        assert de_dest in linked_dests
        assert en_dest in linked_dests

    def test_german_only_episode_not_in_english_library(self, tmp_path: Path) -> None:
        """A German-only episode must not appear in the English symlink library."""
        input_dir = tmp_path / "input"
        output_en = tmp_path / "output-en"
        files = _create_shows_tree(input_dir)

        prober = _build_show_prober(files)
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_en, ["en"])],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        processor.process_library(_make_library(input_dir, output_en))

        linked_dests = {c.args[1] for c in symlinks.ensure_link.call_args_list}

        # German-only episodes: S01E01, S02E03
        assert (
            output_en / "Sample.Show" / "Season 1" / "S01E01.DE.mkv" not in linked_dests
        )
        assert (
            output_en / "Sample.Show" / "Season 2" / "S02E03.DE.mkv" not in linked_dests
        )

    def test_counts_across_seasons(self, tmp_path: Path) -> None:
        """Result counts should be correct across multiple seasons."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        files = _create_shows_tree(input_dir)

        prober = _build_show_prober(files)
        symlinks = _mock_symlinks()

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_dir, ["de"])],
            symlinks=symlinks,
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(_make_library(input_dir, output_dir))

        # 4 DE matches created, 2 EN-only rejected (remove_link returns False → unchanged)
        assert result.created == 4
        assert result.unchanged == 2
        assert result.errors == 0
