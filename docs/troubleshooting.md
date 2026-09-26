# Troubleshooting & FAQ

### I forgot the password / cannot log in {#authentication}

Stop Boomarr and delete `auth.json` in the config directory (or set
`BOOMARR_USERNAME`/`BOOMARR_PASSWORD` and restart). On the next start the
web UI asks for a new admin account. With `auth.method: external` make sure
your proxy's address is listed in `server.trusted_proxies`; otherwise the
user header is ignored. See [Web UI & security](web-ui.md#authentication).

### "No libraries configured yet" {#libraries}

Add one in the web UI (*Libraries* → *Add library*) or in `boomarr.yml`,
see [libraries](configuration.md#libraries). Scans are skipped until a
library exists.

### "Scan skipped: Source directories must be mounted read-only"

In watch mode with the web UI, Boomarr keeps running when a source is
writable, but refuses to scan (the dashboard shows the problem). Remount the
source read-only (`:ro`); the next scan runs normally.

### "Source directory '…' is writable! … Aborting." {#read-only-sources}

Mount the source read-only (`:ro` in Docker, `readOnly: true` on
Kubernetes), or make sure the Boomarr user has no write permission on it.
This is a deliberate safety net and cannot be disabled in production.

### My media server shows an empty library / broken files

The symlinks point to paths your media server cannot see. Run

```bash
docker exec boomarr ls -l /data/filtered/movies-deu | head
```

and check that the target paths exist *inside the media server container*.
See [path mapping](media-servers.md#path-mapping) or enable
`relative_symlinks`.

### A file with German audio is not linked

1. `boomarr status` lists all audio languages found. Is your language there?
2. Check the file: `ffprobe -v error -show_entries stream=codec_type:stream_tags=language -of csv "file.mkv"`.
   Tracks without a tag show up as `und`: add `aliases: [und]`.
3. Run with `LOG_LEVEL=debug` to see why each file was rejected.

`ger`, `deu`, `de` and `de-DE` are treated as the same language, so the
spelling in your config does not matter.

### "Input path … contains no files but its output directories contain symlinks. Skipping"

Boomarr protected your filtered library: the source directory is empty,
which almost always means a network share is not mounted. Fix the mount; the
next scan continues normally. If you really emptied the source on purpose,
delete the output folder by hand.

### "FFprobe executable 'ffprobe' not found" {#probers}

Bare metal only: install FFmpeg (`apt install ffmpeg`, `brew install ffmpeg`)
or set `probers: [{type: ffprobe, path: /path/to/ffprobe}]`.

### "Unknown config option … is ignored"

A typo or an option that does not exist (anymore). The message contains the
full path to the key, e.g. `libraries[0].symlink_libraries[0].filters[0].langauges`.

### The first scan takes long

Every file is probed once (only the first few MB are read). Increase
`probe_workers` on fast storage. Later scans only probe new or changed files
and usually finish in seconds.

### After an update all files were probed again

The probe cache format changed and was rebuilt. This happens at most once
per update and does not affect your links.

### I changed the filters, do I need to reset anything?

No. Filters are evaluated on every scan against the cached probe results;
the next scan creates and removes links accordingly. The same applies to
new symlink libraries and links you deleted by hand.

### Can I use hardlinks instead?

Not yet. Hardlinks only work on the same filesystem and cannot be told apart
from the original, which makes safe cleanup much harder. Symlinks are
supported by Plex, Jellyfin and Emby.

### How do I trigger a scan right after Sonarr/Radarr imported something?

Enable the [HTTP server](configuration.md#http-server-webhooks-metrics-status)
and add a webhook in Sonarr/Radarr.

### "Removal guard: refusing to remove …" {#removal-guard}

A scan wanted to remove more than half of the links of a folder. If that is
intended (you changed filters or removed media on purpose), run
`boomarr scan --force` once. Otherwise check your mounts and paths.
