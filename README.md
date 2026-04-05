# Boomarr

![PyPI - Version](https://img.shields.io/pypi/v/boomarr?logo=python&logoColor=green&color=blue)
![GitHub License](https://img.shields.io/github/license/eulemitkeule/boomarr)
![GitHub Sponsors](https://img.shields.io/github/sponsors/eulemitkeule?logo=GitHub-Sponsors)

[![Code Quality](https://github.com/EuleMitKeule/boomarr/actions/workflows/quality.yml/badge.svg)](https://github.com/EuleMitKeule/boomarr/actions/workflows/quality.yml)
[![Publish](https://github.com/EuleMitKeule/boomarr/actions/workflows/publish.yml/badge.svg)](https://github.com/EuleMitKeule/boomarr/actions/workflows/publish.yml)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=EuleMitKeule_boomarr&metric=coverage)](https://sonarcloud.io/summary/new_code?id=EuleMitKeule_boomarr)
[![Bugs](https://sonarcloud.io/api/project_badges/measure?project=EuleMitKeule_boomarr&metric=bugs)](https://sonarcloud.io/summary/new_code?id=EuleMitKeule_boomarr)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=EuleMitKeule_boomarr&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=EuleMitKeule_boomarr)
[![Code Smells](https://sonarcloud.io/api/project_badges/measure?project=EuleMitKeule_boomarr&metric=code_smells)](https://sonarcloud.io/summary/new_code?id=EuleMitKeule_boomarr)
[![Technical Debt](https://sonarcloud.io/api/project_badges/measure?project=EuleMitKeule_boomarr&metric=sqale_index)](https://sonarcloud.io/summary/new_code?id=EuleMitKeule_boomarr)

🔊 Symlink-based audio language filter for Plex & Jellyfin — automatically mirrors your media library, keeping only files with your desired audio tracks.

## What is this?

Boomarr scans your media library for files that contain specific audio language tracks (using ffprobe) and creates symlinks to those files in a separate output folder. That folder can then be used as a dedicated Plex or Jellyfin library — perfect for family members who only want to see content available in their native language.

## Inspiration

This project is inspired by [Filip Rojek's blog post](https://www.filiprojek.cz/posts/jellyfin-language-specific-library/) on creating a language-specific Jellyfin library using a custom Bash script. Boomarr takes that idea further by building it into a fully configurable, Docker-native tool with Sonarr/Radarr integration, inotify-based change detection, and automatic stale symlink cleanup.
