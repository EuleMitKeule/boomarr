# Security Policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Please **do not** open a public issue. Use
[GitHub private vulnerability reporting](https://github.com/EuleMitKeule/boomarr/security/advisories/new)
instead. You will get a response within a few days.

## Security model

- Boomarr needs read access to your media and write access only to its
  config directory and the output directories. It refuses to run when a
  source directory is writable.
- The Docker image drops root privileges (`PUID`/`PGID`) or runs fully
  rootless (`--user`), and the Helm chart uses a read-only root filesystem
  without capabilities.
- The optional webhook listener only accepts requests that queue a scan. Set
  an `api_key` and keep the port on your internal network.
