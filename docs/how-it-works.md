# How it works

```
            ┌───────────── probe cache (SQLite) ─────────────┐
            │  path, size, mtime → audio tracks              │
            └──────────────▲──────────────────┬──────────────┘
                           │ new/changed      │ unchanged
/media/movies ──discover──►│ files only       │ files
 (read-only)   + ignore    │ (ffprobe, N      │
               + pre-probe │  in parallel)    ▼
                 filters   └──────────► audio tracks ──► filters of each
                                                         symlink library
                                                              │
                                   desired set of links ◄─────┘
                                              │
                               reconcile output directory
                        create/update missing links, remove unwanted ones
                                              ▼
                             /media/filtered/movies-deu
```

Every scan is a **full reconciliation** instead of an incremental update:

1. **Discover** all files below `input_path`, skipping `ignore_patterns`.
2. **Pre-filter** by extension; non-media files are only considered as
   sidecars (subtitles).
3. **Look up** every media file in the probe cache by path, size and
   modification time. Only new or changed files are probed with ffprobe
   (`probe_workers` at a time).
4. **Evaluate** the cached audio tracks against the *current* filters of
   every symlink library. This is why config changes apply immediately.
5. **Reconcile** each output directory: create or atomically update the
   desired links, then remove every other symlink that points into this
   library's input directory (or is broken).
6. **Prune** cache entries of files that no longer exist.

Because the result depends only on the current state of the source files
and the config, the output is always correct after a scan, no matter what
happened before (crashes, config changes, links deleted by hand, …).

## Safety guarantees

Boomarr is designed so that it cannot damage your media or your libraries:

- **Sources are never written.** Boomarr refuses to start if an input
  directory is writable, and it only ever reads media files.
- **Only symlinks are deleted.** Regular files and directories in output
  folders are never removed (only directories that became empty).
- **Only its own symlinks are deleted.** Symlinks pointing somewhere other
  than the library's input directory are left alone.
- **Unmounted shares are detected.** If an input directory is missing, or
  empty while its output still contains links, the library is skipped and
  every link is kept. Without this, a NAS reboot would look like "all files
  deleted" and empty your filtered libraries (and possibly make your media
  server forget their metadata).
- **Probe failures keep links.** If a file cannot be probed (corrupt,
  temporarily unreadable), its existing link is kept.
- **Atomic updates.** A changed link is replaced with `rename(2)`, so the
  media server never sees it disappear.
- **Graceful shutdown.** `SIGTERM` stops a running scan within seconds:
  pending probes are cancelled and a library whose probing was interrupted
  is left untouched. Probe results gathered so far are kept.
- **Crash-safe cache.** SQLite in WAL mode; a corrupt or outdated cache is
  rebuilt automatically without touching any links.
- **Conflicting configs are rejected** (overlapping inputs/outputs,
  duplicate or nested outputs, path traversal in names).
- **Removal guard.** Removing more than half of a folder's links at once is
  refused until confirmed with `boomarr scan --force`.
- **Dry run.** `boomarr scan --dry-run` shows what would change.

## Commands

| Command | Description |
| --- | --- |
| `boomarr watch` | Run continuously, scanning on every trigger (Docker default). |
| `boomarr scan [--dry-run] [--force]` | One full scan, then exit. `--force` bypasses the removal guard once. |
| `boomarr clean` | Only remove broken symlinks. |
| `boomarr status [--json]` | Last scan (time, duration, result), probe cache statistics and languages found, active triggers, and for every output folder its link count and filters. Tables in a terminal, plain text when piped. |
| `boomarr paths` | Print writable directories (used by the Docker entrypoint). |
| `boomarr healthcheck` | Exit 0 if `watch` is alive (Docker/Kubernetes). |
| `boomarr version` | Print the version. |
