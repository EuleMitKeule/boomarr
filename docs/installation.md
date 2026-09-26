# Installation

- [Docker Compose](#docker-compose) (recommended)
- [Docker CLI](#docker-cli)
- [Unraid](#unraid)
- [Kubernetes with Helm](#kubernetes-with-helm)
- [pip, pipx or uv (bare metal)](#pip-pipx-or-uv-bare-metal)
- [Updating](#updating)

Whatever you choose, two rules matter more than anything else:

1. **Mount your source media read-only.** Boomarr refuses to run otherwise.
2. **Use the same paths as your media server.** Symlinks contain the path of
   the original file as Boomarr sees it. If Boomarr sees
   `/data/media/movies/Film.mkv`, Plex/Jellyfin must see the file at exactly
   that path too. See [media servers](media-servers.md#path-mapping).

## Docker Compose

```yaml
services:
  boomarr:
    image: ghcr.io/eulemitkeule/boomarr:latest
    container_name: boomarr
    restart: unless-stopped
    environment:
      PUID: 1000
      PGID: 1000
      TZ: Europe/Berlin
    ports:
      - "9797:9797"                  # web UI
    volumes:
      - ./config:/config
      - /srv/data/media:/data/media:ro
      - /srv/data/filtered:/data/filtered
    security_opt:
      - no-new-privileges:true
```

```bash
docker compose up -d
```

Open `http://<host>:9797/`, create the admin account and add your first
library in **Libraries** (see [Web UI](web-ui.md#first-start)). Prefer
YAML? Edit `./config/boomarr.yml` instead, the UI and the file are always in
sync.

The image:

- runs `boomarr watch` by default,
- runs as `PUID`/`PGID` (default `1000`) and also supports `user: 1000:1000`
  (rootless, no privilege switching),
- serves the [web UI](web-ui.md) on port `9797`,
- has a built-in `HEALTHCHECK` (`boomarr healthcheck`),
- is published for `linux/amd64` and `linux/arm64`
  (Raspberry Pi 4/5, Apple Silicon, ARM NAS),
- is tagged `latest`, `X.Y.Z`, `X.Y` and `X` (from 1.0 on). Pin at least the
  minor version in production.

### Validate before going live

Press **Dry run** in the web UI (or run
`docker compose run --rm boomarr boomarr scan --dry-run`): Boomarr lists
every symlink that *would* be created or removed without touching anything
(*Activity* → click the scan).

## Docker CLI

```bash
docker run -d --name boomarr --restart unless-stopped \
  -e PUID=1000 -e PGID=1000 -e TZ=Europe/Berlin \
  -p 9797:9797 \
  -v /srv/boomarr:/config \
  -v /srv/data/media:/data/media:ro \
  -v /srv/data/filtered:/data/filtered \
  ghcr.io/eulemitkeule/boomarr:latest
```

## Unraid

A template is available at
[`contrib/unraid/boomarr.xml`](https://github.com/EuleMitKeule/boomarr/blob/master/contrib/unraid/boomarr.xml).

1. *Docker* → *Template repositories*: add
   `https://github.com/EuleMitKeule/boomarr` and save.
2. *Add Container* → select **boomarr**.
3. Map your media share **read-only** to the same container path your
   Plex/Jellyfin container uses (the template defaults to `/data/media`), and
   the output share read-write (`/data/filtered`).
4. Start the container and click *WebUI* in its context menu to create the
   admin account and add libraries.

`PUID=99`/`PGID=100` (nobody/users) are the Unraid defaults.

## Kubernetes with Helm

The chart is published as an OCI artifact:

```bash
helm install boomarr oci://ghcr.io/eulemitkeule/charts/boomarr \
  --namespace media --create-namespace \
  -f values.yaml
```

Example `values.yaml`:

```yaml
config:
  output_path: /data/filtered
  libraries:
    - name: Movies
      input_path: /data/media/movies
      symlink_libraries:
        - filters:
            - type: audio_language
              languages: [deu]

volumes:
  - name: media
    persistentVolumeClaim:
      claimName: media           # shared with your Plex/Jellyfin deployment
volumeMounts:
  - name: media
    mountPath: /data/media
    subPath: media
    readOnly: true
  - name: media
    mountPath: /data/filtered
    subPath: filtered

auth:
  existingSecret: boomarr-admin     # keys: username, password
ingress:
  enabled: true
  className: nginx
  hosts:
    - host: boomarr.example.com
      paths: [{path: /, pathType: Prefix}]
serviceMonitor:
  enabled: true                     # Prometheus Operator
```

By default (`configMode: ui`) `config` is only the initial `boomarr.yml`;
afterwards the web UI owns the file on the config volume. For GitOps set
`configMode: configMap`: the file is mounted read-only from the ConfigMap
and the UI shows the settings without allowing changes.

The chart runs rootless with a read-only root filesystem, dropped
capabilities and `RuntimeDefault` seccomp, uses a `Recreate` strategy (the
probe cache is SQLite) and restarts the pod when the config changes. See
[`charts/boomarr/values.yaml`](https://github.com/EuleMitKeule/boomarr/blob/master/charts/boomarr/values.yaml) for all
options.

## pip, pipx or uv (bare metal)

Requires Python 3.14+ and `ffprobe` (package `ffmpeg`).

```bash
pipx install boomarr        # or: uv tool install boomarr
boomarr --help
CONFIG_DIR=/etc/boomarr boomarr watch      # web UI on http://localhost:9797/
```

A hardened systemd unit is available at
[`contrib/systemd/boomarr.service`](https://github.com/EuleMitKeule/boomarr/blob/master/contrib/systemd/boomarr.service).
The service user needs read access to the sources and write access to the
output directories and the config directory only.

## Updating

Boomarr's probe cache is versioned. If an update changes its format, the
cache is rebuilt automatically (all files are probed once more); symlinks
are left in place and reconciled by the first scan. No manual steps are
needed.
