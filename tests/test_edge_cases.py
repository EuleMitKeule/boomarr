"""Edge cases across the core modules (error paths, dry runs, fallbacks)."""

import asyncio
import logging
import os
import sys
import threading
import urllib.error
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from boomarr.config import (
    Config,
    GeneralConfig,
    JellyfinConfig,
    LoggingConfig,
    LogRotationConfig,
    NotificationsConfig,
    ProberConfig,
    WebhookTriggerConfig,
    build_config,
)
from boomarr.const import ProberType
from boomarr.hooks import JellyfinRefreshHook, NotificationHook, build_hooks
from boomarr.languages import language_from_name_or_code
from boomarr.log import _make_tz_converter, setup_logging
from boomarr.metrics import Metrics
from boomarr.models import (
    MAX_RECORDED_CHANGES,
    AudioTrack,
    MediaInfo,
    RemovalGuard,
    ScanResult,
)
from boomarr.pipeline import Pipeline, PipelineFactory
from boomarr.probers import arr as arr_module
from boomarr.probers.arr import ArrProber, _parse_languages, _parse_resolution
from boomarr.probers.base import MediaProber
from boomarr.probers.ffprobe import FFProbeProber, _int_or_none
from boomarr.processor import LibraryProcessor
from boomarr.runner import ScanReport, ScanRunner
from boomarr.state import InMemoryStateStore, SQLiteStateStore, _without_changes
from boomarr.status import _scan_lines, _triggers
from boomarr.symlinks import SymlinkManager, _log_walk_error
from boomarr.triggers.schedule import ScheduleTrigger
from tests.test_processor import StubProber, _make_library, _resolved_sym_lib

# ---------------------------------------------------------------------------
# Config / languages
# ---------------------------------------------------------------------------


def test_explicit_null_output_path(tmp_path: Path) -> None:
    config = Config(
        config_dir=tmp_path,
        config_file="b.yml",
        general=GeneralConfig(),
        logging=LoggingConfig(),
        output_path=None,
    )
    assert config.output_path is None


def test_language_name_with_qualifier() -> None:
    assert language_from_name_or_code("German (Switzerland)") == "deu"


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------


class TestHooks:
    def test_build_hooks_with_notifications(self, tmp_path: Path) -> None:
        config = build_config(
            {"notifications": {"urls": ["json://localhost"]}}, tmp_path, "b.yml"
        )
        assert isinstance(build_hooks(config)[0], NotificationHook)

    def test_invalid_url_and_failed_send(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import apprise

        with caplog.at_level(logging.WARNING):
            hook = NotificationHook(
                NotificationsConfig(urls=["nope://x", "json://localhost"])
            )
            monkeypatch.setattr(apprise.Apprise, "notify", lambda *a, **k: False)
            hook.after_scan(
                ScanReport(result=None, duration=1, finished_at=0, error="x")
            )
        assert "Invalid notification URL" in caplog.text
        assert "Sending notification failed" in caplog.text

    def test_errors_can_be_muted(self) -> None:
        hook = NotificationHook(NotificationsConfig(on_errors=False))
        report = ScanReport(result=None, duration=1, finished_at=0, error="x")
        assert hook.build_message(report) is None

    def test_jellyfin_without_changes(self) -> None:
        hook = JellyfinRefreshHook(JellyfinConfig(url="http://jf", api_key="k"))
        hook.after_scan(ScanReport(result=ScanResult(), duration=1, finished_at=0))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


class TestLogging:
    def test_converter_without_timestamp(self) -> None:
        assert _make_tz_converter("UTC")(None).tm_year >= 2024

    def test_color_and_rotation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True, raising=False)
        (tmp_path / "boomarr.log").write_text("old\n")
        setup_logging(LoggingConfig(dir=tmp_path, color=True))
        logging.getLogger("boomarr.edge").error("colored")
        logging.getLogger("boomarr.edge").log(5, "no color for custom levels")
        assert (tmp_path / "boomarr.log.1").read_text() == "old\n"
        assert "colored" in (tmp_path / "boomarr.log").read_text()

    def test_rotation_without_previous_file(self, tmp_path: Path) -> None:
        setup_logging(LoggingConfig(dir=tmp_path / "fresh", color=False))
        logging.getLogger("boomarr.edge").warning("first")
        assert not (tmp_path / "fresh" / "boomarr.log.1").exists()

    def test_without_rotation(self, tmp_path: Path) -> None:
        setup_logging(
            LoggingConfig(
                dir=tmp_path, rotation=LogRotationConfig(enabled=False), color=False
            )
        )
        logging.getLogger("boomarr.edge").warning("plain")
        assert "plain" in (tmp_path / "boomarr.log").read_text()
        handlers = logging.getLogger("boomarr").handlers
        assert any(type(h) is logging.FileHandler for h in handlers)


# ---------------------------------------------------------------------------
# Metrics and models
# ---------------------------------------------------------------------------


def test_metrics_get_and_empty_counters() -> None:
    metrics = Metrics()
    metrics.set_gauge("g", 3)
    assert metrics.get("g") == 3
    assert metrics.get("missing") == 0
    assert "boomarr_scans_total 0" in metrics.render()


def test_record_change_is_capped() -> None:
    result = ScanResult()
    for i in range(MAX_RECORDED_CHANGES + 5):
        result.record_change("created", Path(f"/x/{i}"))
    assert len(result.changes) == MAX_RECORDED_CHANGES


# ---------------------------------------------------------------------------
# Pipeline and probers
# ---------------------------------------------------------------------------


def test_pipeline_legacy_webhook_and_plain_ffprobe_config() -> None:
    assert PipelineFactory.build_triggers([WebhookTriggerConfig()]) == []
    probers = PipelineFactory._build_probers([ProberConfig(type=ProberType.FFPROBE)])
    assert isinstance(probers[0], FFProbeProber)


def test_base_prober_is_available() -> None:
    class Nothing(MediaProber):
        def probe(self, file: Path) -> MediaInfo | None:
            return None

    assert Nothing().check_available() is None


def test_ffprobe_int_or_none() -> None:
    assert _int_or_none("abc") is None


class TestArrEdges:
    def test_parsers(self) -> None:
        assert _parse_languages(None) == []
        assert _parse_resolution("widexhigh") == (None, None)

    def test_files_without_media_info_are_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prober = ArrProber(kind="sonarr", url="http://sonarr", api_key="k")
        monkeypatch.setattr(
            prober,
            "_files",
            lambda: [
                {"path": "/tv/a.mkv"},
                {"path": "/tv/b.mkv", "mediaInfo": {"audioLanguages": "eng"}},
            ],
        )
        prober._refresh()
        assert list(prober._index) == [Path("/tv/b.mkv")]

    def test_network_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prober = ArrProber(
            kind="radarr", url="http://127.0.0.1:9", api_key="k", timeout=0.5
        )

        def refused(*_: Any, **__: Any) -> Any:
            raise urllib.error.URLError("refused")

        monkeypatch.setattr(arr_module.urllib.request, "urlopen", refused)
        assert prober.probe(Path("/m/a.mkv")) is None
        assert prober.check_available() is None


# ---------------------------------------------------------------------------
# Processor
# ---------------------------------------------------------------------------


class TestProcessorEdges:
    def test_walk_errors_and_non_files(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        library = _make_library(tmp_path)
        (library.input_path / "broken.mkv").symlink_to(tmp_path / "missing.mkv")
        real_walk = os.walk

        def walk(top: Any, onerror: Any = None, **kwargs: Any) -> Any:
            error = OSError(13, "Permission denied")
            error.filename = str(top)
            onerror(error)
            return real_walk(top, onerror=onerror, **kwargs)

        monkeypatch.setattr("boomarr.processor.os.walk", walk)
        pipeline = Pipeline(
            probers=[StubProber({})],
            symlink_libraries=[_resolved_sym_lib(tmp_path / "out")],
        )
        with caplog.at_level(logging.WARNING):
            LibraryProcessor(pipeline).process_library(library)
        assert "Cannot read directory" in caplog.text

    def test_stat_and_link_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        library = _make_library(tmp_path)
        good = library.input_path / "good.DE.mkv"
        gone = library.input_path / "gone.mkv"
        good.touch()
        gone.touch()
        real_stat = Path.stat

        def stat(self: Path, *args: Any, **kwargs: Any) -> os.stat_result:
            if (
                self.name == "gone.mkv"
                and kwargs.get("follow_symlinks", True) is not False
            ):
                raise OSError("vanished")
            return real_stat(self, *args, **kwargs)

        prober = StubProber(
            {
                str(good): MediaInfo(
                    good, [AudioTrack(index=0, language="de", codec="aac")]
                )
            }
        )
        manager = SymlinkManager()
        manager.ensure_link = MagicMock(side_effect=OSError("read-only"))
        pipeline = Pipeline(
            probers=[prober],
            symlink_libraries=[_resolved_sym_lib(tmp_path / "out")],
            symlinks=manager,
        )
        monkeypatch.setattr(Path, "stat", stat)
        result = LibraryProcessor(pipeline).process_library(library)
        assert result.errors == 2

    def test_blocked_scan_still_reports_new_links(self, tmp_path: Path) -> None:
        library = _make_library(tmp_path)
        out = tmp_path / "output-de"
        files = [library.input_path / f"m{i}.mkv" for i in range(10)]
        for f in files:
            f.touch()

        def run(lang: str, extra: list[Path]) -> ScanResult:
            infos: dict[str, MediaInfo | None] = {
                str(f): MediaInfo(f, [AudioTrack(index=0, language=lang, codec="aac")])
                for f in files
            }
            for f in extra:
                infos[str(f)] = MediaInfo(
                    f, [AudioTrack(index=0, language="de", codec="aac")]
                )
            pipeline = Pipeline(
                probers=[StubProber(infos)],
                symlink_libraries=[_resolved_sym_lib(out)],
                removal_guard=RemovalGuard(max_percent=50, min_count=5),
            )
            return LibraryProcessor(pipeline).process_library(library)

        run("de", [])
        new = library.input_path / "new.mkv"
        new.touch()
        result = run("en", [new])
        assert result.blocked == 1
        assert result.created == 1
        assert str(out) in result.changed_outputs


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class TestRunnerEdges:
    def _runner(self, config_dir: Path) -> ScanRunner:
        from boomarr.config_store import ConfigStore

        config = ConfigStore(config_dir, "boomarr.yml", {"logging": {"dir": ""}}).load()
        return ScanRunner(config, PipelineFactory(state=InMemoryStateStore()))

    def test_hook_failures_are_logged(
        self, config_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from boomarr.config_store import ConfigStore

        class Unreachable:
            def after_scan(self, report: ScanReport) -> None:
                raise OSError("connection refused")

        class Broken:
            def after_scan(self, report: ScanReport) -> None:
                raise RuntimeError("bug")

        config = ConfigStore(config_dir, "boomarr.yml", {"logging": {"dir": ""}}).load()
        runner = ScanRunner(
            config,
            PipelineFactory(state=InMemoryStateStore()),
            hooks=[Unreachable(), Broken()],
        )
        with caplog.at_level(logging.WARNING):
            runner._run_hooks(
                ScanReport(result=ScanResult(), duration=1, finished_at=0)
            )
        assert "Unreachable failed: connection refused" in caplog.text
        assert "Traceback" in caplog.text  # unexpected errors keep the traceback

    def test_report_without_result(self) -> None:
        report = ScanReport(result=None, duration=1, finished_at=5, error="x")
        assert report.changed_outputs == []
        assert "result" not in report.as_dict()

    def test_cancel_before_start(self, config_dir: Path) -> None:
        runner = self._runner(config_dir)
        assert runner.config.libraries[0].name == "Movies"
        cancel = threading.Event()
        cancel.set()
        assert runner.scan_libraries(cancel).total == 0

    def test_library_failure_is_isolated(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = self._runner(config_dir)
        monkeypatch.setattr(
            runner._factory, "for_scan", MagicMock(side_effect=RuntimeError("x"))
        )
        assert runner.scan_libraries(threading.Event()).errors == 1

    def test_failed_run_is_recorded(
        self, config_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        runner = self._runner(config_dir)
        monkeypatch.setattr(
            runner, "scan_libraries", MagicMock(side_effect=RuntimeError("boom"))
        )
        with pytest.raises(RuntimeError):
            runner.run(threading.Event())
        report = runner.last_report
        assert report is not None and report.error == "RuntimeError: boom"
        scans, _ = runner._factory.state.list_scans()
        assert scans[0]["error"] == "RuntimeError: boom"


# ---------------------------------------------------------------------------
# State stores
# ---------------------------------------------------------------------------


class TestStateEdges:
    def test_without_changes_passthrough(self) -> None:
        assert _without_changes({"result": None}) == {"result": None}

    def test_in_memory_history(self) -> None:
        store = InMemoryStateStore()
        assert store.was_reset is False
        scan_id = store.add_scan({"result": {"changes": [1, 2]}})
        items, total = store.list_scans()
        assert total == 1 and items[0]["result"]["changes_count"] == 2
        assert store.get_scan(scan_id)["result"]["changes"] == [1, 2]  # ty: ignore[not-subscriptable]
        assert store.get_scan(99) is None

    def test_sqlite_corrupt_rows(self, tmp_path: Path) -> None:
        store = SQLiteStateStore(tmp_path / "db.sqlite")
        try:
            conn = store._conn
            conn.execute("INSERT INTO meta (key, value) VALUES ('bad', 'not json')")
            conn.execute(
                "INSERT INTO scan_history (finished_at, record) VALUES (1, 'not json')"
            )
            conn.execute(
                "INSERT INTO file_cache (path, size, mtime, tracks, probed_at) VALUES ('/a', 1, 1, '[1]', 1)"
            )
            conn.commit()
            assert store.get_meta("bad") is None
            items, _ = store.list_scans()
            assert items == []
            assert store.get_stats()["total_cached"] >= 0
        finally:
            store.close()

    def test_sqlite_quick_check_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db = tmp_path / "db.sqlite"
        SQLiteStateStore(db).close()

        class FakeConn:
            def execute(self, *_: Any) -> Any:
                return self

            def fetchone(self) -> tuple[str]:
                return ("corrupt page",)

            def close(self) -> None:
                pass

        real_connect = SQLiteStateStore._connect
        calls: list[int] = []

        def connect(path: Path) -> Any:
            calls.append(1)
            return FakeConn() if len(calls) == 1 else real_connect(path)

        monkeypatch.setattr(SQLiteStateStore, "_connect", staticmethod(connect))
        store = SQLiteStateStore(db)
        assert store.was_reset is True
        store.close()


# ---------------------------------------------------------------------------
# Status, symlinks, schedule
# ---------------------------------------------------------------------------


def test_status_helpers(tmp_path: Path) -> None:
    config = build_config(
        {"server": {"enabled": False}, "triggers": []}, tmp_path, "b.yml"
    )
    assert _triggers(config) == []
    lines = _scan_lines({"finished_at": 1, "error": "boom"})
    assert ("Scan error", "boom") in lines
    assert len(lines) == 2


class TestSymlinkEdges:
    def test_dry_run_update_and_remove(self, tmp_path: Path) -> None:
        source = tmp_path / "a.mkv"
        source.touch()
        dest = tmp_path / "out" / "a.mkv"
        dest.parent.mkdir()
        dest.symlink_to(tmp_path / "other.mkv")
        manager = SymlinkManager(dry_run=True)
        assert manager.ensure_link(source, dest) is True
        assert os.readlink(dest) == str(tmp_path / "other.mkv")
        assert manager.remove_link(dest) is True
        assert dest.is_symlink()
        assert manager.remove_link(tmp_path / "nothing") is False
        assert manager._remove(dest, "stale") is True

    def test_remove_errors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager = SymlinkManager()
        assert manager._remove(tmp_path / "missing", "stale") is False
        link = tmp_path / "link"
        link.symlink_to(tmp_path / "x")

        def fail(self: Path, *args: Any, **kwargs: Any) -> None:
            raise PermissionError("nope")

        monkeypatch.setattr(Path, "unlink", fail)
        assert manager._remove(link, "stale") is False

    def test_unreadable_link_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        out = tmp_path / "out"
        out.mkdir()
        (out / "l").symlink_to(tmp_path / "x")

        def fail(link: Path) -> Path:
            raise OSError("gone")

        monkeypatch.setattr("boomarr.symlinks.resolve_link_target", fail)
        plan = SymlinkManager().plan_removals(out, set(), tmp_path)
        assert plan.removals == []

    def test_walk_error_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        error = OSError(13, "Permission denied")
        error.filename = "/x"
        with caplog.at_level(logging.WARNING):
            _log_walk_error(error)
        assert "Cannot read directory '/x'" in caplog.text


def test_schedule_trigger_repeats() -> None:
    async def main() -> int:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        trigger = ScheduleTrigger(interval=0.02, run_on_start=False)
        await trigger.start(queue)
        await asyncio.sleep(0.1)
        await trigger.stop()
        return queue.qsize()

    assert asyncio.run(main()) >= 2
