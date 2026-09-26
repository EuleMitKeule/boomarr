"""Symlink management module.

Handles creation, validation, and cleanup of symlinks used to mirror media
library structures. Regular files and directories inside output folders are
never deleted; only symlinks (and directories left empty by removing them).
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

_TMP_SUFFIX = ".boomarr-tmp"


@dataclass
class RemovalPlan:
    """Symlinks a reconciliation would remove, plus the number of existing links."""

    removals: list[tuple[Path, str]] = field(default_factory=list)
    existing: int = 0


def link_target(source: Path, dest: Path, *, relative: bool = False) -> str:
    """Return the symlink target string for a link at *dest* to *source*."""
    if relative:
        return os.path.relpath(source, dest.parent)
    return str(source)


def resolve_link_target(link: Path) -> Path:
    """Return the (lexically normalised, absolute) target of symlink *link*."""
    raw = os.readlink(link)
    return Path(os.path.normpath(os.path.join(link.parent, raw)))


class SymlinkManager:
    """Creates, validates, and cleans up symlinks for filtered media libraries.

    Args:
        dry_run: Only log what would be changed, never touch the filesystem.
    """

    def __init__(self, *, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    def ensure_link(self, source: Path, dest: Path, *, relative: bool = False) -> bool:
        """Ensure a symlink at ``dest`` pointing to ``source`` exists.

        Creates parent directories as needed. An existing symlink with a
        different target is replaced atomically, so the media server never
        sees the file disappear.

        Returns True if a link was created or changed, False if it already
        existed and was correct (or a non-symlink blocks the path).
        """
        target = link_target(source, dest, relative=relative)

        if dest.is_symlink():
            if os.readlink(dest) == target:
                return False
            if self.dry_run:
                _LOGGER.info(
                    "[dry-run] Would update symlink '%s' -> '%s'", dest, target
                )
                return True
            tmp = dest.with_name(f".{dest.name}{_TMP_SUFFIX}")
            tmp.unlink(missing_ok=True)
            os.symlink(target, tmp)
            os.replace(tmp, dest)
            _LOGGER.debug("Updated symlink '%s' -> '%s'", dest, target)
            return True

        if dest.exists():
            _LOGGER.warning(
                "Cannot create symlink at '%s': path exists and is not a symlink", dest
            )
            return False

        if self.dry_run:
            _LOGGER.info("[dry-run] Would create symlink '%s' -> '%s'", dest, target)
            return True

        dest.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, dest)
        _LOGGER.debug("Created symlink '%s' -> '%s'", dest, target)
        return True

    def remove_link(self, dest: Path) -> bool:
        """Remove a symlink at ``dest`` if it exists.

        Returns True if a symlink was (or, in dry-run mode, would be) removed.
        """
        if not dest.is_symlink():
            return False
        if self.dry_run:
            _LOGGER.info("[dry-run] Would remove symlink '%s'", dest)
            return True
        dest.unlink()
        _LOGGER.debug("Removed symlink '%s'", dest)
        return True

    def iter_links(self, output_dir: Path) -> list[Path]:
        """Return all symlinks below *output_dir* (without following links)."""
        links: list[Path] = []
        if not output_dir.is_dir():
            return links
        for dirpath, dirnames, filenames in os.walk(
            output_dir, onerror=_log_walk_error
        ):
            base = Path(dirpath)
            for name in (*filenames, *dirnames):
                path = base / name
                if path.is_symlink():
                    links.append(path)
        return links

    def reconcile(
        self,
        output_dir: Path,
        expected: set[Path],
        owned_root: Path,
        preserve: set[Path] | None = None,
    ) -> int:
        """Remove symlinks below *output_dir* that are no longer wanted.

        A symlink is removed when it is neither in *expected* nor *preserve*
        and it either is broken or points into *owned_root* (the library's
        input directory). Symlinks pointing somewhere else were not created
        by Boomarr and are left untouched.

        Returns the number of removed symlinks.
        """
        plan = self.plan_removals(output_dir, expected, owned_root, preserve)
        return len(self.apply_removals(output_dir, plan.removals))

    def plan_removals(
        self,
        output_dir: Path,
        expected: set[Path],
        owned_root: Path,
        preserve: set[Path] | None = None,
    ) -> RemovalPlan:
        """Compute which symlinks :meth:`reconcile` would remove."""
        keep = expected | (preserve or set())
        plan = RemovalPlan()
        for link in self.iter_links(output_dir):
            plan.existing += 1
            if link in keep:
                continue
            try:
                target = resolve_link_target(link)
            except OSError:
                continue
            broken = not link.exists()
            if not broken and not target.is_relative_to(owned_root):
                continue
            plan.removals.append((link, "stale" if broken else "unwanted"))
        return plan

    def apply_removals(
        self, output_dir: Path, removals: list[tuple[Path, str]]
    ) -> list[Path]:
        """Remove the planned symlinks and prune directories left empty.

        Returns the symlinks that were (or, in dry-run mode, would be) removed.
        """
        removed = [link for link, reason in removals if self._remove(link, reason)]
        self.prune_empty_dirs(output_dir)
        return removed

    def clean_stale(self, output_dir: Path) -> int:
        """Remove all broken symlinks under ``output_dir`` recursively.

        After removing stale symlinks, empty subdirectories left behind are
        also pruned (bottom-up so nested empty trees collapse fully).

        Returns the number of stale symlinks removed.
        """
        removed = 0
        for link in self.iter_links(output_dir):
            if not link.exists() and self._remove(link, "stale"):
                removed += 1
        self.prune_empty_dirs(output_dir)
        return removed

    def prune_empty_dirs(self, output_dir: Path) -> None:
        """Remove empty directories below (not including) *output_dir*."""
        if self.dry_run or not output_dir.is_dir():
            return
        for dirpath, _, _ in os.walk(
            output_dir, topdown=False, onerror=_log_walk_error
        ):
            path = Path(dirpath)
            if path == output_dir or path.is_symlink():
                continue
            try:
                path.rmdir()
                _LOGGER.debug("Pruned empty directory '%s'", path)
            except OSError:
                pass

    def _remove(self, link: Path, reason: str) -> bool:
        if self.dry_run:
            _LOGGER.info("[dry-run] Would remove %s symlink '%s'", reason, link)
            return True
        try:
            link.unlink()
        except FileNotFoundError:
            return False
        except OSError as exc:
            _LOGGER.error("Failed to remove %s symlink '%s': %s", reason, link, exc)
            return False
        _LOGGER.info("Removed %s symlink '%s'", reason, link)
        return True


def _log_walk_error(exc: OSError) -> None:
    _LOGGER.warning("Cannot read directory '%s': %s", exc.filename, exc.strerror)
