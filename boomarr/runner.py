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
from boomarr.const import APP_NAME, VERSION
from boomarr.metrics import METRICS
from boomarr.models import ProgressCallback, ScanResult
from boomarr.pipeline import PipelineFactory
from boomarr.processor import LibraryProcessor
from boomarr.state import summarize_scan

_LOGGER = logging.getLogger(__name__)

LAST_SCAN_KEY = "last_scan"
MAX_RECORDED_ISSUES = 200
"""Maximum number of warnings and errors kept per scan (for the UI)."""
_PROBE_THREAD_PREFIX = "probe"


class IssueCollector(logging.Handler):
    """Collects the warnings and errors logged by one scan.

    Only records from the scanning thread and its probe workers are kept, so
    unrelated messages (e.g. from the web server) do not end up in the report.
    """

    def __init__(self, thread_id: int) -> None:
        super().__init__(level=logging.WARNING)
        self._thread_id = thread_id
        self._lock_issues = threading.Lock()
        self.issues: list[dict[str, Any]] = []
        self.dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        if record.thread != self._thread_id and not (
            record.threadName or ""
        ).startswith(_PROBE_THREAD_PREFIX):
            return
        with self._lock_issues:
            if len(self.issues) >= MAX_RECORDED_ISSUES:
                self.dropped += 1
                return
            self.issues.append(
                {
                    "time": record.created,
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
            )


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
    issues: tuple[dict[str, Any], ...] = ()
    issues_dropped: int = 0

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
            "issues": list(self.issues),
            "issues_dropped": self.issues_dropped,
        }
        if self.result is not None:
            result = dataclasses.asdict(self.result)
            result["changed_outputs"] = sorted(self.result.changed_outputs)
            data["result"] = result
        return data


def _with_id(record: dict[str, Any], scan_id: int | None) -> dict[str, Any]:
    return record if scan_id is None else {**record, "id": scan_id}


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
        self._last_id: int | None = None
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
        collector = IssueCollector(threading.get_ident())
        app_logger = logging.getLogger(APP_NAME)
        app_logger.addHandler(collector)
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
            app_logger.removeHandler(collector)
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
                issues=tuple(collector.issues),
                issues_dropped=collector.dropped,
            )
            scan_id = self._record(report)
            with self._lock:
                self._last = report
                self._last_id = scan_id
                self._running = False
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

    def last_summary(self) -> dict[str, Any] | None:
        """The last report with its history id, without change and issue lists."""
        with self._lock:
            last, scan_id = self._last, self._last_id
        return (
            None if last is None else summarize_scan(_with_id(last.as_dict(), scan_id))
        )

    def _record(self, report: ScanReport) -> int | None:
        """Store the report in the history and, for real scans, as last scan.

        Returns the id of the history entry.
        """
        record = report.as_dict()
        state = self._factory.state
        try:
            scan_id = state.add_scan(record)
            if not report.dry_run and not report.cancelled:
                state.set_meta(LAST_SCAN_KEY, summarize_scan({**record, "id": scan_id}))
        except Exception:  # pragma: no cover - history must never break scans
            _LOGGER.exception("Could not store the scan report")
            return None
        return scan_id

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
