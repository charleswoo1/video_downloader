# Third-Party Components

This project uses and, in the Windows standalone build, may redistribute third-party software. This document is an inventory for transparency; it is **not a substitute for the complete upstream license texts or for satisfying redistribution obligations**.

## Python components

The release build is pinned in `requirements-release.txt`. Major components include:

- **yt-dlp** — https://github.com/yt-dlp/yt-dlp
- **CustomTkinter** — https://github.com/TomSchimansky/CustomTkinter
- **Pillow** — https://github.com/python-pillow/Pillow
- **PyInstaller** — https://github.com/pyinstaller/pyinstaller

Each component remains subject to its own upstream license and notices.

## Node.js

The Windows standalone build bundles a Node.js executable used by yt-dlp for JavaScript challenge processing.

- Upstream: https://github.com/nodejs/node
- License information: https://github.com/nodejs/node/blob/main/LICENSE

The release workflow currently pins Node.js **22.23.2**.

## FFmpeg / FFprobe

The Windows standalone build bundles FFmpeg and FFprobe.

- FFmpeg upstream: https://ffmpeg.org/
- FFmpeg legal/licensing information: https://ffmpeg.org/legal.html
- Windows build source used by the current workflow: Gyan.dev via the Chocolatey `ffmpeg` package
- Pinned package version: **9.0.1**

The successful v1.0.0 build reported a Gyan Essentials build configured with both `--enable-gpl` and `--enable-version3`. Redistribution must therefore be reviewed against the license terms that apply to that exact binary and its enabled libraries. This repository does not claim that this notice alone fulfills those obligations.

## Release metadata

Starting with the hardened release workflow, each new release also includes `BUILD-METADATA.txt`, which records the commit and runtime/package versions used for that build.

If a bundled component or build source changes, update this document in the same Pull Request.
