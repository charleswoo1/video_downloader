# Release workflow

Formal releases can be published in three ways:

1. Merge a release request to `main` (preferred).
2. Manually run **Build & Release Windows EXE** with a tag.
3. Push a `v*` tag.

## Preferred: release request

Create or update `.github/release-request.json` in the same release PR that prepares the version and release notes:

```json
{
  "tag": "v1.0.3",
  "publish": true
}
```

The PR should also ensure:

- `version.py` contains the same version without the leading `v`.
- `.github/release-notes/<tag>.md` exists and is not empty.
- Normal CI passes before merge.

After the PR is merged to `main`, the release workflow runs automatically because `.github/release-request.json` changed. It validates the request, refuses to reuse an existing tag or Release, runs the unit tests, builds the standalone Windows executable, creates checksums and build metadata, and publishes the GitHub Release.

The Release is created against the merge commit (`GITHUB_SHA`), so no separate manual tag creation or **Run workflow** click is required.

## Safety behavior

The automatic release path only triggers on a push to `main` that changes `.github/release-request.json`. Pull-request activity alone cannot publish a Release.

A request is rejected if any of these checks fail:

- `publish` is not exactly `true`.
- `tag` is missing or does not match the supported `vX.Y.Z` format.
- `tag` does not match `version.py`.
- the curated release notes file is missing or empty.
- the Git tag already exists.
- the GitHub Release already exists.

Published releases are never overwritten.

## Manual fallback

The workflow keeps `workflow_dispatch` support. From **Actions → Build & Release Windows EXE → Run workflow**, provide the desired tag. The same version, notes, existing-tag, test, build, checksum, and publishing checks apply.

The legacy `v*` tag trigger also remains available as a fallback.
