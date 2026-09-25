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
    LanguageEntry,
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
                    AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
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

    def test_alias_matches(self) -> None:
        f = AudioLanguageFilter(languages=["deu"], aliases={"deu": ["ger"]})
        info = MediaInfo(
            file_path=Path("/m.mkv"),
            audio_tracks=[AudioTrack(index=0, language="ger", codec="aac")],
        )
        assert f.matches(info) is True

    def test_alias_suffix_unchanged(self) -> None:
        """Aliases must not appear in the suffix."""
        f = AudioLanguageFilter(languages=["deu"], aliases={"deu": ["ger"]})
        assert f.suffix == "deu"

    def test_alias_for_unconfigured_language_ignored(self) -> None:
        """Aliases only expand languages that are actually configured."""
        f = AudioLanguageFilter(languages=["eng"], aliases={"deu": ["ger"]})
        info = MediaInfo(
            file_path=Path("/m.mkv"),
            audio_tracks=[AudioTrack(index=0, language="ger", codec="aac")],
        )
        assert f.matches(info) is False


class TestScanResult:
    def test_merge(self) -> None:
        a = ScanResult(created=1, removed=2)
        b = ScanResult(created=3, errors=1, filtered=5)
        a.merge(b)
        assert a.created == 4
        assert a.removed == 2
        assert a.errors == 1
        assert a.filtered == 5

    def test_total(self) -> None:
        r = ScanResult(
            created=1, removed=2, unchanged=3, skipped=4, filtered=6, errors=5
        )
        assert r.total == 21


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

    @_skip_no_symlink
    def test_clean_stale_valid_symlink_kept(self, tmp_path: Path) -> None:
        """A symlink whose target still exists must not be removed."""
        source = tmp_path / "real.mkv"
        source.touch()
        out = tmp_path / "output"
        out.mkdir()
        link = out / "real.mkv"
        link.symlink_to(source)

        mgr = SymlinkManager()
        assert mgr.clean_stale(out) == 0
        assert link.is_symlink()

    @_skip_no_symlink
    def test_clean_stale_prunes_empty_dir(self, tmp_path: Path) -> None:
        """Empty directory left by stale symlink removal must be pruned."""
        out = tmp_path / "output"
        sub = out / "Season 1"
        sub.mkdir(parents=True)
        stale = sub / "ep.mkv"
        stale.symlink_to(tmp_path / "nonexistent")

        mgr = SymlinkManager()
        assert mgr.clean_stale(out) == 1
        assert not stale.exists()
        assert not sub.exists(), "empty subdirectory should have been pruned"

    @_skip_no_symlink
    def test_clean_stale_prunes_nested_empty_dirs(self, tmp_path: Path) -> None:
        """Nested empty dirs (Show/Season/ep) must all be removed bottom-up."""
        out = tmp_path / "output"
        nested = out / "Show" / "Season 2"
        nested.mkdir(parents=True)
        stale = nested / "ep.mkv"
        stale.symlink_to(tmp_path / "nonexistent")

        mgr = SymlinkManager()
        assert mgr.clean_stale(out) == 1
        assert not stale.exists()
        assert not nested.exists(), "leaf empty dir should be pruned"
        assert not (out / "Show").exists(), "parent empty dir should be pruned"

    @_skip_no_symlink
    def test_clean_stale_keeps_nonempty_dir(self, tmp_path: Path) -> None:
        """A directory that still holds a valid symlink must not be removed."""
        source = tmp_path / "real.mkv"
        source.touch()
        out = tmp_path / "output"
        sub = out / "Season 1"
        sub.mkdir(parents=True)
        valid = sub / "real.mkv"
        valid.symlink_to(source)
        stale = sub / "gone.mkv"
        stale.symlink_to(tmp_path / "nonexistent")

        mgr = SymlinkManager()
        assert mgr.clean_stale(out) == 1
        assert not stale.exists()
        assert sub.is_dir(), "non-empty subdirectory must not be removed"
        assert valid.is_symlink(), "valid symlink must be preserved"

    @_skip_no_symlink
    def test_clean_stale_logs_removed_symlink(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Each removed stale symlink must be logged at INFO level."""
        import logging

        out = tmp_path / "output"
        sub = out / "sub"
        sub.mkdir(parents=True)
        stale = sub / "gone.mkv"
        stale.symlink_to(tmp_path / "nonexistent")

        mgr = SymlinkManager()
        with caplog.at_level(logging.INFO, logger="boomarr.symlinks"):
            mgr.clean_stale(out)

        assert any("gone.mkv" in record.message for record in caplog.records)
        assert any(record.levelno == logging.INFO for record in caplog.records)

    @_skip_no_symlink
    def test_clean_stale_nonexistent_output_dir(self, tmp_path: Path) -> None:
        """clean_stale on a missing directory must return 0 without error."""
        mgr = SymlinkManager()
        assert mgr.clean_stale(tmp_path / "does_not_exist") == 0

    @_skip_no_symlink
    def test_clean_stale_multiple_dangling_links(self, tmp_path: Path) -> None:
        """Multiple dangling symlinks across sibling dirs are all removed."""
        out = tmp_path / "output"
        for season in ("Season 1", "Season 2"):
            (out / season).mkdir(parents=True)
            (out / season / "ep.mkv").symlink_to(tmp_path / "missing")

        mgr = SymlinkManager()
        assert mgr.clean_stale(out) == 2
        assert not (out / "Season 1").exists()
        assert not (out / "Season 2").exists()


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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        assert library.output_path is not None
        expected = library.output_path / "t-de"
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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        assert library.output_path is not None
        expected = library.output_path / "german"
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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
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
    """End-to-end processor behaviour on a real temporary filesystem."""

    @staticmethod
    def _info(path: Path, *langs: str) -> MediaInfo:
        return MediaInfo(
            file_path=path,
            audio_tracks=[
                AudioTrack(index=i, language=lang, codec="aac")
                for i, lang in enumerate(langs)
            ],
        )

    @staticmethod
    def _run(
        library: LibraryConfig,
        prober: MediaProber,
        sym_libs: list[ResolvedSymlinkLibrary],
        **kwargs: object,
    ) -> ScanResult:
        pipeline = Pipeline(probers=[prober], symlink_libraries=sym_libs, **kwargs)  # type: ignore[arg-type]
        return LibraryProcessor(pipeline).process_library(library)

    def test_nonexistent_input_is_skipped_with_error(self, tmp_path: Path) -> None:
        library = LibraryConfig(
            name="Ghost",
            input_path=tmp_path / "nonexistent",
            output_path=tmp_path / "output",
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
                    ],
                ),
            ],
        )
        result = self._run(library, StubProber({}), [_resolved_sym_lib(tmp_path / "o")])
        assert result.errors == 1
        assert result.created == result.removed == 0

    def test_missing_input_keeps_existing_links(self, tmp_path: Path) -> None:
        """An unmounted share must never wipe the filtered library."""
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()
        prober = StubProber({str(media): self._info(media, "de")})
        self._run(library, prober, [_resolved_sym_lib(out)])
        assert (out / "movie.mkv").is_symlink()

        media.unlink()
        library.input_path.rmdir()
        result = self._run(library, prober, [_resolved_sym_lib(out)])
        assert result.errors == 1
        assert (out / "movie.mkv").is_symlink()

    def test_empty_input_keeps_existing_links(self, tmp_path: Path) -> None:
        """An empty mount point (share not mounted) is treated like a missing one."""
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()
        prober = StubProber({str(media): self._info(media, "de")})
        self._run(library, prober, [_resolved_sym_lib(out)])

        media.unlink()
        result = self._run(library, prober, [_resolved_sym_lib(out)])
        assert result.errors == 1
        assert result.removed == 0
        assert (out / "movie.mkv").is_symlink()

    def test_empty_input_without_links_is_fine(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        result = self._run(library, StubProber({}), [_resolved_sym_lib(tmp_path / "o")])
        assert result.errors == 0

    def test_probe_returns_none_counts_as_error(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        media = library.input_path / "bad.mkv"
        media.touch()
        result = self._run(
            library, StubProber({str(media): None}), [_resolved_sym_lib(tmp_path / "o")]
        )
        assert result.errors == 1
        assert result.total == 1

    def test_failed_probe_preserves_existing_link(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.write_text("v1")
        self._run(
            library,
            StubProber({str(media): self._info(media, "de")}),
            [_resolved_sym_lib(out)],
        )
        media.write_text("v2 - changed so it must be probed again")
        result = self._run(
            library, StubProber({str(media): None}), [_resolved_sym_lib(out)]
        )
        assert result.errors == 1
        assert result.removed == 0
        assert (out / "movie.mkv").is_symlink()

    def test_cached_files_are_not_probed_again(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()
        prober = MagicMock(spec=MediaProber)
        prober.probe.return_value = self._info(media, "de")
        state = InMemoryStateStore()

        first = self._run(library, prober, [_resolved_sym_lib(out)], state=state)
        second = self._run(library, prober, [_resolved_sym_lib(out)], state=state)

        assert prober.probe.call_count == 1
        assert first.probed == 1 and first.created == 1
        assert second.skipped == 1 and second.unchanged == 1 and second.created == 0

    def test_changed_file_is_probed_again(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.write_text("a")
        prober = MagicMock(spec=MediaProber)
        prober.probe.return_value = self._info(media, "de")
        state = InMemoryStateStore()
        self._run(library, prober, [_resolved_sym_lib(out)], state=state)
        media.write_text("changed")
        result = self._run(library, prober, [_resolved_sym_lib(out)], state=state)
        assert prober.probe.call_count == 2
        assert result.probed == 1 and result.skipped == 0

    def test_new_symlink_library_is_populated_from_cache(self, tmp_path: Path) -> None:
        """Regression: adding a symlink library later must fill it on next scan."""
        library = _make_library(tmp_path)
        out_de, out_en = tmp_path / "output-de", tmp_path / "output-en"
        media = library.input_path / "movie.mkv"
        media.touch()
        prober = MagicMock(spec=MediaProber)
        prober.probe.return_value = self._info(media, "de", "en")
        state = InMemoryStateStore()

        self._run(library, prober, [_resolved_sym_lib(out_de, ["de"])], state=state)
        result = self._run(
            library,
            prober,
            [_resolved_sym_lib(out_de, ["de"]), _resolved_sym_lib(out_en, ["en"])],
            state=state,
        )
        assert prober.probe.call_count == 1
        assert result.created == 1
        assert (out_en / "movie.mkv").is_symlink()

    def test_changed_filter_removes_links_without_reprobe(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output"
        media = library.input_path / "movie.mkv"
        media.touch()
        prober = MagicMock(spec=MediaProber)
        prober.probe.return_value = self._info(media, "de")
        state = InMemoryStateStore()
        self._run(library, prober, [_resolved_sym_lib(out, ["de"])], state=state)
        result = self._run(
            library, prober, [_resolved_sym_lib(out, ["fr"])], state=state
        )
        assert prober.probe.call_count == 1
        assert result.removed == 1
        assert not (out / "movie.mkv").exists()

    def test_manually_deleted_link_is_recreated(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()
        prober = StubProber({str(media): self._info(media, "de")})
        state = InMemoryStateStore()
        self._run(library, prober, [_resolved_sym_lib(out)], state=state)
        (out / "movie.mkv").unlink()
        result = self._run(library, prober, [_resolved_sym_lib(out)], state=state)
        assert result.created == 1
        assert (out / "movie.mkv").is_symlink()

    def test_deleted_source_link_removed_and_cache_pruned(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        keep = library.input_path / "keep.mkv"
        gone = library.input_path / "gone.mkv"
        keep.touch()
        gone.touch()
        prober = StubProber(
            {str(keep): self._info(keep, "de"), str(gone): self._info(gone, "de")}
        )
        state = InMemoryStateStore()
        self._run(library, prober, [_resolved_sym_lib(out)], state=state)
        gone.unlink()
        result = self._run(library, prober, [_resolved_sym_lib(out)], state=state)
        assert result.removed == 1
        assert not (out / "gone.mkv").is_symlink()
        assert state.get_stats()["total_cached"] == 1

    def test_foreign_symlinks_and_regular_files_untouched(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        out.mkdir()
        elsewhere = tmp_path / "elsewhere.mkv"
        elsewhere.touch()
        (out / "foreign.mkv").symlink_to(elsewhere)
        (out / "notes.txt").write_text("mine")
        media = library.input_path / "movie.mkv"
        media.touch()
        self._run(
            library,
            StubProber({str(media): self._info(media, "en")}),
            [_resolved_sym_lib(out)],
        )
        assert (out / "foreign.mkv").is_symlink()
        assert (out / "notes.txt").read_text() == "mine"

    def test_exception_during_probe_counts_as_error(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        media = library.input_path / "movie.mkv"
        media.touch()
        prober = MagicMock(spec=MediaProber)
        prober.probe.side_effect = RuntimeError("boom")
        result = self._run(library, prober, [_resolved_sym_lib(tmp_path / "o")])
        assert result.errors == 1

    def test_multiple_files_mixed_results(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        good = library.input_path / "good.mkv"
        bad = library.input_path / "bad.mkv"
        good.touch()
        bad.touch()
        prober = StubProber({str(good): self._info(good, "de"), str(bad): None})
        result = self._run(library, prober, [_resolved_sym_lib(tmp_path / "o")])
        assert result.created == 1
        assert result.errors == 1
        assert result.probed == 1

    def test_dest_path_mirrors_input_structure(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        subdir = library.input_path / "subdir"
        subdir.mkdir()
        media = subdir / "movie.mkv"
        media.touch()
        self._run(
            library,
            StubProber({str(media): self._info(media, "de")}),
            [_resolved_sym_lib(out)],
        )
        link = out / "subdir" / "movie.mkv"
        assert link.is_symlink()
        assert link.readlink() == media

    def test_pre_probe_filter_skips_non_media(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        media = library.input_path / "movie.txt"
        media.touch()
        prober = MagicMock(spec=MediaProber)
        result = self._run(
            library,
            prober,
            [_resolved_sym_lib(tmp_path / "o")],
            pre_probe_filters=[FileExtensionFilter()],
        )
        assert result.filtered == 1
        assert result.created == 0
        prober.probe.assert_not_called()

    def test_state_updated_after_processing(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        media = library.input_path / "movie.mkv"
        media.touch()
        stat = media.stat()
        state = InMemoryStateStore()
        self._run(
            library,
            StubProber({str(media): self._info(media, "de")}),
            [_resolved_sym_lib(tmp_path / "o")],
            state=state,
        )
        cached = state.get(media, stat.st_size, stat.st_mtime)
        assert cached is not None
        assert cached.audio_tracks[0].language == "de"

    def test_clean_library_delegates_to_symlink_manager(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        (library.input_path / "movie.mkv").touch()
        output_de = tmp_path / "output-de"
        symlinks = MagicMock(spec=SymlinkManager)
        symlinks.clean_stale.return_value = 3
        pipeline = Pipeline(
            probers=[StubProber({})],
            symlinks=symlinks,
            symlink_libraries=[_resolved_sym_lib(output_de)],
        )
        assert LibraryProcessor(pipeline).clean_library(library) == 3
        symlinks.clean_stale.assert_called_once_with(output_de)

    def test_clean_library_skips_unmounted_input(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        out.mkdir()
        (out / "movie.mkv").symlink_to(library.input_path / "movie.mkv")  # broken
        pipeline = Pipeline(
            probers=[StubProber({})], symlink_libraries=[_resolved_sym_lib(out)]
        )
        assert LibraryProcessor(pipeline).clean_library(library) == 0
        assert (out / "movie.mkv").is_symlink()

    def test_prober_fallback_chain(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        media = library.input_path / "movie.mkv"
        media.touch()
        pipeline = Pipeline(
            probers=[StubProber({}), StubProber({str(media): self._info(media, "de")})],
            symlink_libraries=[_resolved_sym_lib(tmp_path / "o")],
        )
        assert LibraryProcessor(pipeline).process_library(library).created == 1

    def test_multiple_symlink_libraries(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        media = library.input_path / "movie.mkv"
        media.touch()
        result = self._run(
            library,
            StubProber({str(media): self._info(media, "de", "en")}),
            [
                _resolved_sym_lib(tmp_path / "output-de", ["de"]),
                _resolved_sym_lib(tmp_path / "output-en", ["en"]),
            ],
        )
        assert result.created == 2

    def test_sidecar_subtitles_follow_media(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "Movie.mkv"
        media.touch()
        for name in ["Movie.de.srt", "Movie.en.forced.ass", "Other.srt", "Movie.nfo"]:
            (library.input_path / name).touch()
        prober = StubProber({str(media): self._info(media, "de")})
        state = InMemoryStateStore()
        self._run(
            library,
            prober,
            [_resolved_sym_lib(out)],
            state=state,
            pre_probe_filters=[FileExtensionFilter()],
        )
        assert sorted(p.name for p in out.iterdir()) == [
            "Movie.de.srt",
            "Movie.en.forced.ass",
            "Movie.mkv",
        ]
        # Sidecars are removed together with the media link.
        result = self._run(
            library,
            prober,
            [_resolved_sym_lib(out, ["fr"])],
            state=state,
            pre_probe_filters=[FileExtensionFilter()],
        )
        assert result.removed == 3

    def test_sidecars_can_be_disabled(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "Movie.mkv"
        media.touch()
        (library.input_path / "Movie.de.srt").touch()
        self._run(
            library,
            StubProber({str(media): self._info(media, "de")}),
            [_resolved_sym_lib(out)],
            pre_probe_filters=[FileExtensionFilter()],
            sidecar_extensions=frozenset(),
        )
        assert [p.name for p in out.iterdir()] == ["Movie.mkv"]

    def test_ignore_patterns(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()
        junk_dir = library.input_path / "@eaDir"
        junk_dir.mkdir()
        (junk_dir / "thumb.mkv").touch()
        (library.input_path / "._movie.mkv").touch()
        prober = MagicMock(spec=MediaProber)
        prober.probe.return_value = self._info(media, "de")
        self._run(library, prober, [_resolved_sym_lib(out)])
        assert prober.probe.call_count == 1
        assert [p.name for p in out.iterdir()] == ["movie.mkv"]

    def test_relative_symlinks(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "sub" / "movie.mkv"
        media.parent.mkdir()
        media.touch()
        self._run(
            library,
            StubProber({str(media): self._info(media, "de")}),
            [_resolved_sym_lib(out)],
            relative_symlinks=True,
        )
        link = out / "sub" / "movie.mkv"
        assert not link.readlink().is_absolute()
        assert link.resolve() == media.resolve()

    def test_dry_run_changes_nothing(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()
        result = self._run(
            library,
            StubProber({str(media): self._info(media, "de")}),
            [_resolved_sym_lib(out)],
            symlinks=SymlinkManager(dry_run=True),
        )
        assert result.created == 1
        assert not out.exists()

    def test_cancelled_scan_changes_nothing(self, tmp_path: Path) -> None:
        import threading

        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        media = library.input_path / "movie.mkv"
        media.touch()
        cancel = threading.Event()
        cancel.set()
        pipeline = Pipeline(
            probers=[StubProber({str(media): self._info(media, "de")})],
            symlink_libraries=[_resolved_sym_lib(out)],
        )
        result = LibraryProcessor(pipeline, cancel=cancel).process_library(library)
        assert result.created == 0
        assert not out.exists()

    def test_parallel_probing(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        files = [library.input_path / f"m{i}.mkv" for i in range(20)]
        for f in files:
            f.touch()
        prober = StubProber({str(f): self._info(f, "de") for f in files})
        result = self._run(library, prober, [_resolved_sym_lib(out)], probe_workers=8)
        assert result.created == 20
        assert result.probed == 20


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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
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
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
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

    def test_global_output_path_auto_naming(self) -> None:
        """With global output_path and no library output_path, dir name includes library slug."""
        config = Config(
            config_dir=Path("."),
            config_file="test.yml",
            general=GeneralConfig(),
            logging=LoggingConfig(),
            output_path=Path("/filtered"),
            libraries=[],
        )
        library = LibraryConfig(
            name="Dev Movies",
            input_path=Path("/a"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        expected = Path("/filtered").resolve() / "dev-movies-de"
        assert pipeline.symlink_libraries[0].output_path == expected

    def test_library_output_overrides_global(self) -> None:
        """Per-library output_path takes precedence over global."""
        config = Config(
            config_dir=Path("."),
            config_file="test.yml",
            general=GeneralConfig(),
            logging=LoggingConfig(),
            output_path=Path("/global"),
            libraries=[],
        )
        library = LibraryConfig(
            name="Movies",
            input_path=Path("/a"),
            output_path=Path("/per-library"),
            symlink_libraries=[
                SymlinkLibraryConfig(
                    filters=[
                        AudioLanguageFilterConfig(languages=[LanguageEntry(code="de")]),
                    ],
                ),
            ],
        )
        factory = PipelineFactory()
        pipeline = factory.for_scan(config, library)
        expected = Path("/per-library").resolve() / "movies-de"
        assert pipeline.symlink_libraries[0].output_path == expected


class TestRemovalGuard:
    @staticmethod
    def _setup(tmp_path: Path, count: int) -> tuple[LibraryConfig, Path, list[Path]]:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        files = [library.input_path / f"m{i}.mkv" for i in range(count)]
        for f in files:
            f.touch()
        return library, out, files

    @staticmethod
    def _prober(files: list[Path], lang: str) -> StubProber:
        return StubProber(
            {
                str(f): MediaInfo(f, [AudioTrack(index=0, language=lang, codec="aac")])
                for f in files
            }
        )

    def _run(
        self, library: LibraryConfig, out: Path, prober: StubProber, **kwargs: object
    ) -> ScanResult:
        from boomarr.models import RemovalGuard

        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(out)],
            removal_guard=RemovalGuard(max_percent=50, min_count=5),
            **kwargs,  # type: ignore[arg-type]
        )
        return LibraryProcessor(pipeline).process_library(library)

    def test_mass_removal_is_blocked(self, tmp_path: Path) -> None:
        library, out, files = self._setup(tmp_path, 10)
        self._run(library, out, self._prober(files, "de"))
        result = self._run(library, out, self._prober(files, "en"))
        assert result.blocked == 1
        assert result.removed == 0
        assert len(list(out.iterdir())) == 10

    def test_force_bypasses_guard(self, tmp_path: Path) -> None:
        library, out, files = self._setup(tmp_path, 10)
        self._run(library, out, self._prober(files, "de"))
        result = self._run(library, out, self._prober(files, "en"), force=True)
        assert result.blocked == 0
        assert result.removed == 10

    def test_small_removals_are_allowed(self, tmp_path: Path) -> None:
        library, out, files = self._setup(tmp_path, 4)
        self._run(library, out, self._prober(files, "de"))
        result = self._run(library, out, self._prober(files, "en"))
        assert result.removed == 4

    def test_guard_model(self) -> None:
        from boomarr.models import RemovalGuard

        guard = RemovalGuard(max_percent=50, min_count=20)
        assert not guard.blocks(20, 21)
        assert guard.blocks(21, 40)
        assert not guard.blocks(21, 100)
        assert not guard.blocks(0, 0)

    def test_config_disable(self) -> None:
        from boomarr.config import RemovalGuardConfig

        assert RemovalGuardConfig(max_percent=100).to_model() is None
        assert RemovalGuardConfig().to_model() is not None
