"""Tests for the remaining CLI commands (version, clean, watch, status...)."""

import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from boomarr import __main__ as cli
from boomarr.__main__ import app

runner = CliRunner()


def _run(*args: str) -> Any:
    return runner.invoke(app, [*args, "--log-dir", ""])


class TestSmallCommands:
    def test_version(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert result.output.startswith("Boomarr version")

    def test_main(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[bool] = []
        monkeypatch.setattr(cli, "app", lambda: called.append(True))
        cli.main()
        assert called == [True]

    def test_heartbeat_default_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HEARTBEAT_FILE", raising=False)
        assert cli._heartbeat_file().name == "boomarr.heartbeat"

    def test_scan_without_libraries(self, tmp_path: Path) -> None:
        (tmp_path / "boomarr.yml").write_text("unknown_option: 1\n")
        result = _run("scan", "--config-dir", str(tmp_path), "--log-level", "DEBUG")
        assert result.exit_code == 0

    def test_clean_without_libraries(self, tmp_path: Path) -> None:
        (tmp_path / "boomarr.yml").write_text("")
        assert _run("clean", "--config-dir", str(tmp_path)).exit_code == 0

    def test_clean_removes_stale_links(self, config_dir: Path, tmp_path: Path) -> None:
        output = tmp_path / "out" / "movies-deu"
        output.mkdir(parents=True)
        (output / "gone.mkv").symlink_to(tmp_path / "media" / "movies" / "missing.mkv")
        result = _run(
            "clean", "--config-dir", str(config_dir), "--dangerous-skip-readonly-check"
        )
        assert result.exit_code == 0
        assert not list(output.iterdir())

    def test_status_rich(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli.Console, "is_terminal", property(lambda self: True))
        result = _run("status", "--config-dir", str(config_dir))
        assert result.exit_code == 0
        assert "Libraries" in result.output

    def test_paths_deduplicated_and_memory_db(self, config_dir: Path) -> None:
        result = runner.invoke(
            app,
            ["paths", "--config-dir", str(config_dir), "--log-dir", str(config_dir)],
        )
        assert result.output.splitlines().count(str(config_dir)) == 1
        path = config_dir / "boomarr.yml"
        path.write_text(path.read_text() + "database:\n  type: memory\n")
        result = runner.invoke(
            app, ["paths", "--config-dir", str(config_dir), "--log-dir", ""]
        )
        assert str(config_dir) not in result.output.splitlines()

    def test_paths_with_log_file(self, config_dir: Path, tmp_path: Path) -> None:
        result = runner.invoke(
            app,
            [
                "paths",
                "--config-dir",
                str(config_dir),
                "--log-dir",
                str(tmp_path / "logs"),
            ],
        )
        assert str(tmp_path / "logs") in result.output.splitlines()


class TestWatchCommand:
    def test_invalid_config(self, tmp_path: Path) -> None:
        (tmp_path / "boomarr.yml").write_text("probe_workers: 0\n")
        result = _run("watch", "--config-dir", str(tmp_path))
        assert result.exit_code == 1
        assert "Invalid configuration" in result.output

    def test_without_server_and_libraries(self, tmp_path: Path) -> None:
        (tmp_path / "boomarr.yml").write_text("server:\n  enabled: false\n")
        assert _run("watch", "--config-dir", str(tmp_path)).exit_code == 0

    def test_without_server_and_triggers(self, config_dir: Path) -> None:
        path = config_dir / "boomarr.yml"
        path.write_text(path.read_text() + "server:\n  enabled: false\n")
        result = _run(
            "watch", "--config-dir", str(config_dir), "--dangerous-skip-readonly-check"
        )
        assert result.exit_code == 0

    def test_without_server_checks_sources(self, config_dir: Path) -> None:
        path = config_dir / "boomarr.yml"
        path.write_text(path.read_text() + "server:\n  enabled: false\n")
        assert _run("watch", "--config-dir", str(config_dir)).exit_code == 1

    @pytest.mark.parametrize("server", [True, False])
    def test_starts_daemon(
        self,
        config_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        server: bool,
    ) -> None:
        path = config_dir / "boomarr.yml"
        text = path.read_text().replace("triggers: []\n", "") + "unknown_option: 1\n"
        if not server:
            text += "server:\n  enabled: false\n"
        path.write_text(text)
        started: list[Any] = []
        monkeypatch.setattr(cli.Daemon, "run", lambda self: started.append(self))
        monkeypatch.setenv("HEARTBEAT_FILE", str(config_dir / "hb"))
        result = _run(
            "watch", "--config-dir", str(config_dir), "--dangerous-skip-readonly-check"
        )
        assert result.exit_code == 0
        assert started and started[0].skip_readonly_check is True
        started[0].state.close()
        assert ("Setup token" in result.output) is server
        assert (config_dir / "auth.json").exists()

    def test_env_credentials(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BOOMARR_USERNAME", "admin")
        monkeypatch.setenv("BOOMARR_PASSWORD", "password1")
        started: list[Any] = []
        monkeypatch.setattr(cli.Daemon, "run", lambda self: started.append(self))
        result = _run(
            "watch", "--config-dir", str(config_dir), "--dangerous-skip-readonly-check"
        )
        assert result.exit_code == 0
        assert started[0].auth.has_credentials
        started[0].state.close()
        assert "Setup token" not in result.output
        assert os.path.exists(config_dir / "auth.json")
