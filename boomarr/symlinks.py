"""Symlink management module.

Handles creation, validation, and cleanup of symlinks used to mirror media
library structures. Provides safe operations for maintaining symlink integrity
and resolving link targets.
"""

import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


class SymlinkManager:
    """Creates, validates, and cleans up symlinks for filtered media libraries."""

    def ensure_link(self, source: Path, dest: Path) -> bool:
        """Ensure a symlink at ``dest`` pointing to ``source`` exists.

        Creates parent directories as needed. Uses absolute symlink targets.

        Returns True if a new link was created, False if it already existed
        and was correct.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)

        if dest.is_symlink():
            if dest.resolve() == source.resolve():
                return False
            _LOGGER.debug("Updating symlink '%s' -> '%s'", dest, source)
            dest.unlink()
        elif dest.exists():
            _LOGGER.warning(
                "Cannot create symlink at '%s': path exists and is not a symlink", dest
            )
            return False

        dest.symlink_to(source)
        _LOGGER.debug("Created symlink '%s' -> '%s'", dest, source)
        return True

    def remove_link(self, dest: Path) -> bool:
        """Remove a symlink at ``dest`` if it exists.

        Returns True if a symlink was removed.
        """
        if dest.is_symlink():
            dest.unlink()
            _LOGGER.debug("Removed symlink '%s'", dest)
            return True
        return False

    def clean_stale(self, output_dir: Path) -> int:
        """Remove all broken symlinks under ``output_dir`` recursively.

        After removing stale symlinks, empty subdirectories left behind are
        also pruned (bottom-up so nested empty trees collapse fully).

        Returns the number of stale symlinks removed.
        """
        removed = 0
        if not output_dir.is_dir():
            return removed

        for path in list(output_dir.rglob("*")):
            if path.is_symlink() and not path.exists():
                path.unlink()
                _LOGGER.debug("Removed stale symlink '%s'", path)
                removed += 1

        subdirs = sorted(
            (p for p in output_dir.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        )
        for dirpath in subdirs:
            try:
                dirpath.rmdir()
                _LOGGER.debug("Pruned empty directory '%s'", dirpath)
            except OSError:
                pass

        return removed
