"""End-to-end tests with the real ffprobe binary and committed fixture media.

Skipped automatically when ffprobe is not installed.
"""

import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from boomarr.__main__ import app
from tests.fixtures import MOVIES_DIR, SHOWS_DIR

pytestmark = pytest.mark.skipif(
    shutil.which("ffprobe") is None, reason="ffprobe not installed"
)

runner = CliRunner()


def _scan(config_dir: Path, *extra: str) -> None:
    result = runner.invoke(
        app,
        [
            "scan",
            "--config-dir",
            str(config_dir),
            "--dangerous-skip-readonly-check",
            "--log-dir",
            "",
            *extra,
        ],
    )
    assert result.exit_code == 0, result.output


def _links(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_symlink()}


def test_full_scan_with_real_ffprobe(tmp_path: Path) -> None:
    media = tmp_path / "media"
    shutil.copytree(MOVIES_DIR, media / "movies")
    shutil.copytree(SHOWS_DIR, media / "shows")
    output = tmp_path / "filtered"
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    config = {
        "output_path": str(output),
        "libraries": [
            {
                "name": "Movies",
                "input_path": str(media / "movies"),
                "symlink_libraries": [
                    {"filters": [{"type": "audio_language", "languages": ["ger"]}]},
                    {
                        "name": "Bilingual",
                        "filters": [
                            {
                                "type": "audio_language",
                                "languages": ["de", "en"],
                                "mode": "all",
                            }
                        ],
                    },
                ],
            },
            {
                "name": "Shows",
                "input_path": str(media / "shows"),
                "symlink_libraries": [
                    {"filters": [{"type": "audio_language", "languages": ["eng"]}]}
                ],
            },
        ],
    }
    (config_dir / "boomarr.yml").write_text(yaml.dump(config), encoding="utf-8")

    _scan(config_dir)

    assert _links(output / "movies-ger") == {
        "Sample.Movie.DE.mkv",
        "Sample.Movie.DE.EN.mkv",
        "Sample.Movie.DE.EN.FR.mkv",
        "Movie.In.Folder/Movie.In.Folder.DE.EN.mkv",
        "Collection/Sequel/Sequel.Movie.DE.mkv",
        "Collection/Sequel/Sequel.Movie.DE.srt",
    }
    assert _links(output / "Bilingual") == {
        "Sample.Movie.DE.EN.mkv",
        "Sample.Movie.DE.EN.FR.mkv",
        "Movie.In.Folder/Movie.In.Folder.DE.EN.mkv",
    }
    assert _links(output / "shows-eng") == {
        "Sample.Show/Season 1/S01E02.EN.mkv",
        "Sample.Show/Season 1/S01E03.DE.EN.mkv",
        "Sample.Show/Season 2/S02E01.DE.EN.mkv",
        "Sample.Show/Season 2/S02E02.EN.mkv",
        "Another.Show/Season 1/S01E01.DE.EN.FR.mkv",
    }
    assert (config_dir / "boomarr.db").exists()

    # Deleting a source file removes its link on the next (cached) scan.
    (media / "movies" / "Sample.Movie.DE.mkv").unlink()
    _scan(config_dir)
    assert "Sample.Movie.DE.mkv" not in _links(output / "movies-ger")
