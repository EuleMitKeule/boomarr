"""Tests for CLI commands, watcher resilience and low-level helpers."""

import asyncio
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from boomarr.__main__ import app
from boomarr.models import AudioTrack, MediaInfo, ScanResult
from boomarr.probers.ffprobe import FFProbeProber
from boomarr.symlinks import SymlinkManager, link_target
from boomarr.watcher import Watcher

runner = CliRunner()


def _write_config(config_dir: Path, media: Path, output: Path) -> None:
    data = {
        "output_path": str(output),
        "database": {"type": "memory"},
        "libraries": [
            {
                "name": "Movies",
                "input_path": str(media),
                "symlink_libraries": [
                    {
                        "name": "German",
                        "filters": [{"type": "audio_language", "languages": ["deu"]}],
                    }
                ],
            }
        ],
    }
    (config_dir / "boomarr.yml").write_text(yaml.dump(data), encoding="utf-8")


def _fake_probe(self: FFProbeProber, file: Path) -> MediaInfo:
    lang = "ger" if ".DE." in file.name else "eng"
    return MediaInfo(file, [AudioTrack(index=1, language=lang, codec="aac")])


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    config_dir = tmp_path / "config"
    media = tmp_path / "media"
    output = tmp_path / "filtered"
    config_dir.mkdir()
    media.mkdir()
    (media / "Film.DE.mkv").touch()
    (media / "Film.EN.mkv").touch()
    _write_config(config_dir, media, output)
    return config_dir, media, output


def _invoke(*args: str) -> object:
    with (
        patch.object(FFProbeProber, "probe", _fake_probe),
        patch.object(FFProbeProber, "check_available", lambda self: None),
    ):
        return runner.invoke(
            app,
            [*args, "--dangerous-skip-readonly-check", "--log-dir", ""],
        )


class TestScanCommand:
    def test_scan_creates_links(self, setup: tuple[Path, Path, Path]) -> None:
        config_dir, media, output = setup
        result = _invoke("scan", "--config-dir", str(config_dir))
        assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
        assert (output / "German" / "Film.DE.mkv").is_symlink()
        assert not (output / "German" / "Film.EN.mkv").exists()

    def test_scan_dry_run(self, setup: tuple[Path, Path, Path]) -> None:
        config_dir, _, output = setup
        result = _invoke("scan", "--config-dir", str(config_dir), "--dry-run")
        assert result.exit_code == 0, result.output  # type: ignore[attr-defined]
        assert not output.exists()

    def test_scan_fails_fast_without_ffprobe(
        self, setup: tuple[Path, Path, Path]
    ) -> None:
        config_dir, _, output = setup
        with patch("boomarr.probers.ffprobe.shutil.which", return_value=None):
            result = runner.invoke(
                app,
                [
                    "scan",
                    "--config-dir",
                    str(config_dir),
                    "--dangerous-skip-readonly-check",
                    "--log-dir",
                    "",
                ],
            )
        assert result.exit_code == 1
        assert not output.exists()


class TestStatusCommand:
    def test_status_json(self, setup: tuple[Path, Path, Path]) -> None:
        config_dir, _, output = setup
        result = runner.invoke(
            app, ["status", "--config-dir", str(config_dir), "--json", "--log-dir", ""]
        )
        assert result.exit_code == 0
        assert str(output / "German") in result.output

    def test_status_text(self, setup: tuple[Path, Path, Path]) -> None:
        config_dir, _, _ = setup
        result = runner.invoke(
            app, ["status", "--config-dir", str(config_dir), "--log-dir", ""]
        )
        assert result.exit_code == 0
        assert "Cached files" in result.output


class TestHealthcheck:
    def test_missing_heartbeat_is_unhealthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HEARTBEAT_FILE", str(tmp_path / "hb"))
        assert runner.invoke(app, ["healthcheck"]).exit_code == 1

    def test_fresh_heartbeat_is_healthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hb = tmp_path / "hb"
        hb.touch()
        monkeypatch.setenv("HEARTBEAT_FILE", str(hb))
        assert runner.invoke(app, ["healthcheck"]).exit_code == 0

    def test_old_heartbeat_is_unhealthy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hb = tmp_path / "hb"
        hb.touch()
        old = time.time() - 3600
        os.utime(hb, (old, old))
        monkeypatch.setenv("HEARTBEAT_FILE", str(hb))
        assert runner.invoke(app, ["healthcheck"]).exit_code == 1


class TestWatcherResilience:
    def test_failing_scan_does_not_stop_watcher(self) -> None:
        calls = 0

        def scan(cancel: threading.Event) -> ScanResult:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("disk on fire")
            return ScanResult()

        watcher = Watcher(triggers=[], scan_callback=scan, debounce_seconds=0.01)

        async def main() -> None:
            from boomarr.models import ScanEvent

            for _ in range(2):
                watcher._queue.put_nowait(ScanEvent("t", time.monotonic()))
                await asyncio.sleep(0)

            async def feed() -> None:
                await asyncio.sleep(0.2)
                watcher._queue.put_nowait(ScanEvent("t", time.monotonic()))
                await asyncio.sleep(0.3)
                watcher._request_shutdown()

            asyncio.create_task(feed())
            await watcher._run()

        asyncio.run(main())
        assert calls == 2

    def test_shutdown_cancels_running_scan(self) -> None:
        seen: list[bool] = []

        def scan(cancel: threading.Event) -> ScanResult:
            cancel.wait(timeout=5)
            seen.append(cancel.is_set())
            return ScanResult()

        watcher = Watcher(triggers=[], scan_callback=scan, debounce_seconds=0.01)

        async def main() -> None:
            from boomarr.models import ScanEvent

            watcher._queue.put_nowait(ScanEvent("t", time.monotonic()))

            async def stop() -> None:
                await asyncio.sleep(0.3)
                watcher._request_shutdown()

            asyncio.create_task(stop())
            started = time.monotonic()
            await watcher._run()
            assert time.monotonic() - started < 3

        asyncio.run(main())
        assert seen == [True]

    def test_heartbeat_written(self, tmp_path: Path) -> None:
        hb = tmp_path / "sub" / "hb"
        watcher = Watcher(
            triggers=[],
            scan_callback=lambda cancel: ScanResult(),
            heartbeat_file=hb,
            heartbeat_interval=0.05,
        )

        async def main() -> None:
            async def stop() -> None:
                await asyncio.sleep(0.2)
                watcher._request_shutdown()

            asyncio.create_task(stop())
            await watcher._run()

        asyncio.run(main())
        assert hb.exists()


class TestSymlinkManagerDetails:
    def test_link_target_relative(self, tmp_path: Path) -> None:
        source = tmp_path / "in" / "a" / "m.mkv"
        dest = tmp_path / "out" / "a" / "m.mkv"
        assert link_target(source, dest, relative=True) == "../../in/a/m.mkv"
        assert link_target(source, dest) == str(source)

    def test_switching_to_relative_updates_link(self, tmp_path: Path) -> None:
        source = tmp_path / "in" / "m.mkv"
        source.parent.mkdir()
        source.touch()
        dest = tmp_path / "out" / "m.mkv"
        mgr = SymlinkManager()
        assert mgr.ensure_link(source, dest) is True
        assert mgr.ensure_link(source, dest) is False
        assert mgr.ensure_link(source, dest, relative=True) is True
        assert not os.readlink(dest).startswith("/")
        assert not list(dest.parent.glob(".*boomarr-tmp"))

    def test_existing_absolute_links_are_kept(self, tmp_path: Path) -> None:
        """Links created by older versions must not be rewritten."""
        source = tmp_path / "in" / "m.mkv"
        source.parent.mkdir()
        source.touch()
        dest = tmp_path / "out" / "m.mkv"
        dest.parent.mkdir()
        dest.symlink_to(source)
        assert SymlinkManager().ensure_link(source, dest) is False

    def test_regular_file_is_never_replaced(self, tmp_path: Path) -> None:
        source = tmp_path / "m.mkv"
        source.touch()
        dest = tmp_path / "out" / "m.mkv"
        dest.parent.mkdir()
        dest.write_text("user data")
        assert SymlinkManager().ensure_link(source, dest) is False
        assert dest.read_text() == "user data"

    def test_reconcile_dry_run(self, tmp_path: Path) -> None:
        owned = tmp_path / "in"
        owned.mkdir()
        (owned / "m.mkv").touch()
        out = tmp_path / "out"
        out.mkdir()
        (out / "m.mkv").symlink_to(owned / "m.mkv")
        assert SymlinkManager(dry_run=True).reconcile(out, set(), owned) == 1
        assert (out / "m.mkv").is_symlink()

    def test_directory_symlinks_are_seen(self, tmp_path: Path) -> None:
        owned = tmp_path / "in"
        (owned / "d").mkdir(parents=True)
        out = tmp_path / "out"
        out.mkdir()
        (out / "d").symlink_to(owned / "d")
        assert SymlinkManager().reconcile(out, set(), owned) == 1
        assert not (out / "d").exists()


class TestFFProbeProber:
    def test_check_available(self) -> None:
        with patch("boomarr.probers.ffprobe.shutil.which", return_value=None):
            assert FFProbeProber(path="nope").check_available() is not None
        with patch("boomarr.probers.ffprobe.shutil.which", return_value="/x"):
            assert FFProbeProber().check_available() is None

    def test_command_uses_path_and_timeout(self, tmp_path: Path) -> None:
        media = tmp_path / "m.mkv"
        media.touch()
        with patch("boomarr.probers.ffprobe.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = '{"streams": []}'
            FFProbeProber(path="/opt/ffprobe", timeout=5).probe(media)
        args, kwargs = run.call_args
        assert args[0][0] == "/opt/ffprobe"
        assert args[0][-1] == str(media)
        assert "error" in args[0]
        assert kwargs["timeout"] == 5


def test_empty_log_dir_disables_file_logging(
    setup: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: typer used to turn '' into Path('.') and log into the CWD."""
    config_dir, _, _ = setup
    monkeypatch.chdir(config_dir)
    result = runner.invoke(
        app, ["status", "--config-dir", str(config_dir), "--log-dir", ""]
    )
    assert result.exit_code == 0
    assert not list(config_dir.glob("*.log*"))
