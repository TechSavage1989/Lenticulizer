# AGENTS.md

Read `DEVELOPMENT_HANDOFF.md` before changing Lenticulizer.

## Baseline rules

- Preserve the confirmed Alpha 31 behavior and Blender add-on v1.18.43 unless a change is explicitly requested.
- Alpha 32/33 contain a Windows updater verification failure: an exclusively open temporary ZIP is hashed before its writer closes. Alpha 34 fixes this and introduces visible verifying/error/retry states and a no-data timeout. A one-time manual installation is required from affected versions. Live updater install/rollback remains unverified.
- Do not replace this source with older Alpha 26/27 source after reconstruction.
- Do not publish source, binaries, releases, credentials, or repository-visibility changes without explicit authorization.
- Do not overwrite published tags/releases.

- Alpha 35 is a small release for user-driven updater testing from installed Alpha 34. Do not modify the Alpha 34 updater/installer or describe its real-world install/rollback path as validated before user testing.

## Source map

The existing toolchain uses these top-level implementation equivalents instead of forcing a new `src/` migration during active updater work:

- `app/` — Windows desktop shell, WebView2 host, updater, preferences, packaging helpers.
- `backend/` — native/core image, optical, project, and Blender-export logic.
- `ui/` — embedded desktop HTML/CSS/JavaScript interface.
- `blender/` — Blender add-on source and packaged add-on.
- `validation/` — parity, contract, raster, UI-handler, and integration checks.
- `scripts/` — repository/source-layout checks and maintenance helpers.
- `packaging/` — runtime/source packaging helpers.
- `docs/` and `docs/releases/` — architecture and historical/current release notes.
- `vendor/` — required Fixed WebView2 Runtime build assets/notices.

Root exceptions are limited to read-first documentation, the .NET project/global/NuGet configuration, and small Windows build/launch wrappers required by the existing workflow. `scripts/root-allowlist.txt` is the reviewed allowlist.

## Packaging/update target

- Windows-first portable/self-contained.
- Stable new-package launch filename: `Lenticulizer.exe`.
- Existing custom/versioned executable paths are preserved during in-place updates so old shortcuts are not broken silently.
- Mutable state belongs in per-user storage, not beside the executable.
- Keep only one previous rollback executable.
- Never auto-download or auto-restart an update.
- Validate trusted HTTPS origin, manifest identity/version, expected package size/hash, archive safety, PE identity, and product/version metadata before installation.
- Confirm a healthy new UI handshake before reporting update success; rollback on failure.
- A matching hash is not publisher signing.

## Update checks

Required behavior: startup check, five-minute active checks, focus-return check after two minutes, single-flight requests, ETag/conditional requests, cached results, shared-IP/rate-limit/backoff/Retry-After handling, manual cooldown, explicit offline/error states, and no false “up to date” state on network failure.

## Testing

For updater fixes, demonstrate the old failure with a negative control and exercise previous-version → new-version download, digest verification, staging, install, relaunch, settings preservation, cleanup and rollback on real Windows before release.

Static/source contract tests are useful but do not replace native Windows validation.

State clearly when Windows, WebView2, live Blender, GPU or printer testing was not performed.

## Root guard

Run:

```text
python validation/RootGuardChecks.py
```

The underlying `scripts/check_root.py` must work both in a Git checkout and from an extracted source archive without `.git`. Generated `bin/`, `obj/`, `dist/`, and release output are excluded. A genuinely required new root item must be reviewed and added to `scripts/root-allowlist.txt` in the same change.

Do not commit deliberate clutter used by the negative control.

## Release handoff

Before calling a release ready:

1. Verify the exact commit/tag and hosted CI.
2. Verify release assets and hashes.
3. Run the source/parity/root checks.
4. Build from a fresh source archive without `.git`.
5. Run native Windows launch/WebView2 checks.
6. Exercise the actual prior-version → release updater path, including offline/throttled/error cases and rollback.
7. Verify settings preservation and cleanup.
8. Run live Blender checks for Blender-affecting changes.
9. Update README and `DEVELOPMENT_HANDOFF.md`.
10. Put release history in `docs/releases/` rather than accumulating dated root files.

Do not add server setup, Codex CLI automation, unattended workers, payment setup, or API-account setup.

## Repository standards (all contributors and AI tools)

This repository follows the shared TechSavage1989 standard in [`docs/REPOSITORY_STANDARDS.md`](docs/REPOSITORY_STANDARDS.md), the same file in every app repository. Read it before changing anything. In short:

- **README:** centered header (real icon, one `<h1>`, tagline, quick links Download · Get started · Features · Screenshots · Updates · Development, hero image), then the standard section order. Update it in the same pull request as any user-visible change.
- **Screenshots:** real captures with fictional data in `docs/images/` (`hero.png` + kebab-case names). Recapture any screenshot a UI change makes stale, in the same pull request.
- **Layout:** compact root; respect the root allowlist and checks above. Never commit build output, binaries, archives, logs, caches or secrets.
- **Branches:** short-lived `feat/` `fix/` `docs/` `chore/` `release/` branches, one focused change per pull request, merge only on green checks, delete the branch after merging.
- **Instructions:** this file is the single source of project rules for every tool; `CLAUDE.md` imports it. Add new rules and gotchas here.

Where this file's project-specific rules differ from the shared standard, this file wins; an enforced check script wins over both.
