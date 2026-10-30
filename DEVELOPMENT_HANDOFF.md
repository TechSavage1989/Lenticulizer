# DEVELOPMENT_HANDOFF.md

## Current status

Confirmed working behavior baseline: **Lenticulizer v3.0.0-alpha.31** with **Blender add-on v1.18.43**.

Current source-development line: **v3.0.0-alpha.32**.

Repository: `TechSavage1989/Lenticulizer` (public). The public repository currently contains documentation only; application source publication has not been authorized. No GitHub release/update feed is live yet.

Alpha 31-equivalent source was reconstructed from the latest recoverable maintainable source plus the recorded Alpha 28–31 changes. Alpha 32 builds on that reconstructed source rather than reverting to older Alpha 26/27 code.

## Alpha 32 changes in source

### Stable portable identity

- Assembly/output name is now `Lenticulizer`.
- New packaged builds target the stable launch filename `Lenticulizer.exe`.
- Build, launch, runtime verification, UI-check, and release-packaging wrappers use the stable filename.
- Active validation projects now reference `Lenticulizer.dll` / matching runtimeconfig/deps names.
- An in-place update preserves the current executable path. This intentionally avoids silently breaking a legacy custom/versioned shortcut. New manual installs use `Lenticulizer.exe`.

### Per-user mutable state

- Window placement is stored under `%LOCALAPPDATA%\Lenticulizer\Settings\window.json`.
- Existing logs, runtime, browser profile, sessions/working data remain per-user.
- Updater cache, downloads, staging, health markers, helper copy, and the one rollback executable live under `%LOCALAPPDATA%\Lenticulizer\Updates`.
- Update staging is copied to the target filesystem before executable replacement to handle cross-volume source/staging cases safely.

### GitHub updater foundation

Native app service added with:

- startup background check;
- five-minute native WinForms timer;
- focus-return check when at least two minutes have elapsed;
- single-flight update operations;
- ETag / `If-None-Match` release caching;
- explicit offline state;
- manual ten-second cooldown;
- `Retry-After`, GitHub rate-limit reset, 403 and 5xx backoff;
- compact update banner and Help-page status;
- explicit **Download** and **Install and restart** actions only;
- no automatic download/restart;
- active-operation restart guard;
- authorized HTTPS GitHub/release-CDN host checks;
- required `update-manifest.json` with app ID/version/stable executable/package name/hash/size;
- SHA-256 and exact-size verification;
- strict one-root-EXE ZIP contract, traversal prevention, size and decompression-ratio limits;
- Windows PE `MZ`, ProductName, and ProductVersion checks;
- same-filesystem replacement staging;
- one retained `Lenticulizer.previous.exe` rollback;
- health token written only after the new WebView2 UI completes the native `bootstrap` handshake;
- automatic restoration/relaunch of the previous executable if the new app does not become healthy.

A matching SHA-256 validates the downloaded bytes against release metadata; it is not publisher signing.

### Release packaging foundation

Running the compiled stable executable with `--package-release <directory>` creates:

- `Lenticulizer_Windows_Portable.zip`
- `update-manifest.json`
- `SHA256SUMS.txt`

The updater ZIP deliberately contains only root `Lenticulizer.exe`.

### Prepared CI

The private source includes `.github/workflows/ci.yml`, a Windows validation workflow that performs source checks, explicit NuGet restores, .NET build/parity tests, self-contained publish, core/runtime verification, and source-archive construction. It does not publish releases or upload release binaries. It has not run on GitHub because application-source publication is not authorized. Interactive Windows updater/UI and live Blender tests remain manual release gates.

### Repository/source guard

- `scripts/root-allowlist.txt`
- `scripts/check_root.py`
- `validation/RootGuardChecks.py`

The guard works with Git metadata when available and has a filesystem fallback for extracted source archives. The test demonstrates a clean pass plus an isolated unapproved-root-file failure.

## Preserved Alpha 31 baseline

- Lenticular Lens and Lens-Free Relief workflows.
- Source ordering/interlacing and 16-bit height/depth maps.
- Automatic / Semi-Automatic / Manual settings.
- LPI, DPI, phase/registration, IOR, viewing angle, lens/base and optional backing controls.
- Alpha 29 compact Images/Optics layout and UI preferences.
- Labeled test-print export workflow.
- Blender add-on v1.18.43.
- Uploaded Project(6) baseline with SHA-256 `54154ce98dae6b232ef486886ecdaf61f5370510abe9c247ad712d002ca99897`.

## Validation completed in the current environment

Passed after Alpha 32 changes:

```text
node --check ui/src/bridge.js
node --check ui/src/renderer.js
node --check ui/src/test-output.js
node validation/BridgeTests.js
node validation/DropUiTests.js
python validation/DesktopHeightmapContractChecks.py
python validation/HeightmapFixtures.py
python validation/BlenderHeightmapChecks.py
python validation/Alpha32FoundationChecks.py
python validation/UpdaterContractChecks.py
python validation/RootGuardChecks.py
python validation/SourceArchiveChecks.py
python -m py_compile validation/*.py scripts/*.py blender/Lenticulizer_Blender_Addon_v1.18.43/*.py
```

The validation environment used Node 22.16.0, Python 3.13.5, NumPy 2.3.5, and Pillow 12.3.0. Results include 30 heightmap fixtures, 33 Blender add-on callback/project/geometry/export checks using API doubles, bridge/drop regressions, Alpha 31 resource/baseline preservation, updater/static-security contracts, archive extra-file/traversal negative controls, and the root-clutter negative control.

Not performed in this environment:

- .NET compiler build of Alpha 32;
- Windows EXE launch;
- real WebView2 timers/focus/download/save behavior;
- actual GitHub release download/install/relaunch;
- real throttling/offline transition testing at the native HTTP layer;
- updater rollback with live processes;
- live Blender installation/viewport/rendering;
- physical print testing.

This environment does not currently provide the .NET 10 SDK and cannot directly obtain Microsoft/NuGet build dependencies, so source/static validation must not be represented as a compiled release.

## First-update migration

Alpha 31 does not contain the new updater, so it cannot update itself to Alpha 32 through this mechanism. The first transition to a compiled Alpha 32 build must be manual.

Once Alpha 32 is installed, subsequent in-place updates use the updater foundation. New packages use `Lenticulizer.exe`. If Alpha 32 itself is launched under an older/custom filename, the updater keeps that path during replacement to preserve existing shortcuts.

## Build and release commands

Windows source build entry:

```text
Build_SelfContained.bat
```

Expected compiled output:

```text
dist\Lenticulizer.exe
```

Expected release assets after the build/Windows-check pipeline:

```text
release\Lenticulizer_Windows_Portable.zip
release\update-manifest.json
release\SHA256SUMS.txt
```

The source pins .NET SDK 10.0.400 and runtime 10.0.11, includes the Fixed WebView2 Runtime build payload, and uses the repository `NuGet.Config` to restore from the official NuGet v3 source instead of inheriting a machine with no configured package source.

## Repository map / root exceptions

Implementation remains in the established `app/`, `backend/`, `ui/`, and `blender/` folders to avoid a risky move during updater development. Tests live in `validation/`, maintenance in `scripts/`, packaging in `packaging/`, documentation in `docs/`, and required vendored runtime assets in `vendor/`.

Root exceptions are the read-first Markdown files, `Lenticulizer.csproj`, `global.json`, `NuGet.Config`, and small build/launch BAT wrappers. The reviewed root allowlist is `scripts/root-allowlist.txt`.

The old root `README.txt` was moved to `docs/releases/legacy-alpha31-readme.txt`; it is historical and is not a build input.


## Git publication runtime handling

The Fixed Version WebView2 runtime is too large for a normal GitHub blob. The public source therefore omits `vendor/FixedRuntime/runtime.zip` from Git history. `Restore_Build_Assets.bat` restores it automatically from the pinned 152.0.4191.62 x64 Fixed Version cabinet. The restore path verifies the cabinet SHA-256, checks every expanded browser file against `vendor/FixedRuntime/manifest.json`, validates critical Microsoft Authenticode signatures, and rebuilds the embedded runtime archive. CI runs this restore before source/build checks.

## Next release gates

1. Fresh-compile Alpha 32 on Windows from an extracted source snapshot without `.git`.
2. Run the built-in core/runtime/UI checks against `dist\Lenticulizer.exe`.
3. Verify stable shortcut behavior and window/settings persistence.
4. Publish a release only when authorized, with all three generated release assets.
5. Test actual GitHub ETag/offline/rate-limit/manual/startup/5-minute/focus behavior.
6. Exercise an Alpha 32 → newer test release download/hash/stage/install/relaunch and a forced-health-failure rollback negative control.
7. Confirm only one rollback remains and app-owned staging/helper/temp cleanup occurs after health.
8. Re-run live Blender integration if desktop bridge behavior changes.
9. Verify hosted CI, exact commit/tag, release assets and hashes before calling the release ready.

## Publication boundary

Do not publish the application source merely because the repository is public. Source-publication scope remains unapproved. Documentation-only repository updates are allowed; application source/binaries/releases require explicit release/publication authorization.

Do not add server setup, Codex CLI automation, unattended workers, payment setup, or API-account setup.
