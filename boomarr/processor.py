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

    Discovers media files, probes metadata, applies filters, and manages
    symlinks. Reused by scan, watch, and clean commands via different
    Pipeline configurations.
    """

    def __init__(self, pipeline: Pipeline) -> None:
        self._pipeline = pipeline

    def _dest_path(self, source: Path, library: LibraryConfig) -> Path:
        """Compute the destination symlink path mirroring the input structure."""
        relative = source.relative_to(library.input_path)
        return library.output_path / relative

    def _discover_files(self, input_path: Path) -> list[Path]:
        """Walk the input directory and return all files."""
        if not input_path.is_dir():
            _LOGGER.warning("Input path does not exist: %s", input_path)
            return []
        return sorted(p for p in input_path.rglob("*") if p.is_file())

    def process_library(self, library: LibraryConfig) -> ScanResult:
        """Run the full scan pipeline on a single library.

        Steps:
            1. Discover all files under input_path
            2. For each file:
               a. Check state — skip if unchanged
               b. Apply pre-probe filters (e.g. file extension)
               c. Probe metadata
               d. Apply post-probe filters (e.g. audio language)
               e. Create or remove symlink accordingly
               f. Update state
            3. Clean stale symlinks in output_path
        """
        result = ScanResult()
        _LOGGER.info(
            "Processing library '%s': %s -> %s",
            library.name,
            library.input_path,
            library.output_path,
        )

        files = self._discover_files(library.input_path)
        _LOGGER.info("Discovered %d files in '%s'", len(files), library.name)

        prober = self._pipeline.prober
        filters = self._pipeline.filters
        symlinks = self._pipeline.symlinks
        state = self._pipeline.state

        for file_path in files:
            dest = self._dest_path(file_path, library)

            try:
                info = prober.probe(file_path)
                if info is None:
                    result.errors += 1
                    continue

                if state.is_unchanged(file_path, info.size, info.mtime):
                    result.skipped += 1
                    continue

                passed = all(f.matches(info, library) for f in filters)

                if passed:
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

                state.update(file_path, info.size, info.mtime, matched=passed)

            except Exception:
                _LOGGER.exception("Error processing '%s'", file_path)
                result.errors += 1

        stale = symlinks.clean_stale(library.output_path)
        result.removed += stale
        if stale:
            _LOGGER.info("Cleaned %d stale symlinks in '%s'", stale, library.name)

        _LOGGER.info(
            "Library '%s' complete: %d created, %d removed, %d unchanged, "
            "%d skipped, %d errors",
            library.name,
            result.created,
            result.removed,
            result.unchanged,
            result.skipped,
            result.errors,
        )
        return result

    def clean_library(self, library: LibraryConfig) -> int:
        """Remove stale symlinks only (for the clean command)."""
        symlinks = self._pipeline.symlinks
        stale = symlinks.clean_stale(library.output_path)
        _LOGGER.info("Clean '%s': removed %d stale symlinks", library.name, stale)
        return stale
