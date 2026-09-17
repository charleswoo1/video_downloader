# Contributing

Thanks for considering a contribution.

## Development flow

1. Create a branch from `main`.
2. Make focused changes.
3. Run the tests:
   ```powershell
   python -m unittest -v test_suite.py
   ```
4. For packaging-related changes, also run:
   ```powershell
   python build_exe.py --onefile
   ```
5. Open a Pull Request and let GitHub Actions complete before merge.

## Versioning

`version.py` is the single source of truth for the application version. Do not bump the version for ordinary feature or bug-fix Pull Requests unless the change is specifically preparing a release.

A release tag must exactly match the application version, for example:

```text
version.py -> 1.0.1
Git tag    -> v1.0.1
```

Published release tags and assets are not reused or overwritten.

## Release notes

Every release must include a curated, user-facing summary at:

```text
.github/release-notes/vX.Y.Z.md
```

The filename must exactly match the release tag. For example, release `v1.0.1` requires `.github/release-notes/v1.0.1.md`.

The release workflow refuses to publish when this file is missing or empty. At release time it places the curated summary first, then appends GitHub's automatically generated changelog so users see the important changes before the raw Pull Request history.

Release summaries should focus on:

- user-visible changes
- upgrade or migration notes
- security or privacy-impacting changes
- download/runtime requirements that changed
- known limitations that matter to users

## Dependencies

- `requirements.txt` describes the normal development dependency ranges.
- `requirements-release.txt` pins the tested release-build dependency set.
- Dependency updates should be isolated, tested, and preferably handled through Dependabot Pull Requests.

## Privacy and credentials

Never commit or attach:

- cookies.txt
- browser cookie databases
- account tokens or passwords
- downloaded media
- private URLs
- unredacted logs containing personal data

## Legal scope

Contributions must not add DRM-circumvention functionality or features whose primary purpose is bypassing access controls. Contributors are responsible for using the project only with content they are authorized to download or process.
