# DEVELOPMENT_HANDOFF.md

## Current status

Confirmed functional baseline: **Lenticulizer v3.0.0-alpha.31** with **Blender add-on v1.18.43**.

Current source-development line: **v3.0.0-alpha.32**.

Repository: `TechSavage1989/Lenticulizer` (public). The public repository remains documentation-only; application-source publication has not been authorized. No GitHub release/update feed is live yet.

Alpha 31-equivalent source was reconstructed privately from the latest recoverable maintainable source plus the recorded Alpha 28–31 changes. Alpha 32 builds on that reconstruction rather than reverting to older Alpha 26/27 code.

## Alpha 32 source foundation

### Stable portable identity

- Assembly/output name is `Lenticulizer`.
- New packaged builds target `Lenticulizer.exe`.
- Build, launch, runtime verification, UI-check, and release-packaging wrappers use the stable filename.
- Active validation projects reference the stable assembly/runtimeconfig/deps names.
- In-place updates preserve the executable path already in use so legacy custom/versioned shortcuts are not silently broken.

### Per-user mutable state

- Window placement: `%LOCALAPPDATA%\Lenticulizer\Settings\window.json`.
- Existing logs/runtime/browser profile/sessions remain per-user.
- Updater cache/downloads/staging/health/helper/rollback live under `%LOCALAPPDATA%\Lenticulizer\Updates`.

### Updater foundation

Implemented in source:

- startup background check;
- five-minute native WinForms timer;
- focus-return check after two minutes;
- single-flight requests;
- ETag/`If-None-Match` caching;
- explicit offline state;
- ten-second manual-check cooldown;
- `Retry-After`, GitHub rate-limit reset, 403 and 5xx backoff;
- compact update banner and Help-page status;
- explicit Download and Install and restart actions only;
- active-operation restart guard;
- authorized HTTPS GitHub/release-CDN host checks;
- required `update-manifest.json` identity/version/package/hash/size contract;
- SHA-256 and size verification;
- strict one-root-EXE ZIP layout, traversal/size/decompression-ratio checks;
- Windows PE/ProductName/ProductVersion checks;
- same-filesystem replacement staging;
- one `Lenticulizer.previous.exe` rollback;
- UI-health token reported only after native WebView2 `bootstrap`;
- restore/relaunch of the previous executable if health fails.

A matching SHA-256 is integrity verification against release metadata, not code signing.

### Release packaging

The compiled stable executable supports `--package-release <directory>` and creates:

- `Lenticulizer_Windows_Portable.zip`
- `update-manifest.json`
- `SHA256SUMS.txt`

The updater ZIP contains only root `Lenticulizer.exe`.

### Root/source guard

The private source contains a reviewed root allowlist, archive-compatible guard, clean-tree test, and isolated unapproved-root-file negative control.

## Preserved Alpha 31 behavior/resources

- Lenticular Lens and Lens-Free Relief workflows.
- Source ordering/interlacing and 16-bit height/depth maps.
- Automatic / Semi-Automatic / Manual settings.
- LPI, DPI, phase/registration, IOR, viewing angle, lens/base and optional backing controls.
- Alpha 29 compact Images/Optics layout and UI preferences.
- Labeled test-print export workflow.
- Blender add-on v1.18.43.
- Project(6) baseline SHA-256 `54154ce98dae6b232ef486886ecdaf61f5370510abe9c247ad712d002ca99897`.

## Validation completed

The Alpha 32 source snapshot passed the available non-.NET checks after a fresh extraction without `.git`, including:

- JavaScript syntax and WebView2 bridge regression checks.
- Native-file drop UI-handler checks.
- Desktop DOM/bridge/add-on-package contracts.
- 30 heightmap raster/direction/phase/filter/bit-depth fixtures.
- 33 Blender add-on callback/project/geometry/export checks using API doubles.
- Alpha 31 baseline/add-on/runtime preservation checks under Alpha 32 identity.
- Updater stable-launch/per-user-state/static-security contracts.
- Unsafe archive extra-file/traversal negative controls.
- Root clean-tree and clutter negative controls.
- Source archive plan/manifest checks from a fresh extracted archive without `.git`.
- Final source snapshot is preserved privately for future continuation; it is not published in this public repository.

Private Alpha 32 source snapshot SHA-256:

`fa20464d3add72707eee76ad9b3e811e73a59fc5ecdb3d1f5cd66c877c1628b8`

Not performed in this environment:

- .NET compiler build of Alpha 32;
- Windows EXE launch / real WebView2 behavior;
- real GitHub update download/install/relaunch;
- live throttling/offline transitions at the native HTTP layer;
- live rollback process test;
- live Blender installation/viewport/rendering;
- physical print testing.

The environment lacks the .NET 10 SDK and cannot directly obtain Microsoft/NuGet build dependencies, so source/static validation must not be represented as a compiled release.

## First-update migration

Alpha 31 has no updater, so the first transition to a compiled Alpha 32 build must be manual.

Once Alpha 32 is installed, subsequent in-place updates can use the updater foundation after a compatible GitHub release feed is published and validated. New packages use `Lenticulizer.exe`; a legacy/custom filename already used by Alpha 32 is preserved during replacement to protect shortcuts.

## Build/release expectations

Windows build entry: `Build_SelfContained.bat`.

Expected output:

`dist\Lenticulizer.exe`

Expected release assets:

- `release\Lenticulizer_Windows_Portable.zip`
- `release\update-manifest.json`
- `release\SHA256SUMS.txt`

The source pins .NET SDK 10.0.400 and runtime 10.0.11, includes the Fixed WebView2 Runtime build payload, and carries a repository `NuGet.Config` that explicitly restores from the official NuGet v3 source instead of inheriting machine-specific package-source state.

## Next release gates

1. Fresh-compile Alpha 32 on Windows from an extracted source snapshot without `.git`.
2. Run built-in core/runtime/UI checks.
3. Verify stable shortcut behavior and settings/window persistence.
4. Publish only when explicitly authorized.
5. Test actual GitHub ETag/offline/rate-limit/startup/5-minute/focus behavior.
6. Exercise Alpha 32 → newer test release download/hash/stage/install/relaunch.
7. Force a health failure and verify rollback/cleanup/one-backup behavior.
8. Re-run live Blender integration if bridge behavior changes.
9. Verify hosted CI, exact commit/tag, assets and hashes before calling a release ready.

## Publication boundary

Do not publish application source merely because the repository is public. Source-publication scope remains unapproved. Documentation-only repository updates are allowed; application source/binaries/releases require explicit authorization.

Do not add server setup, Codex CLI automation, unattended workers, payment setup, or API-account setup.
