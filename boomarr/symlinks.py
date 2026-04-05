"""Symlink management module.

Handles creation, validation, and cleanup of symlinks used to mirror media
library structures. Provides safe operations for maintaining symlink integrity
and resolving link targets.
"""

import logging
import os
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


class SymlinkManager:
    """Creates, validates, and cleans up symlinks for filtered media libraries."""

    def ensure_link(self, source: Path, dest: Path) -> bool:
        """Ensure a symlink at ``dest`` pointing to ``source`` exists.

        Creates parent directories as needed. Uses relative symlink targets
        for portability across mount points.

        Returns True if a new link was created, False if it already existed
        and was correct.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)

        target = os.path.relpath(source, dest.parent)

        if dest.is_symlink():
            existing = os.readlink(dest)
            if existing == target:
                return False
            _LOGGER.debug("Updating symlink '%s' -> '%s'", dest, target)
            dest.unlink()
        elif dest.exists():
            _LOGGER.warning(
                "Cannot create symlink at '%s': path exists and is not a symlink", dest
            )
            return False

        dest.symlink_to(target)
        _LOGGER.debug("Created symlink '%s' -> '%s'", dest, target)
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

        Returns the number of stale symlinks removed.
        """
        removed = 0
        if not output_dir.is_dir():
            return removed

        for path in output_dir.rglob("*"):
            if path.is_symlink() and not path.resolve().exists():
                path.unlink()
                _LOGGER.debug("Cleaned stale symlink '%s'", path)
                removed += 1

        return removed
