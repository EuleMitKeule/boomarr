"""Scan orchestration shared by ``scan`` and ``watch``.

:class:`ScanRunner` processes every configured library, records metrics,
remembers the last result for the status API and runs post-scan hooks
(notifications, media server refreshes). Hook failures are logged and never
affect the scan itself.
"""

import dataclasses
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from boomarr.config import Config
from boomarr.const import VERSION
from boomarr.metrics import METRICS
from boomarr.models import ProgressCallback, ScanResult
from boomarr.pipeline import PipelineFactory
from boomarr.processor import LibraryProcessor

_LOGGER = logging.getLogger(__name__)

LAST_SCAN_KEY = "last_scan"


@dataclass(frozen=True)
class ScanReport:
    """Outcome of one full scan, handed to post-scan hooks."""

    result: ScanResult | None
    duration: float
    finished_at: float
    error: str | None = None
    dry_run: bool = False
    force: bool = False
    source: str = "cli"
    cancelled: bool = False

    @property
    def changed_outputs(self) -> list[str]:
        """Output directories that had links created or removed."""
        if self.result is None:
            return []
        return sorted(self.result.changed_outputs)

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "started_at": self.finished_at - self.duration,
            "finished_at": self.finished_at,
            "duration_seconds": round(self.duration, 3),
            "error": self.error,
            "dry_run": self.dry_run,
            "force": self.force,
            "source": self.source,
            "cancelled": self.cancelled,
        }
        if self.result is not None:
            result = dataclasses.asdict(self.result)
            result["changed_outputs"] = sorted(self.result.changed_outputs)
            data["result"] = result
        return data


class PostScanHook(Protocol):
    """Something that reacts to a finished scan."""

    def after_scan(self, report: ScanReport) -> None:
        """Handle a finished (or failed) scan."""


class ScanRunner:
    """Runs full scans and everything that belongs around them."""

    def __init__(
        self,
        config: Config,
        factory: PipelineFactory,
        *,
        hooks: list[PostScanHook] | None = None,
        dry_run: bool = False,
    ) -> None:
        self._config = config
        self._factory = factory
        self._hooks = hooks or []
        self._dry_run = dry_run
        self._lock = threading.Lock()
        self._last: ScanReport | None = None
        self._running = False

    @property
    def config(self) -> Config:
        return self._config

    def scan_libraries(
        self,
        cancel: threading.Event,
        *,
        dry_run: bool | None = None,
        force: bool | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> ScanResult:
        """Process every configured library, isolating per-library failures."""
        total = ScanResult()
        for library in self._config.libraries:
            if cancel.is_set():
                break
            try:
                pipeline = self._factory.for_scan(
                    self._config, library, dry_run=dry_run, force=force
                )
                processor = LibraryProcessor(
                    pipeline, cancel=cancel, on_progress=on_progress
                )
                result = processor.process_library(library)
            except Exception:
                _LOGGER.exception("Processing library '%s' failed", library.name)
                total.errors += 1
                continue
            total.merge(result)
        return total

    def run(
        self,
        cancel: threading.Event,
        *,
        dry_run: bool | None = None,
        force: bool = False,
        source: str = "cli",
        on_progress: ProgressCallback | None = None,
    ) -> ScanResult:
        """Run a full scan, record metrics and history and invoke the hooks."""
        dry_run = self._dry_run if dry_run is None else dry_run
        with self._lock:
            self._running = True
        started = time.monotonic()
        result: ScanResult | None = None
        error: str | None = None
        try:
            result = self.scan_libraries(
                cancel,
                dry_run=dry_run,
                force=force or None,
                on_progress=on_progress,
            )
            return result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            duration = time.monotonic() - started
            report = ScanReport(
                result=result,
                duration=duration,
                finished_at=time.time(),
                error=error,
                dry_run=dry_run,
                force=force,
                source=source,
                cancelled=cancel.is_set(),
            )
            with self._lock:
                self._last = report
                self._running = False
            self._record(report)
            if not cancel.is_set() and not dry_run:
                METRICS.record_scan(result, duration, self._cache_entries())
                self._run_hooks(report)

    def status(self) -> dict[str, Any]:
        """Return the JSON document served at ``/api/v1/status``."""
        with self._lock:
            last = self._last
            running = self._running
        return {
            "version": VERSION,
            "running": running,
            "last_scan": last.as_dict() if last else None,
        }

    @property
    def last_report(self) -> ScanReport | None:
        with self._lock:
            return self._last

    def _record(self, report: ScanReport) -> None:
        """Store the report in the history and, for real scans, as last scan."""
        record = report.as_dict()
        state = self._factory.state
        try:
            state.add_scan(record)
            if not report.dry_run and not report.cancelled:
                slim = {**record}
                if isinstance(slim.get("result"), dict):
                    slim["result"] = {
                        k: v for k, v in slim["result"].items() if k != "changes"
                    }
                state.set_meta(LAST_SCAN_KEY, slim)
        except Exception:  # pragma: no cover - history must never break scans
            _LOGGER.exception("Could not store the scan report")

    def _cache_entries(self) -> int | None:
        try:
            return self._factory.state.count()
        except Exception:  # pragma: no cover - metrics must never break scans
            return None

    def _run_hooks(self, report: ScanReport) -> None:
        for hook in self._hooks:
            try:
                hook.after_scan(report)
            except OSError as exc:  # unreachable server, DNS, timeouts
                _LOGGER.warning(
                    "Post-scan hook %s failed: %s", type(hook).__name__, exc
                )
            except Exception:
                _LOGGER.exception("Post-scan hook %s failed", type(hook).__name__)
