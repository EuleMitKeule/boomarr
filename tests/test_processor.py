"""Tests for the processor and pipeline subsystems."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from boomarr.config import (
    AudioLanguageFilterConfig,
    Config,
    GeneralConfig,
    LibraryConfig,
    LoggingConfig,
    PostProbeFilterConfig,
    PreProbeFilterConfig,
    ProberConfig,
    SymlinkLibraryConfig,
)
from boomarr.filters.audio_language import AudioLanguageFilter
from boomarr.filters.file_extension import FileExtensionFilter
from boomarr.models import AudioTrack, MediaInfo, ScanResult
from boomarr.pipeline import Pipeline, PipelineFactory, ResolvedSymlinkLibrary
from boomarr.probers.base import MediaProber
from boomarr.processor import LibraryProcessor
from boomarr.state import InMemoryStateStore
from boomarr.symlinks import SymlinkManager


class StubProber(MediaProber):
    """Returns pre-configured MediaInfo for testing."""

    def __init__(self, results: dict[str, MediaInfo | None]) -> None:
        self._results = results

    def probe(self, file: Path) -> MediaInfo | None:
        return self._results.get(str(file))


def _make_library(tmp_path: Path) -> LibraryConfig:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    return LibraryConfig(
        name="Test",
        input_path=input_dir,
        output_path=output_dir,
        symlink_libraries=[
            SymlinkLibraryConfig(
                filters=[
                    AudioLanguageFilterConfig(languages=["de"]),
                ],
            ),
        ],
    )


def _make_config() -> Config:
    return Config(
        config_dir=Path("."),
        config_file="test.yml",
        general=GeneralConfig(),
        logging=LoggingConfig(),
    )


def _resolved_sym_lib(
    output_path: Path,
    languages: list[str] | None = None,
) -> ResolvedSymlinkLibrary:
    """Build a ResolvedSymlinkLibrary for testing."""
    langs = languages or ["de"]
    return ResolvedSymlinkLibrary(
        filters=[AudioLanguageFilter(languages=langs)],
        output_path=output_path,
    )


class TestFileExtensionFilter:
    def test_mkv_passes(self) -> None:
        f = FileExtensionFilter()
        assert f.matches(Path("/media/movie.mkv")) is True

    def test_txt_rejected(self) -> None:
        f = FileExtensionFilter()
        assert f.matches(Path("/media/readme.txt")) is False

    def test_custom_extensions(self) -> None:
        f = FileExtensionFilter(extensions=frozenset({".custom"}))
        assert f.matches(Path("/media/file.custom")) is True

    def test_is_media_file_true(self) -> None:
        assert FileExtensionFilter.is_media_file(Path("/m.mkv")) is True

    def test_is_media_file_false(self) -> None:
        assert FileExtensionFilter.is_media_file(Path("/m.txt")) is False

    def test_is_media_file_custom_extensions(self) -> None:
        assert (
            FileExtensionFilter.is_media_file(Path("/m.custom"), frozenset({".custom"}))
            is True
        )


class TestAudioLanguageFilter:
    def test_matching_language(self) -> None:
        f = AudioLanguageFilter(languages=["de"])
        info = MediaInfo(
            file_path=Path("/m.mkv"),
            audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
        )
        assert f.matches(info) is True

    def test_no_matching_language(self) -> None:
        f = AudioLanguageFilter(languages=["de"])
        info = MediaInfo(
            file_path=Path("/m.mkv"),
            audio_tracks=[AudioTrack(index=0, language="en", codec="aac")],
        )
        assert f.matches(info) is False

    def test_no_tracks_rejected(self) -> None:
        f = AudioLanguageFilter(languages=["de"])
        info = MediaInfo(file_path=Path("/m.mkv"), audio_tracks=[])
        assert f.matches(info) is False

    def test_default_suffix(self) -> None:
        f = AudioLanguageFilter(languages=["de", "en"])
        assert f.default_suffix() == "de-en"

    def test_custom_suffix(self) -> None:
        f = AudioLanguageFilter(languages=["de"], suffix="german")
        assert f.suffix == "german"

    def test_suffix_falls_back_to_default(self) -> None:
        f = AudioLanguageFilter(languages=["de"])
        assert f.suffix == "de"


class TestScanResult:
    def test_merge(self) -> None:
        a = ScanResult(created=1, removed=2)
        b = ScanResult(created=3, errors=1)
        a.merge(b)
        assert a.created == 4
        assert a.removed == 2
        assert a.errors == 1

    def test_total(self) -> None:
        r = ScanResult(created=1, removed=2, unchanged=3, skipped=4, errors=5)
        assert r.total == 15


class TestInMemoryStateStore:
    def test_new_file_not_unchanged(self) -> None:
        store = InMemoryStateStore()
        assert store.is_unchanged(Path("/a.mkv"), 100, 1.0) is False

    def test_unchanged_after_update(self) -> None:
        store = InMemoryStateStore()
        store.update(Path("/a.mkv"), 100, 1.0, matched=True)
        assert store.is_unchanged(Path("/a.mkv"), 100, 1.0) is True

    def test_changed_mtime(self) -> None:
        store = InMemoryStateStore()
        store.update(Path("/a.mkv"), 100, 1.0, matched=True)
        assert store.is_unchanged(Path("/a.mkv"), 100, 2.0) is False

    def test_stats(self) -> None:
        store = InMemoryStateStore()
        store.update(Path("/a.mkv"), 100, 1.0, matched=True)
        store.update(Path("/b.mkv"), 200, 2.0, matched=False)
        stats = store.get_stats()
        assert stats["total_tracked"] == 2
        assert stats["matched"] == 1

    def test_remove_clears_entry(self) -> None:
        """remove() should delete a tracked entry (line 53)."""
        store = InMemoryStateStore()
        store.update(Path("/a.mkv"), 100, 1.0, matched=True)
        store.remove(Path("/a.mkv"))
        assert store.is_unchanged(Path("/a.mkv"), 100, 1.0) is False

    def test_remove_nonexistent_is_noop(self) -> None:
        """remove() on an unknown path should not raise."""
        store = InMemoryStateStore()
        store.remove(Path("/never_added.mkv"))  # must not raise


_skip_no_symlink = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Symlink creation requires elevated privileges on Windows",
)


class TestSymlinkManager:
    @_skip_no_symlink
    def test_ensure_and_remove(self, tmp_path: Path) -> None:
        source = tmp_path / "source.mkv"
        source.touch()
        dest = tmp_path / "output" / "source.mkv"

        mgr = SymlinkManager()
        assert mgr.ensure_link(source, dest) is True
        assert dest.is_symlink()
        # Second call should be no-op
        assert mgr.ensure_link(source, dest) is False
        # Remove
        assert mgr.remove_link(dest) is True
        assert not dest.exists()

    @_skip_no_symlink
    def test_clean_stale(self, tmp_path: Path) -> None:
        out = tmp_path / "output"
        out.mkdir()
        stale = out / "gone.mkv"
        stale.symlink_to(tmp_path / "nonexistent")

        mgr = SymlinkManager()
        assert mgr.clean_stale(out) == 1
        assert not stale.exists()


class TestPipelineFactory:
    def test_for_scan_has_pre_probe_filters(self) -> None:
        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        assert len(pipeline.pre_probe_filters) == 1
        assert isinstance(pipeline.pre_probe_filters[0], FileExtensionFilter)

    def test_for_scan_resolves_symlink_libraries(self) -> None:
        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        assert len(pipeline.symlink_libraries) == 1
        assert isinstance(pipeline.symlink_libraries[0].filters[0], AudioLanguageFilter)

    def test_for_scan_auto_output_path(self) -> None:
        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        expected = Path(f"{library.output_path}-de")
        assert pipeline.symlink_libraries[0].output_path == expected

    def test_for_scan_named_output_path(self) -> None:
        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    name="german",
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        expected = library.output_path.parent / "german"
        assert pipeline.symlink_libraries[0].output_path == expected

    def test_for_clean_has_no_pre_probe_filters(self) -> None:
        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_clean(config, library)
        assert len(pipeline.pre_probe_filters) == 0

    def test_library_prober_override(self) -> None:
        from boomarr.config import FFProbeProberConfig

        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            probers=[FFProbeProberConfig()],
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        assert len(pipeline.probers) == 1

    def test_library_pre_probe_filter_override_empty(self) -> None:
        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            pre_probe_filters=[],
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        assert len(pipeline.pre_probe_filters) == 0

    def test_build_probers_unknown_type_raises(self) -> None:
        """Unknown prober type falls through to raise ValueError (lines 87-88)."""
        mock_config = MagicMock()
        mock_config.type = "totally_unknown_prober"
        with pytest.raises(ValueError, match="Unknown prober"):
            PipelineFactory._build_probers([mock_config])

    def test_build_pre_probe_filters_custom_extensions(self) -> None:
        """FileExtensionFilterConfig with explicit extensions list (line 102)."""
        from boomarr.config import FileExtensionFilterConfig

        config = FileExtensionFilterConfig(extensions=[".mkv", ".mp4"])
        filters = PipelineFactory._build_pre_probe_filters([config])
        assert len(filters) == 1
        assert isinstance(filters[0], FileExtensionFilter)

    def test_build_pre_probe_filters_unknown_type_raises(self) -> None:
        """Unknown pre-probe filter type falls through to raise ValueError (lines 107-108)."""
        mock_config = MagicMock()
        mock_config.type = "totally_unknown_filter"
        with pytest.raises(ValueError, match="Unknown pre-probe filter"):
            PipelineFactory._build_pre_probe_filters([mock_config])

    def test_build_post_probe_filter_unknown_type_raises(self) -> None:
        """Unknown post-probe filter type falls through to raise ValueError (lines 125-126)."""
        mock_config = MagicMock()
        mock_config.type = "totally_unknown_post_filter"
        with pytest.raises(ValueError, match="Unknown post-probe filter type"):
            PipelineFactory._build_post_probe_filter(mock_config)


class TestLibraryProcessor:
    def test_process_empty_input(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        output_de = Path(f"{library.output_path}-de")
        pipeline = Pipeline(
            probers=[StubProber({})],
            pre_probe_filters=[],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=SymlinkManager(),
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.total == 0

    @_skip_no_symlink
    def test_process_creates_symlink(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()

        prober = StubProber(
            {
                str(media): MediaInfo(
                    file_path=media,
                    audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
                    size=100,
                    mtime=1.0,
                )
            }
        )
        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=SymlinkManager(),
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.created == 1
        assert (output_de / "movie.mkv").is_symlink()

    @_skip_no_symlink
    def test_process_skips_non_matching(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()

        prober = StubProber(
            {
                str(media): MediaInfo(
                    file_path=media,
                    audio_tracks=[AudioTrack(index=0, language="en", codec="aac")],
                    size=100,
                    mtime=1.0,
                )
            }
        )
        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=SymlinkManager(),
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.created == 0
        assert not (output_de / "movie.mkv").exists()


class TestLibraryProcessorOrchestration:
    """Tests for LibraryProcessor orchestration logic (no symlinks needed)."""

    def test_nonexistent_input_returns_empty_result(self, tmp_path: Path) -> None:
        """If the input path doesn't exist, result should be empty."""
        library = LibraryConfig(
            name="Ghost",
            input_path=tmp_path / "nonexistent",
            output_path=tmp_path / "output",
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        output_de = tmp_path / "output-de"
        pipeline = Pipeline(
            probers=[StubProber({})],
            symlink_libraries=[_resolved_sym_lib(output_de)],
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.total == 0

    def test_probe_returns_none_counts_as_error(self, tmp_path: Path) -> None:
        """When the prober returns None for a file, it should be counted as an error."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "bad.mkv"
        media.touch()

        prober = StubProber({str(media): None})
        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(output_de)],
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.errors == 1
        assert result.total == 1

    def test_state_skips_unchanged_files(self, tmp_path: Path) -> None:
        """Files already processed with same size/mtime should be skipped."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()

        info = MediaInfo(
            file_path=media,
            audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
            size=100,
            mtime=1.0,
        )
        prober = StubProber({str(media): info})
        state = InMemoryStateStore()
        state.update(media, 100, 1.0, matched=True)

        pipeline = Pipeline(
            probers=[prober],
            state=state,
            symlink_libraries=[_resolved_sym_lib(output_de)],
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.skipped == 1
        assert result.created == 0

    def test_state_reprocesses_changed_mtime(self, tmp_path: Path) -> None:
        """A file with changed mtime should be reprocessed, not skipped."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()

        info = MediaInfo(
            file_path=media,
            audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
            size=100,
            mtime=2.0,
        )
        prober = StubProber({str(media): info})
        state = InMemoryStateStore()
        state.update(media, 100, 1.0, matched=True)  # old mtime

        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.ensure_link.return_value = True
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober],
            state=state,
            symlinks=symlinks,
            symlink_libraries=[_resolved_sym_lib(output_de)],
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.skipped == 0
        assert result.created == 1

    def test_filter_rejects_file_calls_remove_link(self, tmp_path: Path) -> None:
        """When a filter rejects a file, remove_link should be called on dest."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()

        info = MediaInfo(
            file_path=media,
            audio_tracks=[AudioTrack(index=0, language="en", codec="aac")],
            size=100,
            mtime=1.0,
        )
        prober = StubProber({str(media): info})
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.remove_link.return_value = True
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=symlinks,
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.removed == 1
        symlinks.remove_link.assert_called_once()

    def test_filter_rejects_no_existing_symlink(self, tmp_path: Path) -> None:
        """When filter rejects and no symlink exists, counts as unchanged."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()

        info = MediaInfo(
            file_path=media,
            audio_tracks=[AudioTrack(index=0, language="en", codec="aac")],
            size=100,
            mtime=1.0,
        )
        prober = StubProber({str(media): info})
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.remove_link.return_value = False  # nothing to remove
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=symlinks,
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.unchanged == 1

    def test_filter_passes_existing_symlink_unchanged(self, tmp_path: Path) -> None:
        """When filter passes and symlink already exists, counts as unchanged."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()

        info = MediaInfo(
            file_path=media,
            audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
            size=100,
            mtime=1.0,
        )
        prober = StubProber({str(media): info})
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.ensure_link.return_value = False  # already existed
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=symlinks,
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.unchanged == 1

    def test_exception_during_processing_counts_as_error(self, tmp_path: Path) -> None:
        """An exception raised during processing should be caught and counted."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()

        prober = MagicMock(spec=MediaProber)
        prober.probe.side_effect = RuntimeError("boom")
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober],
            symlinks=symlinks,
            symlink_libraries=[_resolved_sym_lib(output_de)],
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.errors == 1

    def test_multiple_files_mixed_results(self, tmp_path: Path) -> None:
        """Process multiple files with different outcomes."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        good = library.input_path / "good.mkv"
        bad = library.input_path / "bad.mkv"
        good.touch()
        bad.touch()

        prober = StubProber(
            {
                str(good): MediaInfo(
                    file_path=good,
                    audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
                    size=100,
                    mtime=1.0,
                ),
                str(bad): None,
            }
        )
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.ensure_link.return_value = True
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=symlinks,
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.created == 1
        assert result.errors == 1
        assert result.total == 2

    def test_clean_stale_added_to_removed_count(self, tmp_path: Path) -> None:
        """Stale symlinks cleaned should be added to removed count."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.clean_stale.return_value = 5

        pipeline = Pipeline(
            probers=[StubProber({})],
            symlinks=symlinks,
            symlink_libraries=[_resolved_sym_lib(output_de)],
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.removed == 5

    def test_dest_path_mirrors_input_structure(self, tmp_path: Path) -> None:
        """Destination path should mirror the relative path from input."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        subdir = library.input_path / "subdir"
        subdir.mkdir()
        media = subdir / "movie.mkv"
        media.touch()

        info = MediaInfo(
            file_path=media,
            audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
            size=100,
            mtime=1.0,
        )
        prober = StubProber({str(media): info})
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.ensure_link.return_value = True
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=symlinks,
        )
        processor = LibraryProcessor(pipeline)
        processor.process_library(library)

        expected_dest = output_de / "subdir" / "movie.mkv"
        symlinks.ensure_link.assert_called_once_with(media, expected_dest)

    def test_pre_probe_filter_skips_non_media(self, tmp_path: Path) -> None:
        """Pre-probe filters should skip files before probing."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.txt"  # bad extension
        media.touch()

        info = MediaInfo(
            file_path=media,
            audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
            size=100,
            mtime=1.0,
        )
        prober = StubProber({str(media): info})
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober],
            pre_probe_filters=[FileExtensionFilter()],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=symlinks,
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        # Pre-probe filter rejects, so prober should not be called
        assert result.total == 0

    def test_state_updated_after_processing(self, tmp_path: Path) -> None:
        """State store should be updated after a file is processed."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()

        info = MediaInfo(
            file_path=media,
            audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
            size=100,
            mtime=1.0,
        )
        prober = StubProber({str(media): info})
        state = InMemoryStateStore()
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.ensure_link.return_value = True
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=symlinks,
            state=state,
        )
        processor = LibraryProcessor(pipeline)
        processor.process_library(library)

        # After first run, file should be marked as unchanged
        assert state.is_unchanged(media, 100, 1.0) is True

    def test_clean_library_delegates_to_symlink_manager(self, tmp_path: Path) -> None:
        """clean_library should only call clean_stale."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.clean_stale.return_value = 3

        pipeline = Pipeline(
            probers=[StubProber({})],
            symlinks=symlinks,
            symlink_libraries=[_resolved_sym_lib(output_de)],
        )
        processor = LibraryProcessor(pipeline)
        count = processor.clean_library(library)

        assert count == 3
        symlinks.clean_stale.assert_called_once_with(output_de)

    def test_prober_fallback_chain(self, tmp_path: Path) -> None:
        """Second prober should be used when the first returns None."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()

        info = MediaInfo(
            file_path=media,
            audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
            size=100,
            mtime=1.0,
        )
        prober1 = StubProber({})  # returns None for everything
        prober2 = StubProber({str(media): info})  # has the result

        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.ensure_link.return_value = True
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober1, prober2],
            symlink_libraries=[_resolved_sym_lib(output_de)],
            symlinks=symlinks,
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.created == 1

    def test_multiple_symlink_libraries(self, tmp_path: Path) -> None:
        """A single file can be linked into multiple symlink libraries."""
        library = _make_library(tmp_path)
        output_de = tmp_path / "output-de"
        output_en = tmp_path / "output-en"
        media = library.input_path / "movie.mkv"
        media.touch()

        info = MediaInfo(
            file_path=media,
            audio_tracks=[
                AudioTrack(index=0, language="de", codec="aac"),
                AudioTrack(index=1, language="en", codec="aac"),
            ],
            size=100,
            mtime=1.0,
        )
        prober = StubProber({str(media): info})
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.ensure_link.return_value = True
        symlinks.clean_stale.return_value = 0

        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[
                _resolved_sym_lib(output_de, ["de"]),
                _resolved_sym_lib(output_en, ["en"]),
            ],
            symlinks=symlinks,
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.created == 2


class TestPipelineFactoryExtended:
    """Extended tests for PipelineFactory."""

    def test_for_watch_has_filters(self) -> None:
        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_watch(config, library)
        assert len(pipeline.pre_probe_filters) == 1
        assert len(pipeline.symlink_libraries) == 1

    def test_shared_state_across_pipelines(self) -> None:
        """Pipelines from the same factory should share state."""
        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        state = InMemoryStateStore()
        factory = PipelineFactory(state=state)
        scan = factory.for_scan(config, library)
        watch = factory.for_watch(config, library)
        assert scan.state is state
        assert watch.state is state

    def test_for_clean_uses_provided_state(self) -> None:
        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                ),
            ],
        )
        state = InMemoryStateStore()
        factory = PipelineFactory(state=state)
        pipeline = factory.for_clean(config, library)
        assert pipeline.state is state

    def test_unknown_prober_raises(self) -> None:
        with pytest.raises(ValidationError):
            ProberConfig(type="nonexistent")  # type: ignore[arg-type]

    def test_unknown_pre_probe_filter_raises(self) -> None:
        with pytest.raises(ValidationError):
            PreProbeFilterConfig(type="nonexistent")  # type: ignore[arg-type]

    def test_unknown_post_probe_filter_raises(self) -> None:
        with pytest.raises(ValidationError):
            PostProbeFilterConfig(type="nonexistent")  # type: ignore[arg-type]

    def test_audio_language_filter_without_languages_raises(self) -> None:
        from boomarr.const import PostProbeFilterType

        config = PostProbeFilterConfig(type=PostProbeFilterType.AUDIO_LANGUAGE)
        with pytest.raises(ValueError, match="languages"):
            PipelineFactory._build_post_probe_filter(config)

    def test_explicit_output_path_used(self) -> None:
        config = _make_config()
        library = LibraryConfig(
            name="T",
            input_path=Path("/a"),
            output_path=Path("/b"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=["de"]),
                    ],
                    output_path=Path("/custom/output"),
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        assert (
            pipeline.symlink_libraries[0].output_path
            == Path("/custom/output").resolve()
        )
