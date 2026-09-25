"""Tiny, dependency-free Prometheus metrics registry.

Only what Boomarr needs: counters and gauges with optional labels, rendered
in the Prometheus text exposition format (``GET /metrics``).
"""

import threading
import time
from collections.abc import Mapping

from boomarr.const import VERSION
from boomarr.models import ScanResult

_Labels = tuple[tuple[str, str], ...]


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


class Metrics:
    """Thread-safe collection of Boomarr metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, dict[_Labels, float]] = {}
        self._gauges: dict[str, dict[_Labels, float]] = {}
        self._help: dict[str, tuple[str, str]] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.describe("boomarr_build_info", "gauge", "Boomarr build information.")
        self.set_gauge("boomarr_build_info", 1, {"version": VERSION})
        self.describe("boomarr_scans_total", "counter", "Completed scans by status.")
        self.describe(
            "boomarr_scan_duration_seconds", "gauge", "Duration of the last scan."
        )
        self.describe(
            "boomarr_last_scan_timestamp_seconds",
            "gauge",
            "Unix time the last scan finished.",
        )
        self.describe(
            "boomarr_links_created_total", "counter", "Symlinks created or updated."
        )
        self.describe("boomarr_links_removed_total", "counter", "Symlinks removed.")
        self.describe("boomarr_files_probed_total", "counter", "Files probed.")
        self.describe(
            "boomarr_errors_total", "counter", "Files or libraries that failed."
        )
        self.describe(
            "boomarr_removal_guard_blocked_total",
            "counter",
            "Reconciliations refused by the removal guard.",
        )
        self.describe(
            "boomarr_links",
            "gauge",
            "Symlinks per output directory after the last scan.",
        )
        self.describe("boomarr_cache_entries", "gauge", "Entries in the probe cache.")

    def describe(self, name: str, kind: str, text: str) -> None:
        with self._lock:
            self._help[name] = (kind, text)

    def inc(
        self, name: str, value: float = 1, labels: Mapping[str, str] | None = None
    ) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            series = self._counters.setdefault(name, {})
            series[key] = series.get(key, 0) + value

    def set_gauge(
        self, name: str, value: float, labels: Mapping[str, str] | None = None
    ) -> None:
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            self._gauges.setdefault(name, {})[key] = value

    def get(self, name: str, labels: Mapping[str, str] | None = None) -> float:
        """Return the current value of a counter or gauge (0 if unset)."""
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            for store in (self._counters, self._gauges):
                if key in store.get(name, {}):
                    return store[name][key]
        return 0

    def record_scan(
        self,
        result: ScanResult | None,
        duration: float,
        cache_entries: int | None = None,
    ) -> None:
        """Update all scan related metrics after a scan finished or failed."""
        self.inc("boomarr_scans_total", labels={"status": "ok" if result else "failed"})
        self.set_gauge("boomarr_scan_duration_seconds", duration)
        self.set_gauge("boomarr_last_scan_timestamp_seconds", time.time())
        if cache_entries is not None:
            self.set_gauge("boomarr_cache_entries", cache_entries)
        if result is None:
            return
        self.inc("boomarr_links_created_total", result.created)
        self.inc("boomarr_links_removed_total", result.removed)
        self.inc("boomarr_files_probed_total", result.probed)
        self.inc("boomarr_errors_total", result.errors)
        self.inc("boomarr_removal_guard_blocked_total", result.blocked)
        for output, count in result.links.items():
            self.set_gauge("boomarr_links", count, {"output": output})

    def render(self) -> str:
        """Return all metrics in the Prometheus text format."""
        lines: list[str] = []
        with self._lock:
            names = sorted({*self._counters, *self._gauges, *self._help})
            for name in names:
                kind, text = self._help.get(
                    name, ("counter" if name in self._counters else "gauge", "")
                )
                lines.append(f"# HELP {name} {text}")
                lines.append(f"# TYPE {name} {kind}")
                series = self._counters.get(name) or self._gauges.get(name) or {}
                if not series and kind == "counter":
                    lines.append(f"{name} 0")
                for labels, value in sorted(series.items()):
                    label_str = ",".join(f'{k}="{_escape(v)}"' for k, v in labels)
                    suffix = f"{{{label_str}}}" if label_str else ""
                    lines.append(f"{name}{suffix} {value:g}")
        return "\n".join(lines) + "\n"


METRICS = Metrics()
"""Process-wide metrics registry."""
