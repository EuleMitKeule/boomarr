"""Tests for the ``boomarr paths`` CLI command."""

from pathlib import Path

import yaml
from typer.testing import CliRunner

from boomarr.__main__ import app

runner = CliRunner()


def _write_config(tmp_path: Path, data: dict[str, object]) -> None:
    (tmp_path / "boomarr.yml").write_text(yaml.dump(data), encoding="utf-8")


class TestPathsCommand:
    def test_global_output_path_printed(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            {
                "output_path": "/media/filtered",
                "libraries": [
                    {
                        "name": "Movies",
                        "input_path": "/media/movies",
                        "symlink_libraries": [
                            {
                                "filters": [
                                    {"type": "audio_language", "languages": ["de"]}
                                ]
                            }
                        ],
                    }
                ],
            },
        )
        result = runner.invoke(
            app, ["paths", "--config-dir", str(tmp_path)], catch_exceptions=False
        )
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        # Must include the resolved symlink library output path under the global base
        assert any("movies-de" in line or "filtered" in line for line in lines)

    def test_per_library_output_path_printed(self, tmp_path: Path) -> None:
        _write_config(
            tmp_path,
            {
                "libraries": [
                    {
                        "name": "Movies",
                        "input_path": "/media/movies",
                        "output_path": "/media/filtered/movies",
                        "symlink_libraries": [
                            {
                                "filters": [
                                    {"type": "audio_language", "languages": ["de"]}
                                ]
                            }
                        ],
                    }
                ],
            },
        )
        result = runner.invoke(
            app, ["paths", "--config-dir", str(tmp_path)], catch_exceptions=False
        )
        assert result.exit_code == 0
        lines = result.output.strip().splitlines()
        assert any("movies" in line.lower() for line in lines)

    def test_log_dir_printed(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        _write_config(tmp_path, {})
        result = runner.invoke(
            app,
            [
                "paths",
                "--config-dir",
                str(tmp_path),
                "--log-dir",
                str(log_dir),
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert str(log_dir) in result.output

    def test_no_libraries_only_log_dir(self, tmp_path: Path) -> None:
        log_dir = tmp_path / "logs"
        _write_config(tmp_path, {})
        result = runner.invoke(
            app,
            [
                "paths",
                "--config-dir",
                str(tmp_path),
                "--log-dir",
                str(log_dir),
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        lines = [line for line in result.output.strip().splitlines() if line]
        assert lines == [str(log_dir)]

    def test_no_duplicate_paths(self, tmp_path: Path) -> None:
        """Two symlink libraries with the same resolved path should appear once."""
        _write_config(
            tmp_path,
            {
                "libraries": [
                    {
                        "name": "Movies",
                        "input_path": "/media/movies",
                        "output_path": "/media/filtered/movies",
                        "symlink_libraries": [
                            {
                                "output_path": "/media/filtered/movies/de",
                                "filters": [
                                    {"type": "audio_language", "languages": ["de"]}
                                ],
                            },
                            {
                                "output_path": "/media/filtered/movies/de",
                                "filters": [
                                    {"type": "audio_language", "languages": ["de"]}
                                ],
                            },
                        ],
                    }
                ],
            },
        )
        result = runner.invoke(
            app, ["paths", "--config-dir", str(tmp_path)], catch_exceptions=False
        )
        assert result.exit_code == 0
        lines = [line for line in result.output.strip().splitlines() if line]
        assert len(lines) == len(set(lines))

    def test_each_path_on_own_line(self, tmp_path: Path) -> None:
        """Output must be newline-separated (suitable for shell `read`)."""
        log_dir = tmp_path / "logs"
        _write_config(
            tmp_path,
            {
                "libraries": [
                    {
                        "name": "Movies",
                        "input_path": "/media/movies",
                        "output_path": "/media/filtered/movies",
                        "symlink_libraries": [
                            {
                                "filters": [
                                    {"type": "audio_language", "languages": ["de"]}
                                ]
                            }
                        ],
                    }
                ],
            },
        )
        result = runner.invoke(
            app,
            ["paths", "--config-dir", str(tmp_path), "--log-dir", str(log_dir)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        lines = [line for line in result.output.strip().splitlines() if line]
        assert len(lines) >= 2  # at least log dir + one output path
