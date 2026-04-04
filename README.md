# boomarr

🔊 Symlink-based audio language filter for Plex & Jellyfin — automatically mirrors your media library, keeping only files with your desired audio tracks.

## What is this?

boomarr scans your media library for files that contain specific audio language tracks (using ffprobe) and creates symlinks to those files in a separate output folder. That folder can then be used as a dedicated Plex or Jellyfin library — perfect for family members who only want to see content available in their native language.

## Inspiration

This project is inspired by [Filip Rojek's blog post](https://www.filiprojek.cz/posts/jellyfin-language-specific-library/) on creating a language-specific Jellyfin library using a custom Bash script. boomarr takes that idea further by building it into a fully configurable, Docker-native tool with Sonarr/Radarr integration, inotify-based change detection, and automatic stale symlink cleanup.
