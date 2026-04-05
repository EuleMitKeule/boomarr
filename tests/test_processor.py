"""Tests for the processor and pipeline subsystems."""

import sys
from pathlib import Path

import pytest

from boomarr.config import LibraryConfig
from boomarr.filters.audio_language import AudioLanguageFilter
from boomarr.filters.file_extension import FileExtensionFilter
from boomarr.models import AudioTrack, MediaInfo, ScanResult
from boomarr.pipeline import Pipeline, PipelineFactory
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
        languages=["de"],
    )


class TestFileExtensionFilter:
    def test_mkv_passes(self) -> None:
        f = FileExtensionFilter()
        info = MediaInfo(file_path=Path("/media/movie.mkv"))
        lib = LibraryConfig(
            name="T", input_path=Path("/a"), output_path=Path("/b"), languages=["en"]
        )
        assert f.matches(info, lib) is True

    def test_txt_rejected(self) -> None:
        f = FileExtensionFilter()
        info = MediaInfo(file_path=Path("/media/readme.txt"))
        lib = LibraryConfig(
            name="T", input_path=Path("/a"), output_path=Path("/b"), languages=["en"]
        )
        assert f.matches(info, lib) is False

    def test_custom_extensions(self) -> None:
        f = FileExtensionFilter(extensions=frozenset({".custom"}))
        info = MediaInfo(file_path=Path("/media/file.custom"))
        lib = LibraryConfig(
            name="T", input_path=Path("/a"), output_path=Path("/b"), languages=["en"]
        )
        assert f.matches(info, lib) is True


class TestAudioLanguageFilter:
    def test_matching_language(self) -> None:
        f = AudioLanguageFilter()
        info = MediaInfo(
            file_path=Path("/m.mkv"),
            audio_tracks=[AudioTrack(index=0, language="de", codec="aac")],
        )
        lib = LibraryConfig(
            name="T", input_path=Path("/a"), output_path=Path("/b"), languages=["de"]
        )
        assert f.matches(info, lib) is True

    def test_no_matching_language(self) -> None:
        f = AudioLanguageFilter()
        info = MediaInfo(
            file_path=Path("/m.mkv"),
            audio_tracks=[AudioTrack(index=0, language="en", codec="aac")],
        )
        lib = LibraryConfig(
            name="T", input_path=Path("/a"), output_path=Path("/b"), languages=["de"]
        )
        assert f.matches(info, lib) is False

    def test_no_tracks_rejected(self) -> None:
        f = AudioLanguageFilter()
        info = MediaInfo(file_path=Path("/m.mkv"), audio_tracks=[])
        lib = LibraryConfig(
            name="T", input_path=Path("/a"), output_path=Path("/b"), languages=["de"]
        )
        assert f.matches(info, lib) is False


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
    def test_for_scan_has_filters(self) -> None:
        factory = PipelineFactory()
        pipeline = factory.for_scan()
        assert len(pipeline.filters) == 2
        assert isinstance(pipeline.filters[0], FileExtensionFilter)
        assert isinstance(pipeline.filters[1], AudioLanguageFilter)

    def test_for_clean_has_no_filters(self) -> None:
        factory = PipelineFactory()
        pipeline = factory.for_clean()
        assert len(pipeline.filters) == 0


class TestLibraryProcessor:
    def test_process_empty_input(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        pipeline = Pipeline(
            prober=StubProber({}),
            filters=[],
            symlinks=SymlinkManager(),
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.total == 0

    @_skip_no_symlink
    def test_process_creates_symlink(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        # Create a test media file
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
            prober=prober,
            filters=[AudioLanguageFilter()],
            symlinks=SymlinkManager(),
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.created == 1
        assert (library.output_path / "movie.mkv").is_symlink()

    @_skip_no_symlink
    def test_process_skips_non_matching(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
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
            prober=prober,
            filters=[AudioLanguageFilter()],
            symlinks=SymlinkManager(),
            state=InMemoryStateStore(),
        )
        processor = LibraryProcessor(pipeline)
        result = processor.process_library(library)
        assert result.created == 0
        assert not (library.output_path / "movie.mkv").exists()
