"""Library processor module.

Orchestrates the scan/filter/symlink workflow for a single library using
the subsystems provided by a Pipeline.
"""

import logging
from pathlib import Path

from boomarr.config import LibraryConfig
from boomarr.models import ScanResult
from boomarr.pipeline import Pipeline

_LOGGER = logging.getLogger(__name__)


class LibraryProcessor:
    """Processes a single library through the configured pipeline.

    Discovers media files, applies pre-probe filters, probes metadata
    via a fallback chain, evaluates post-probe filters for each symlink
    library, and manages symlinks accordingly.
    """

    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline

    def _dest_path(self, source: Path, input_path: Path, output_path: Path) -> Path:
        """Compute the destination symlink path mirroring the input structure."""
        relative = source.relative_to(input_path)
        return output_path / relative

    def _discover_files(self, input_path: Path) -> list[Path]:
        """Walk the input directory and return all files."""
        if not input_path.is_dir():
            _LOGGER.warning("Input path does not exist: %s", input_path)
            return []
        return sorted(p for p in input_path.rglob("*") if p.is_file())

    def process_library(self, library: LibraryConfig) -> ScanResult:
        """Run the full scan pipeline on a single library."""
        result = ScanResult()
        _LOGGER.info(
            "Processing library '%s': %s",
            library.name,
            library.input_path,
        )

        files = self._discover_files(library.input_path)
        total_files = len(files)
        _LOGGER.info("Discovered %d files in '%s'", total_files, library.name)

        probers = self._pipeline.probers
        pre_filters = self._pipeline.pre_probe_filters
        sym_libs = self._pipeline.symlink_libraries
        symlinks = self._pipeline.symlinks
        state = self._pipeline.state

        # Phase 1 – Preprocessing: filter and check state without probing
        to_probe: list[tuple[Path, int, float]] = []
        for file_path in files:
            if not all(f.matches(file_path) for f in pre_filters):
                result.filtered += 1
                continue

            try:
                stat = file_path.stat()
                file_size = stat.st_size
                file_mtime = stat.st_mtime
            except Exception as e:
                _LOGGER.exception("Error processing '%s': %s", file_path, e)
                result.errors += 1
                continue

            if state.is_unchanged(file_path, file_size, file_mtime):
                result.skipped += 1
                continue

            to_probe.append((file_path, file_size, file_mtime))

        # Phase 2 – Probing: only files that passed preprocessing
        total = len(to_probe)
        for idx, (file_path, file_size, file_mtime) in enumerate(to_probe, 1):
            try:
                _LOGGER.info(
                    "[%d/%d] Probing '%s'",
                    idx,
                    total,
                    file_path.name,
                )

                info = None
                for prober in probers:
                    info = prober.probe(file_path)
                    if info is not None:
                        break

                if info is None:
                    result.errors += 1
                    continue

                matched_any = False
                for sym_lib in sym_libs:
                    dest = self._dest_path(
                        file_path,
                        library.input_path,
                        sym_lib.output_path,
                    )
                    passed = all(f.matches(info) for f in sym_lib.filters)

                    if passed:
                        matched_any = True
                        created = symlinks.ensure_link(file_path, dest)
                        if created:
                            result.created += 1
                        else:
                            result.unchanged += 1
                    else:
                        removed = symlinks.remove_link(dest)
                        if removed:
                            result.removed += 1
                        else:
                            result.unchanged += 1

                state.update(file_path, file_size, file_mtime, matched=matched_any)

            except Exception as e:
                _LOGGER.exception("Error processing '%s': %s", file_path, e)
                result.errors += 1

        # Phase 3 – Cleanup
        for sym_lib in sym_libs:
            stale = symlinks.clean_stale(sym_lib.output_path)
            result.removed += stale
            if stale:
                _LOGGER.info(
                    "Cleaned %d stale symlinks in '%s'",
                    stale,
                    sym_lib.output_path,
                )

        _LOGGER.info(
            "Library '%s' complete: %d created, %d removed, %d unchanged, "
            "%d skipped (cached), %d filtered (non-media), %d errors",
            library.name,
            result.created,
            result.removed,
            result.unchanged,
            result.skipped,
            result.filtered,
            result.errors,
        )
        return result

    def clean_library(self, library: LibraryConfig) -> int:
        """Remove stale symlinks only (for the clean command)."""
        symlinks = self._pipeline.symlinks
        total = 0
        for sym_lib in self._pipeline.symlink_libraries:
            stale = symlinks.clean_stale(sym_lib.output_path)
            total += stale
        _LOGGER.info("Clean '%s': removed %d stale symlinks", library.name, total)
        return total
