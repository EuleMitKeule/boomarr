"""Tests for the trigger config, pipeline trigger building, and watcher."""

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from boomarr.config import (
    Config,
    GeneralConfig,
    LoggingConfig,
    ScheduleTriggerConfig,
    WatchConfig,
)
from boomarr.const import DEFAULT_WATCH_DEBOUNCE, TriggerType
from boomarr.models import ScanEvent, ScanResult
from boomarr.pipeline import PipelineFactory
from boomarr.triggers.base import TriggerSource
from boomarr.triggers.schedule import ScheduleTrigger
from boomarr.watcher import Watcher

# ------------------------------------------------------------------ #
# ScanEvent model
# ------------------------------------------------------------------ #


class TestScanEvent:
    def test_create(self) -> None:
        ts = time.monotonic()
        event = ScanEvent(source="test", timestamp=ts)
        assert event.source == "test"
        assert event.timestamp == ts

    def test_frozen(self) -> None:
        event = ScanEvent(source="a", timestamp=0.0)
        with pytest.raises(AttributeError):
            event.source = "b"  # type: ignore[misc]


# ------------------------------------------------------------------ #
# ScheduleTriggerConfig
# ------------------------------------------------------------------ #


class TestScheduleTriggerConfig:
    def test_defaults(self) -> None:
        cfg = ScheduleTriggerConfig()
        assert cfg.type == TriggerType.SCHEDULE
        assert cfg.interval == 600
        assert cfg.run_on_start is True

    def test_custom_values(self) -> None:
        cfg = ScheduleTriggerConfig(interval=120, run_on_start=False)
        assert cfg.interval == 120
        assert cfg.run_on_start is False

    def test_invalid_interval_zero(self) -> None:
        with pytest.raises(ValidationError, match="positive"):
            ScheduleTriggerConfig(interval=0)

    def test_invalid_interval_negative(self) -> None:
        with pytest.raises(ValidationError, match="positive"):
            ScheduleTriggerConfig(interval=-10)

    def test_coercion_from_dict(self) -> None:
        """The _coerce_typed_list helper turns {'type': 'schedule'} into a valid config."""
        cfg = ScheduleTriggerConfig.model_validate({"type": "schedule", "interval": 60})
        assert cfg.type == TriggerType.SCHEDULE
        assert cfg.interval == 60


# ------------------------------------------------------------------ #
# Config integration
# ------------------------------------------------------------------ #


class TestConfigTriggers:
    def _minimal_config(self, tmp_path: Path, **kwargs: object) -> Config:
        return Config(
            config_dir=tmp_path,
            config_file="test.yml",
            general=GeneralConfig(),
            logging=LoggingConfig(),
            output_path=tmp_path / "out",
            **kwargs,  # type: ignore[arg-type]
        )

    def test_default_has_schedule_trigger(self, tmp_path: Path) -> None:
        """Default config should include a ScheduleTrigger."""
        cfg = self._minimal_config(tmp_path)
        assert len(cfg.triggers) == 1
        assert cfg.triggers[0].type == TriggerType.SCHEDULE
        assert cfg.triggers[0].interval == 600
        assert cfg.triggers[0].run_on_start is True

    def test_triggers_from_dicts(self, tmp_path: Path) -> None:
        cfg = self._minimal_config(
            tmp_path,
            triggers=[{"type": "schedule", "interval": 300}],
        )
        assert len(cfg.triggers) == 1
        assert cfg.triggers[0].type == TriggerType.SCHEDULE
        assert cfg.triggers[0].interval == 300

    def test_triggers_shorthand_coercion(self, tmp_path: Path) -> None:
        """Plain string 'schedule' is coerced to {'type': 'schedule'}."""
        cfg = self._minimal_config(tmp_path, triggers=["schedule"])
        assert len(cfg.triggers) == 1
        assert cfg.triggers[0].type == TriggerType.SCHEDULE

    def test_multiple_triggers(self, tmp_path: Path) -> None:
        cfg = self._minimal_config(
            tmp_path,
            triggers=[
                {"type": "schedule", "interval": 60},
                {"type": "schedule", "interval": 3600},
            ],
        )
        assert len(cfg.triggers) == 2


# ------------------------------------------------------------------ #
# PipelineFactory.build_triggers
# ------------------------------------------------------------------ #


class TestBuildTriggers:
    def test_empty(self) -> None:
        assert PipelineFactory.build_triggers([]) == []

    def test_schedule(self) -> None:
        cfg = ScheduleTriggerConfig(interval=120, run_on_start=False)
        triggers = PipelineFactory.build_triggers([cfg])
        assert len(triggers) == 1
        assert isinstance(triggers[0], ScheduleTrigger)

    def test_unknown_type_raises(self) -> None:
        cfg = MagicMock()
        cfg.type = "nonexistent"
        with pytest.raises(ValueError, match="Unknown trigger"):
            PipelineFactory.build_triggers([cfg])


# ------------------------------------------------------------------ #
# WatchConfig
# ------------------------------------------------------------------ #


class TestWatchConfig:
    def test_defaults(self, tmp_path: Path) -> None:
        cfg = WatchConfig()
        assert cfg.debounce == DEFAULT_WATCH_DEBOUNCE

    def test_custom_debounce(self) -> None:
        cfg = WatchConfig(debounce=5.0)
        assert cfg.debounce == 5.0

    def test_zero_debounce_allowed(self) -> None:
        cfg = WatchConfig(debounce=0.0)
        assert cfg.debounce == 0.0

    def test_negative_debounce_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-negative"):
            WatchConfig(debounce=-1.0)

    def test_config_default_debounce(self, tmp_path: Path) -> None:
        cfg = Config(
            config_dir=tmp_path,
            config_file="test.yml",
            general=GeneralConfig(),
            logging=LoggingConfig(),
            output_path=tmp_path / "out",
        )
        assert cfg.watch.debounce == DEFAULT_WATCH_DEBOUNCE


# ------------------------------------------------------------------ #
# ScheduleTrigger (runtime behaviour)
# ------------------------------------------------------------------ #


class TestScheduleTrigger:
    def test_start_stop_no_crash(self) -> None:
        trigger = ScheduleTrigger(interval=60)
        queue: asyncio.Queue[ScanEvent] = asyncio.Queue()

        async def _run() -> None:
            await trigger.start(queue)
            await trigger.stop()

        asyncio.run(_run())

    def test_stop_without_start(self) -> None:
        trigger = ScheduleTrigger(interval=60)

        async def _run() -> None:
            await trigger.stop()

        asyncio.run(_run())

    def test_run_on_start_emits_immediately(self) -> None:
        """With run_on_start=True an event is queued as soon as start() is called."""
        trigger = ScheduleTrigger(interval=9999, run_on_start=True)
        queue: asyncio.Queue[ScanEvent] = asyncio.Queue()

        async def _run() -> None:
            await trigger.start(queue)
            # Give the background task a moment to run.
            await asyncio.sleep(0.05)
            await trigger.stop()

        asyncio.run(_run())
        assert queue.qsize() == 1
        event = queue.get_nowait()
        assert event.source == "schedule"

    def test_run_on_start_false_does_not_emit_immediately(self) -> None:
        """With run_on_start=False no event is queued before interval elapses."""
        trigger = ScheduleTrigger(interval=9999, run_on_start=False)
        queue: asyncio.Queue[ScanEvent] = asyncio.Queue()

        async def _run() -> None:
            await trigger.start(queue)
            await asyncio.sleep(0.05)
            await trigger.stop()

        asyncio.run(_run())
        assert queue.qsize() == 0


# ------------------------------------------------------------------ #
# Watcher
# ------------------------------------------------------------------ #


class _ImmediateTrigger(TriggerSource):
    """Test trigger that fires one event then stops."""

    async def start(self, queue: asyncio.Queue[ScanEvent]) -> None:
        queue.put_nowait(ScanEvent(source="immediate", timestamp=time.monotonic()))

    async def stop(self) -> None:
        pass


class TestWatcher:
    def test_single_event_triggers_scan(self) -> None:
        results: list[ScanResult] = []

        def scan_all() -> ScanResult:
            r = ScanResult(created=1)
            results.append(r)
            return r

        watcher = Watcher(
            triggers=[_ImmediateTrigger()],
            scan_callback=scan_all,
            debounce_seconds=0.05,
        )

        async def _run() -> None:
            # Let the watcher process the event, then shut it down.
            async def _shutdown_soon() -> None:
                await asyncio.sleep(0.3)
                watcher._request_shutdown()

            asyncio.create_task(_shutdown_soon())
            await watcher._run()

        asyncio.run(_run())
        assert len(results) == 1

    def test_debounce_collapses_events(self) -> None:
        call_count = 0

        def scan_all() -> ScanResult:
            nonlocal call_count
            call_count += 1
            return ScanResult()

        watcher = Watcher(
            triggers=[],
            scan_callback=scan_all,
            debounce_seconds=0.1,
        )

        async def _run() -> None:
            # Put 5 events rapidly into the queue.
            for _ in range(5):
                watcher._queue.put_nowait(
                    ScanEvent(source="burst", timestamp=time.monotonic())
                )

            async def _shutdown_soon() -> None:
                await asyncio.sleep(0.5)
                watcher._request_shutdown()

            asyncio.create_task(_shutdown_soon())
            await watcher._run()

        asyncio.run(_run())
        # All 5 events should collapse into a single scan.
        assert call_count == 1

    def test_shutdown_event_stops_worker(self) -> None:
        watcher = Watcher(
            triggers=[],
            scan_callback=lambda: ScanResult(),
            debounce_seconds=0.05,
        )

        async def _run() -> None:
            watcher._request_shutdown()
            await watcher._worker()

        asyncio.run(_run())

    def test_empty_triggers_exits_cleanly(self) -> None:
        """Empty trigger list should exit without blocking."""
        watcher = Watcher(
            triggers=[],
            scan_callback=lambda: ScanResult(),
        )

        async def _run() -> None:
            async def _shutdown_soon() -> None:
                await asyncio.sleep(0.1)
                watcher._request_shutdown()

            asyncio.create_task(_shutdown_soon())
            await watcher._run()

        asyncio.run(_run())
