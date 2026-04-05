"""Tests for the source directory read-only safety check."""

from pathlib import Path
from unittest.mock import patch

import pytest

from boomarr.__main__ import verify_source_dirs_readonly
from boomarr.config import LibraryConfig


def _make_library(input_path: Path, output_path: Path) -> LibraryConfig:
    return LibraryConfig(
        name="Test",
        input_path=input_path,
        output_path=output_path,
        languages=["de"],
    )


class TestVerifySourceDirsReadonly:
    """Tests for verify_source_dirs_readonly."""

    def test_readonly_dir_passes(self, tmp_path: Path) -> None:
        """A non-writable source directory should pass without error."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        library = _make_library(input_dir, output_dir)

        with patch("os.access", return_value=False):
            # Should not raise or exit
            verify_source_dirs_readonly([library])

    def test_writable_dir_exits(self, tmp_path: Path) -> None:
        """A writable source directory must cause a critical exit."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        library = _make_library(input_dir, output_dir)

        with pytest.raises(SystemExit) as exc_info:
            verify_source_dirs_readonly([library])

        assert exc_info.value.code == 1

    def test_nonexistent_dir_skipped(self, tmp_path: Path) -> None:
        """A source directory that does not exist should be silently skipped."""
        input_dir = tmp_path / "nonexistent"
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        library = _make_library(input_dir, output_dir)

        # Should not raise or exit
        verify_source_dirs_readonly([library])

    def test_multiple_libraries_first_writable(self, tmp_path: Path) -> None:
        """If any source directory is writable, exit immediately."""
        input1 = tmp_path / "input1"
        input2 = tmp_path / "input2"
        output = tmp_path / "output"
        input1.mkdir()
        input2.mkdir()
        output.mkdir()

        lib1 = _make_library(input1, output)
        lib2 = _make_library(input2, output)

        # First library writable, second not
        def access_side_effect(path: object, mode: int) -> bool:
            return str(path) == str(input1)

        with patch("boomarr.__main__.os.access", side_effect=access_side_effect):
            with pytest.raises(SystemExit) as exc_info:
                verify_source_dirs_readonly([lib1, lib2])
            assert exc_info.value.code == 1

    def test_multiple_libraries_all_readonly(self, tmp_path: Path) -> None:
        """All non-writable directories should pass."""
        input1 = tmp_path / "input1"
        input2 = tmp_path / "input2"
        output = tmp_path / "output"
        input1.mkdir()
        input2.mkdir()
        output.mkdir()

        lib1 = _make_library(input1, output)
        lib2 = _make_library(input2, output)

        with patch("boomarr.__main__.os.access", return_value=False):
            verify_source_dirs_readonly([lib1, lib2])

    def test_empty_libraries_list(self) -> None:
        """An empty library list should be a no-op."""
        verify_source_dirs_readonly([])

    def test_skip_true_bypasses_writable_check(self, tmp_path: Path) -> None:
        """skip=True should bypass the check even if the directory is writable."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        library = _make_library(input_dir, output_dir)

        # Directory IS writable, but skip=True — should not exit
        verify_source_dirs_readonly([library], skip=True)

    def test_skip_false_still_enforces_check(self, tmp_path: Path) -> None:
        """skip=False (the default) should still enforce the check."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir()
        output_dir.mkdir()
        library = _make_library(input_dir, output_dir)

        with pytest.raises(SystemExit) as exc_info:
            verify_source_dirs_readonly([library], skip=False)
        assert exc_info.value.code == 1
