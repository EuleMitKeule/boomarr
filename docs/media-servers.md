# Media server setup

## Path mapping

A symlink is just a file that contains a path. Boomarr writes the path of
the original file **as Boomarr sees it**, and your media server follows that
path **as it sees it**. Both must agree.

Good (same container paths in both containers):

```yaml
# boomarr
volumes:
  - /srv/data/media:/data/media:ro
  - /srv/data/filtered:/data/filtered
# plex / jellyfin
volumes:
  - /srv/data/media:/data/media:ro
  - /srv/data/filtered:/data/filtered:ro
```

Bad (different paths): Boomarr creates `Film.mkv -> /movies/Film.mkv`, but
inside the Plex container the file lives at `/data/movies/Film.mkv`, so the
link is broken and Plex shows nothing.

The easiest way to get this right is one parent directory (`/data`) that is
mounted identically everywhere, as recommended by the
[TRaSH guides](https://trash-guides.info/File-and-Folder-Structure/).

### Relative symlinks

If your paths cannot be identical, but the source and the output share a
common parent in every container, enable relative links:

```yaml
relative_symlinks: true
```

A link at `/data/filtered/movies-deu/Film/Film.mkv` then points to
`../../../media/movies/Film/Film.mkv`, which works wherever `/data` (or any
other common parent) is mounted. Switching the option rewrites existing
links on the next scan.

## Plex

1. Add a new library (e.g. *Filme (Deutsch)*) pointing at the output folder,
   e.g. `/data/filtered/movies-deu`.
2. Share only that library with the users who need it.
3. Recommended: *Settings → Library → Empty trash automatically after every
   scan* can stay enabled. Boomarr never removes the whole library at once:
   if the source share is not mounted, the library is skipped and all
   existing links are kept.
4. Optional: give the filtered library the same agent/language settings as
   the original. Watch state is tracked per library item, so it is not shared
   between the original and the filtered library.

## Jellyfin / Emby

1. *Dashboard → Libraries → Add Media Library*, folder
   `/data/filtered/movies-deu`.
2. Optionally enable *real-time monitoring*; Boomarr's changes are picked up
   like any other file change.
3. Restrict access per user under *Dashboard → Users → Library access*.

Subtitles next to a media file (`Film.de.srt`, `Film.en.forced.ass`) are
linked automatically, see `sidecar_extensions`.

## Sonarr / Radarr

Boomarr only reads your media, so no changes are required. For instant
updates after an import, enable the [HTTP server](configuration.md#http-server-webhooks-metrics-status)
and add a webhook. To skip ffprobe entirely for files Sonarr/Radarr already
analysed, use the [`sonarr`/`radarr` probers](configuration.md#sonarr-and-radarr-probers).

## Automatic media server refresh

Instead of waiting for the media server's own schedule or real-time
monitoring, Boomarr can ask Plex/Jellyfin/Emby to rescan exactly the folders
that changed. See [media server refresh](configuration.md#media-server-refresh).
