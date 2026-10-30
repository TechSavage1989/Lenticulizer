# AGENTS.md

Read `DEVELOPMENT_HANDOFF.md` before changing Lenticulizer.

## Baseline rules

- Preserve the confirmed Alpha 31 behavior and Blender add-on v1.18.43 unless a change is explicitly requested.
- Alpha 32 is the current source-development line for stable packaging/updater work; it is not yet a published native build.
- Do not replace current reconstructed source with older Alpha 26/27 source.
- Do not publish source, binaries, releases, credentials, or repository-visibility changes without explicit authorization.
- Do not overwrite published tags/releases.

## Packaging/update target

- Windows-first portable/self-contained.
- Stable new-package launch filename: `Lenticulizer.exe`.
- Preserve existing custom/versioned executable paths during in-place updates so shortcuts are not broken silently.
- Mutable state belongs in per-user storage.
- Keep only one previous rollback executable.
- Never auto-download or auto-restart an update.
- Validate trusted HTTPS origin, manifest identity/version, expected size/hash, archive safety, PE identity, and product/version metadata before installation.
- Confirm a healthy new UI handshake before reporting update success; rollback on failure.
- A matching hash is not publisher signing.

## Update checks

Required behavior: startup check, five-minute active checks, focus-return check after two minutes, single-flight requests, ETag/conditional requests, cached results, rate-limit/backoff/Retry-After handling, manual cooldown, explicit offline/error states, and no false “up to date” state on failure.

## Testing

For updater fixes, demonstrate negative controls and exercise previous-version → new-version download, digest verification, staging, install, relaunch, settings preservation, cleanup and rollback on real Windows before release.

Static/source contract tests do not replace native Windows validation.

State clearly when Windows, WebView2, live Blender, GPU or printer testing was not performed.

## Repository/source organization

The public repository remains documentation-only until source publication is explicitly authorized.

The private reconstructed source uses the established `app/`, `backend/`, `ui/`, and `blender/` implementation folders, with `validation/`, `scripts/`, `packaging/`, `docs/`, and required `vendor/` assets.

The source has a reviewed root allowlist and a guard that works both with Git metadata and from an extracted archive without `.git`. Its negative control verifies that an unapproved root file fails.

Do not add server setup, Codex CLI automation, unattended workers, payment setup, or API-account setup.

## Release handoff

Before calling a release ready:

1. Verify exact commit/tag and hosted CI.
2. Verify release assets and hashes.
3. Build from a fresh source archive without `.git`.
4. Run native Windows launch/WebView2 checks.
5. Exercise the actual prior-version → release updater path, including offline/throttled/error and rollback cases.
6. Verify settings preservation, cleanup, stable shortcuts, and one rollback.
7. Run live Blender checks when integration changes.
8. Update README and `DEVELOPMENT_HANDOFF.md`.
9. Record release history in `docs/releases/`.
