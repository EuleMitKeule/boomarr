"""Library processor module.

Orchestrates the scan/filter/symlink workflow for a single library using
the subsystems provided by a Pipeline.

A scan is a full reconciliation: the desired set of symlinks is computed
from the (cached) probe results and the *current* filter configuration, then
the output directories are brought in line with it. This makes the result
independent of history — changed filters, new symlink libraries or manually
deleted links are all fixed by the next scan.
"""

import dataclasses
import fnmatch
import logging
import os
import threading
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

from boomarr.config import LibraryConfig
from boomarr.filters.base import PostProbeFilter
from boomarr.models import MediaInfo, ProgressCallback, ScanResult
from boomarr.pipeline import Pipeline

_LOGGER = logging.getLogger(__name__)


class LibraryProcessor:
    """Processes a single library through the configured pipeline.

    Discovers media files, applies pre-probe filters, probes new or changed
    files via a fallback chain (in parallel), evaluates post-probe filters
    for each symlink library, and reconciles the symlinks accordingly.

    Args:
        pipeline: The configured subsystems.
        cancel: Optional event; when set, the scan stops as soon as possible
            without modifying any symlinks.
    """

    def __init__(
        self,
        pipeline: Pipeline,
        *,
        cancel: threading.Event | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._cancel = cancel or threading.Event()
        self._on_progress = on_progress
        self._library = ""

    def _progress(self, phase: str, done: int = 0, total: int = 0) -> None:
        if self._on_progress is not None:
            self._on_progress(
                {"library": self._library, "phase": phase, "done": done, "total": total}
            )

    def _dest_path(self, source: Path, input_path: Path, output_path: Path) -> Path:
        """Compute the destination symlink path mirroring the input structure."""
        relative = source.relative_to(input_path)
        return output_path / relative

    def _is_ignored(self, name: str) -> bool:
        return any(
            fnmatch.fnmatchcase(name, pattern)
            for pattern in self._pipeline.ignore_patterns
        )

    def _discover_files(self, input_path: Path) -> list[Path]:
        """Walk the input directory and return all non-ignored files."""
        if not input_path.is_dir():
            _LOGGER.warning("Input path does not exist: %s", input_path)
            return []
        found: list[Path] = []

        def on_error(exc: OSError) -> None:
            _LOGGER.warning(
                "Cannot read directory '%s': %s", exc.filename, exc.strerror
            )

        for dirpath, dirnames, filenames in os.walk(input_path, onerror=on_error):
            dirnames[:] = [d for d in dirnames if not self._is_ignored(d)]
            base = Path(dirpath)
            for name in filenames:
                if self._is_ignored(name):
                    continue
                path = base / name
                if path.is_file():
                    found.append(path)
        return sorted(found)

    def _has_links(self) -> bool:
        return any(
            self._pipeline.symlinks.iter_links(sym_lib.output_path)
            for sym_lib in self._pipeline.symlink_libraries
        )

    def _input_is_usable(self, library: LibraryConfig, has_files: bool) -> bool:
        """Guard against wiping all links when the source is not mounted.

        If the input directory is missing, or empty while symlinks exist,
        the most likely cause is an unmounted network share or disk. In that
        case every symlink would look stale, so the library is skipped.
        """
        if not library.input_path.is_dir():
            _LOGGER.error(
                "Input path '%s' of library '%s' is missing. Skipping the library "
                "and keeping all existing symlinks (is the share mounted?)",
                library.input_path,
                library.name,
            )
            return False
        if not has_files and self._has_links():
            _LOGGER.error(
                "Input path '%s' of library '%s' contains no files but its output "
                "directories contain symlinks. Skipping the library to protect "
                "them (is the share mounted?)",
                library.input_path,
                library.name,
            )
            return False
        return True

    def _probe(self, file_path: Path) -> MediaInfo | None:
        if self._cancel.is_set():
            return None
        for prober in self._pipeline.probers:
            info = prober.probe(file_path)
            if info is not None:
                return info
        return None

    def _probe_all(
        self,
        to_probe: list[tuple[Path, int, float]],
        infos: dict[Path, MediaInfo],
        result: ScanResult,
    ) -> None:
        """Probe *to_probe* in parallel and store results in *infos*/state."""
        total = len(to_probe)
        if not total:
            return
        state = self._pipeline.state
        workers = max(1, min(self._pipeline.probe_workers, total))
        _LOGGER.info("Probing %d new or changed files (%d workers)", total, workers)
        executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="probe")
        try:
            futures: dict[Future[MediaInfo | None], tuple[Path, int, float]] = {
                executor.submit(self._probe, path): (path, size, mtime)
                for path, size, mtime in to_probe
            }
            for idx, future in enumerate(as_completed(futures), 1):
                if self._cancel.is_set():
                    return
                path, size, mtime = futures[future]
                try:
                    info = future.result()
                except Exception:
                    _LOGGER.exception("Error probing '%s'", path)
                    info = None
                if info is None:
                    result.errors += 1
                    _LOGGER.warning("[%d/%d] Could not probe '%s'", idx, total, path)
                    continue
                cached = dataclasses.replace(
                    info, file_path=path, size=size, mtime=mtime
                )
                state.put(cached)
                infos[path] = cached
                result.probed += 1
                self._progress("probing", idx, total)
                _LOGGER.info(
                    "[%d/%d] Probed '%s': %s",
                    idx,
                    total,
                    path.name,
                    ", ".join(t.language for t in info.audio_tracks) or "no audio",
                )
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

    def process_library(self, library: LibraryConfig) -> ScanResult:
        """Run the full scan pipeline on a single library."""
        result = ScanResult()
        input_path = library.input_path
        self._library = library.name
        _LOGGER.info("Processing library '%s': %s", library.name, input_path)
        self._progress("discovering")

        files = self._discover_files(input_path)
        if not self._input_is_usable(library, bool(files)):
            result.errors += 1
            return result
        _LOGGER.info("Discovered %d files in '%s'", len(files), library.name)

        pre_filters = self._pipeline.pre_probe_filters
        sidecar_exts = self._pipeline.sidecar_extensions
        state = self._pipeline.state

        # Phase 1 – pre-filter and cache lookup (no probing)
        media: list[Path] = []
        sidecars_by_dir: dict[Path, list[Path]] = defaultdict(list)
        infos: dict[Path, MediaInfo] = {}
        to_probe: list[tuple[Path, int, float]] = []
        for file_path in files:
            if not all(f.matches(file_path) for f in pre_filters):
                result.filtered += 1
                if file_path.suffix.lower() in sidecar_exts:
                    sidecars_by_dir[file_path.parent].append(file_path)
                continue
            media.append(file_path)
            try:
                stat = file_path.stat()
            except OSError as exc:
                _LOGGER.error("Cannot stat '%s': %s", file_path, exc)
                result.errors += 1
                continue
            cached = state.get(file_path, stat.st_size, stat.st_mtime)
            if cached is not None:
                infos[file_path] = cached
                result.skipped += 1
            else:
                to_probe.append((file_path, stat.st_size, stat.st_mtime))

        # Phase 2 – probe new/changed files
        self._probe_all(to_probe, infos, result)
        if self._cancel.is_set():
            _LOGGER.warning(
                "Scan of '%s' cancelled; no symlinks were changed", library.name
            )
            return result

        # Phase 3 – reconcile every symlink library
        self._progress("linking")
        for sym_lib in self._pipeline.symlink_libraries:
            self._reconcile_symlink_library(
                library,
                sym_lib.output_path,
                sym_lib.filters,
                media,
                infos,
                sidecars_by_dir,
                result,
            )

        # Phase 4 – forget cache entries of files that no longer exist
        pruned = state.prune(input_path, set(files))
        if pruned:
            _LOGGER.debug("Pruned %d vanished files from the probe cache", pruned)

        _LOGGER.info(
            "Library '%s' complete: %d created, %d removed, %d unchanged, "
            "%d probed, %d skipped (cached), %d filtered (non-media), %d errors",
            library.name,
            result.created,
            result.removed,
            result.unchanged,
            result.probed,
            result.skipped,
            result.filtered,
            result.errors,
        )
        return result

    def _sidecars_for(
        self, media_path: Path, sidecars_by_dir: dict[Path, list[Path]]
    ) -> list[Path]:
        prefix = f"{media_path.stem}."
        return [
            p
            for p in sidecars_by_dir.get(media_path.parent, [])
            if p.name.startswith(prefix)
        ]

    def _reconcile_symlink_library(
        self,
        library: LibraryConfig,
        output_path: Path,
        filters: list[PostProbeFilter],
        media: list[Path],
        infos: dict[Path, MediaInfo],
        sidecars_by_dir: dict[Path, list[Path]],
        result: ScanResult,
    ) -> None:
        symlinks = self._pipeline.symlinks
        relative = self._pipeline.relative_symlinks
        input_path = library.input_path
        expected: set[Path] = set()
        preserve: set[Path] = set()
        created_before = result.created

        for file_path in media:
            sources = [file_path, *self._sidecars_for(file_path, sidecars_by_dir)]
            dests = [self._dest_path(s, input_path, output_path) for s in sources]
            info = infos.get(file_path)
            if info is None:
                # Probe failed: keep whatever links exist for this file.
                preserve.update(dests)
                continue
            if not all(f.matches(info) for f in filters):
                continue
            for source, dest in zip(sources, dests, strict=True):
                expected.add(dest)
                try:
                    if symlinks.ensure_link(source, dest, relative=relative):
                        result.created += 1
                        result.record_change("created", dest, source)
                    else:
                        result.unchanged += 1
                except OSError as exc:
                    _LOGGER.error("Cannot create symlink '%s': %s", dest, exc)
                    result.errors += 1

        result.links[str(output_path)] = len(expected)
        plan = symlinks.plan_removals(output_path, expected, input_path, preserve)
        guard = self._pipeline.removal_guard
        if (
            guard is not None
            and not self._pipeline.force
            and guard.blocks(len(plan.removals), plan.existing)
        ):
            _LOGGER.error(
                "Removal guard: refusing to remove %d of %d symlinks (%.0f%%) from "
                "'%s' (limit %.0f%%). If this is intended (e.g. changed filters), "
                "run 'boomarr scan --force' once.",
                len(plan.removals),
                plan.existing,
                100 * len(plan.removals) / max(plan.existing, 1),
                output_path,
                guard.max_percent,
            )
            result.blocked += 1
            if result.created > created_before:
                result.changed_outputs.add(str(output_path))
            return
        removed_links = symlinks.apply_removals(output_path, plan.removals)
        for link in removed_links:
            result.record_change("removed", link)
        removed = len(removed_links)
        result.removed += removed
        if removed or result.created > created_before:
            result.changed_outputs.add(str(output_path))
        if removed:
            _LOGGER.info("Removed %d symlinks from '%s'", removed, output_path)

    def clean_library(self, library: LibraryConfig) -> int:
        """Remove stale symlinks only (for the clean command)."""
        input_path = library.input_path
        has_files = input_path.is_dir() and any(input_path.iterdir())
        if not self._input_is_usable(library, has_files):
            return 0
        symlinks = self._pipeline.symlinks
        total = 0
        for sym_lib in self._pipeline.symlink_libraries:
            total += symlinks.clean_stale(sym_lib.output_path)
        _LOGGER.info("Clean '%s': removed %d stale symlinks", library.name, total)
        return total
