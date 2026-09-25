# Configuration reference

Boomarr is configured with a single YAML file, `boomarr.yml`, inside the
config directory (`/config` in Docker, `./config` otherwise). If the file
does not exist, a commented template is created on first start.

Unknown or misspelled options never prevent startup, but are logged as a
warning (e.g. `Unknown config option 'libraries[0].symlink_libraries[0].filters[0].langauges'`).

- [Minimal example](#minimal-example)
- [Top-level options](#top-level-options)
- [Libraries](#libraries)
- [Symlink libraries](#symlink-libraries)
- [Filters](#filters)
- [Triggers (watch mode)](#triggers-watch-mode)
- [HTTP server: webhooks, metrics, status](#http-server-webhooks-metrics-status)
- [Removal guard](#removal-guard)
- [Notifications](#notifications)
- [Media server refresh](#media-server-refresh)
- [Probers](#probers)
- [Database (probe cache)](#database-probe-cache)
- [Logging](#logging)
- [Environment variables and CLI options](#environment-variables-and-cli-options)
- [Output directory naming](#output-directory-naming)
- [Validation rules](#validation-rules)

## Minimal example

```yaml
output_path: /media/filtered

libraries:
  - name: Movies
    input_path: /media/movies
    symlink_libraries:
      - filters:
          - type: audio_language
            languages: [deu]
```

This creates `/media/filtered/movies-deu`, mirroring the folder structure of
`/media/movies` but containing only (symlinks to) files with a German audio
track.

## Top-level options

| Option | Default | Description |
| --- | --- | --- |
| `output_path` | – | Base directory for all symlink libraries. Required unless every library (or every symlink library) sets its own `output_path`. |
| `libraries` | `[]` | List of [libraries](#libraries). |
| `triggers` | `[schedule]` | [Triggers](#triggers-watch-mode) for `boomarr watch`. |
| `sidecar_extensions` | `[.srt, .ass, .ssa, .sub, .idx, .vtt, .sup, .smi]` | External files that are linked together with a matching media file when their name starts with the media file's name (`Movie.mkv` → `Movie.de.srt`, `Movie.en.forced.ass`). Set `[]` to disable. |
| `ignore_patterns` | see below | [fnmatch](https://docs.python.org/3/library/fnmatch.html) patterns of file and directory **names** that are skipped while scanning. |
| `relative_symlinks` | `false` | Create relative symlinks (`../../movies/Film/Film.mkv`) instead of absolute ones. See [media servers](media-servers.md#path-mapping). |
| `removal_guard` | 50 % / 20 | [Protection against mass removals](#removal-guard). |
| `server` | disabled | [HTTP server](#http-server-webhooks-metrics-status) for webhooks, metrics and status. |
| `notifications` | none | [Apprise notifications](#notifications). |
| `media_servers` | `[]` | [Plex/Jellyfin/Emby refresh](#media-server-refresh) after changes. |
| `probe_workers` | `4` | Number of files probed in parallel (1–64). Only new or changed files are probed. Lower it for slow spinning disks, raise it for SSD/NVMe. |
| `probers` | `[ffprobe]` | [Probers](#probers) used to read audio tracks. |
| `pre_probe_filters` | `[file_extension]` | Cheap filters applied before probing. |
| `database` | `sqlite` | [Probe cache](#database-probe-cache). |
| `watch.debounce` | `2.0` | Seconds to wait for more trigger events before a scan starts. |
| `general.tz` | `UTC` | Timezone for log timestamps (also `TZ`). |
| `logging` | | See [logging](#logging). |

Default `ignore_patterns`:

```yaml
ignore_patterns:
  - ".*"                         # hidden files/dirs, macOS "._" files, .Trash-*
  - "@eaDir"                     # Synology thumbnails
  - "#recycle"                   # Synology recycle bin
  - "#snapshot"                  # Synology snapshots
  - "$RECYCLE.BIN"
  - "System Volume Information"
  - "lost+found"
  - "Plex Versions"              # Plex optimized versions
```

Setting `ignore_patterns` replaces the list; copy the defaults if you only
want to add a pattern.

## Libraries

A library is a source directory that is scanned recursively.

```yaml
libraries:
  - name: Movies                  # required, unique, used for folder names
    input_path: /media/movies     # required, must be mounted read-only
    output_path: /media/filtered  # optional, overrides the global output_path
    symlink_libraries: [...]      # required, at least one

    # Optional per-library overrides of the global options:
    probers: [ffprobe]
    pre_probe_filters: [file_extension]
    sidecar_extensions: [.srt]
    ignore_patterns: [".*", "Extras"]
    relative_symlinks: true
```

## Symlink libraries

Each symlink library is one output folder with its own filters. A file is
linked if it passes **all** filters of the symlink library.

```yaml
symlink_libraries:
  # Automatic name: <output_path>/<library-name-slug>-<filter suffixes>
  - filters:
      - type: audio_language
        languages: [deu]

  # Fixed folder name inside the library's output path
  - name: English
    filters:
      - type: audio_language
        languages: [eng]

  # Fully custom location
  - output_path: /media/kids
    filters:
      - type: audio_language
        languages: [deu]
```

## Filters

### `audio_language`

Matches files by the languages of their audio tracks.

```yaml
- type: audio_language
  languages:
    - deu                       # shorthand for {code: deu}
    - code: eng
      aliases: [und]            # tracks tagged "und" (undetermined) count as English
  mode: any                     # any (default) | all
  suffix: german-english        # optional, overrides the automatic folder suffix
```

| Option | Default | Description |
| --- | --- | --- |
| `languages` | – | At least one language. Plain strings or `{code, aliases}`. |
| `mode` | `any` | `any`: at least one configured language is present. `all`: every configured language (or one of its aliases) is present, e.g. for "original + German dub" libraries. |
| `suffix` | joined codes | Folder suffix used for automatic output naming. |

**Language codes are normalised.** Matroska files store ISO 639-2/B codes
(`ger`, `fre`, `dut`), other containers often use ISO 639-2/T (`deu`, `fra`,
`nld`), ISO 639-1 (`de`) or IETF tags (`de-DE`). Boomarr treats all of these
as the same language, both in your config and in the files, so `deu`, `ger`,
`de` and `de-DE` are interchangeable.

Tracks without a language tag are reported as `und`. Add `und` as an alias if
your untagged files are in a known language.

### `resolution`

```yaml
- type: resolution
  min_height: 2160      # or "4k", "uhd", "1080p", "fhd", "720p", "hd", "sd"
  max_height: 2160      # optional upper bound
```

The resolution is compared as its 16:9 equivalent, so cropped "scope"
releases (1920×800) count as 1080p. A tolerance of 5 % applies. Automatic
suffix: `2160p-plus`, `max-720p` or `720p-1080p`.

### `video_codec` / `audio_codec`

```yaml
- type: video_codec
  codecs: [hevc, av1]           # h265/x265 = hevc, avc/x264 = h264
- type: audio_codec
  codecs: [truehd, eac3, dts]   # e-ac-3 = eac3, ac-3 = ac3
```

A file matches if at least one video (resp. audio) track uses one of the
codecs. Suffix: the sorted codec names.

### `audio_channels`

```yaml
- type: audio_channels
  min_channels: 6               # 5.1 or more
```

### `invert`

Every filter accepts `invert: true` to negate it, e.g. "everything that has
no English audio track":

```yaml
- type: audio_language
  languages: [eng]
  invert: true                  # automatic suffix: not-eng
```

Filters of a symlink library are combined with AND, so for example
"German 4K with surround sound" is:

```yaml
- name: German UHD
  filters:
    - {type: audio_language, languages: [deu]}
    - {type: resolution, min_height: 4k}
    - {type: audio_channels, min_channels: 6}
```

### `file_extension` (pre-probe)

Only files with these extensions are probed. Case and leading dot do not
matter.

```yaml
pre_probe_filters:
  - type: file_extension
    extensions: [mkv, mp4, avi, m4v, ts, wmv, flv, mov, webm]   # default
```

## Triggers (watch mode)

`boomarr watch` runs until stopped and scans whenever a trigger fires. All
triggers share one queue; events arriving within `watch.debounce` seconds
are collapsed into one scan. Unchanged files are served from the probe
cache, so frequent scans are cheap.

### `schedule`

```yaml
triggers:
  - type: schedule
    interval: 600        # seconds between scans (default 600)
    run_on_start: true   # scan immediately on startup (default true)
```

## HTTP server: webhooks, metrics, status

`boomarr watch` can run a small built-in HTTP server:

```yaml
server:
  enabled: true
  host: 0.0.0.0          # default
  port: 9797             # default
  api_key: change-me     # optional, falls back to BOOMARR_API_KEY
  metrics_auth: false    # require the API key for /metrics too
```

| Endpoint | Auth | Description |
| --- | --- | --- |
| `GET /health` | no | Liveness check, returns `{"status": "ok"}`. |
| `GET /metrics` | if `metrics_auth` | [Prometheus](https://prometheus.io/) metrics. |
| `GET /api/v1/status` | yes | Last scan result as JSON. |
| `POST /api/v1/scan` | yes | Queue a full scan. |
| `POST /api/v1/webhook/<name>` | yes | Same, `<name>` (e.g. `sonarr`) is only used for logging. |

The API key can be sent as `X-Api-Key` header, `?apikey=` query parameter,
`Authorization: Bearer <key>`, or as the **password** of HTTP basic auth.
The latter is what Sonarr/Radarr offer:

> Sonarr/Radarr → Settings → Connect → **+** → Webhook
> - URL: `http://boomarr:9797/api/v1/webhook/sonarr`
> - Method: `POST`
> - Password: your API key (username can be anything)
> - Triggers: *On File Import*, *On File Upgrade*, *On Rename*, *On Delete*

Without an API key anyone who can reach the port can trigger scans (they
cannot do anything else). Keep the port on an internal network.

Metrics include `boomarr_scans_total{status}`, `boomarr_scan_duration_seconds`,
`boomarr_last_scan_timestamp_seconds`, `boomarr_links{output}`,
`boomarr_links_created_total`, `boomarr_links_removed_total`,
`boomarr_files_probed_total`, `boomarr_errors_total`,
`boomarr_removal_guard_blocked_total`, `boomarr_cache_entries` and
`boomarr_build_info`. A useful alert:
`time() - boomarr_last_scan_timestamp_seconds > 3600`.

The older `triggers: [{type: webhook, ...}]` form still works and is turned
into a `server` section (a deprecation warning is logged).

## Removal guard

Mass removals are almost always an accident (a share mounted empty, a
wrong path, a filter typo). A scan therefore refuses to remove symlinks from
an output directory when it would remove **more than `min_count` links and
more than `max_percent` of them**:

```yaml
removal_guard:
  max_percent: 50        # default; 100 disables the guard
  min_count: 20          # default; small changes are always allowed
```

The scan logs an error, counts the output as `blocked` (metric
`boomarr_removal_guard_blocked_total`, notification) and leaves the links
alone; new links are still created. If the removals are intended, e.g.
after changing filters, run once:

```bash
docker exec boomarr boomarr scan --force
```

## Notifications

Boomarr sends notifications through [Apprise](https://github.com/caronc/apprise/wiki),
which supports Telegram, Discord, Slack, Matrix, ntfy, Gotify, Pushover,
e-mail and ~100 more services.

```yaml
notifications:
  urls:                  # or BOOMARR_NOTIFY_URLS (whitespace separated)
    - tgram://bottoken/ChatID
    - ntfys://ntfy.sh/my-boomarr
  on_errors: true        # default: scan failed or files could not be probed
  on_blocked: true       # default: the removal guard blocked a removal
  on_changes: false      # links were created or removed
```

## Media server refresh

After a scan changed an output directory, Boomarr can tell your media server
to rescan exactly that folder instead of waiting for its schedule:

```yaml
media_servers:
  - type: plex
    url: http://plex:32400
    token: your-plex-token            # https://support.plex.tv/articles/204059436
  - type: jellyfin                    # or: emby
    url: http://jellyfin:8096
    api_key: your-api-key             # Dashboard → API Keys
    # Only needed if the media server sees the output under another path:
    path_mappings:
      - local: /data/filtered         # path inside Boomarr
        remote: /media/filtered       # same folder inside the media server
```

- **Plex:** every library section whose folder contains (or is inside) a
  changed output directory gets a partial scan of that folder.
- **Jellyfin/Emby:** the changed folders are reported via
  `/Library/Media/Updated`, which triggers a targeted scan.

Failures are logged and never affect the scan.

## Probers

Probers read the audio tracks of a file. They form a fallback chain: the
first prober that returns a result wins.

```yaml
probers:
  - type: ffprobe
    path: ffprobe        # executable name or absolute path
    timeout: 60          # seconds per file
```

Boomarr checks at startup that ffprobe is available and exits with a clear
error otherwise. The Docker image ships a static ffprobe build.

### Sonarr and Radarr probers

Sonarr and Radarr already know the audio languages of every file they
imported. Asking them is much faster than probing, especially on network
storage:

```yaml
libraries:
  - name: Movies
    input_path: /data/media/movies
    probers:
      - type: radarr
        url: http://radarr:7878
        api_key: your-radarr-api-key
        path_mappings:                # only if Radarr uses other paths
          - local: /data/media/movies
            remote: /movies
        cache_ttl: 300                # seconds the library index is reused
      - ffprobe                       # fallback for files Radarr doesn't know
    symlink_libraries: [...]
```

Boomarr fetches the whole library in one request (Sonarr: one per series),
caches it for `cache_ttl` seconds and maps paths with `path_mappings`. Files
Sonarr/Radarr do not know, or whose languages are empty, go to the next
prober. If the server is unreachable, Boomarr logs a warning and falls back
as well.

## Database (probe cache)

```yaml
database:
  type: sqlite           # default
  dir: /config           # default: the config directory
  file_name: boomarr.db
```

or

```yaml
database:
  type: memory           # nothing persisted, every restart probes everything
```

The cache stores the audio tracks of every probed file keyed by path, size
and modification time. **Filters are never cached**: changing languages,
adding a symlink library or deleting links by hand takes effect on the next
scan without probing a single file again. Entries of deleted files are
pruned automatically. The cache can be deleted at any time; the next scan
simply re-probes all files.

## Logging

```yaml
logging:
  level: info                # debug | info | warning | error | critical
  color: true                # only applied when stderr is a terminal
  format: "%(asctime)s | %(levelname)-8s | %(name)s: %(message)s"
  date_format: "%Y-%m-%d %H:%M:%S"
  file_name: boomarr.log     # empty string disables file logging
  rotation:
    enabled: true
    max_bytes: 10485760
    backup_count: 3
    rotate_on_start: true
```

The log directory can only be set via `LOG_DIR` / `--log-dir` (default
`<config>/logs` in Docker); set it to an empty string to disable file logging.

## Environment variables and CLI options

| Env var | CLI option | Description |
| --- | --- | --- |
| `CONFIG_DIR` | `--config-dir` | Config directory (`/config` in Docker). |
| `CONFIG_FILE_NAME` | `--config-file-name` | Config file name (`boomarr.yml`). |
| `LOG_LEVEL` | `--log-level` | Overrides `logging.level`. |
| `LOG_DIR` | `--log-dir` | Log directory, empty disables file logging. |
| `LOG_FILE_NAME` | `--log-file-name` | Log file name. |
| `LOG_COLOR`, `LOG_FORMAT`, `LOG_ROTATION_ENABLED`, … | | Any `logging.*` option as `LOG_<OPTION>` / `LOG_ROTATION_<OPTION>`. |
| `TZ` | | Timezone for timestamps. |
| `BOOMARR_API_KEY` | | API key for the HTTP server when `server.api_key` is not set (`WEBHOOK_API_KEY` also works). |
| `BOOMARR_NOTIFY_URLS` | | Whitespace separated Apprise URLs when `notifications.urls` is not set. |
| `HEARTBEAT_FILE` | | Heartbeat file used by `boomarr healthcheck`. |
| `PUID`, `PGID`, `UMASK` | | Docker only: user, group and umask Boomarr runs as. |
| `DANGEROUS_SKIP_READONLY_CHECK` | `--dangerous-skip-readonly-check` | Disable the read-only source check. Development only. |

Environment variables win over the config file (a warning is logged when
both are set); CLI options win over both.

## Output directory naming

For every symlink library the output directory is, in order of precedence:

1. its own `output_path`,
2. `<base>/<name>` when `name` is set,
3. `<base>/<library name, lower-case, spaces → dashes>-<filter suffixes>`,

where `<base>` is the library's `output_path` or the global `output_path`.
The automatic suffix of an `audio_language` filter is its configured codes,
lower-cased, sorted and joined with `-` (`[eng, DEU]` → `deu-eng`); see the
individual filters for theirs. Inverted filters are prefixed with `not-`.

## Validation rules

Boomarr refuses to start with a configuration that could damage your data or
produce conflicting results:

- Output directories must not be inside, equal to, or contain **any**
  library's input directory.
- Every symlink library needs its own output directory, and output
  directories must not be nested inside each other.
- Library names, symlink library names and suffixes must be usable as a
  single folder name (no `/`, `\`, `.` or `..`).
- Library names must be unique; every library needs at least one symlink
  library and every symlink library at least one filter.
- Input directories must be **read-only** for Boomarr (checked at runtime).
