# DEVELOPMENT_HANDOFF.md

## Current status

**Corrective Alpha 34 release target:** Lenticulizer **v3.0.0-alpha.34** for Windows x64, preserving Blender add-on **v1.18.43**. Alpha 32 and 33 successfully detect updates but cannot finalize their downloads because HashFile opens the temporary ZIP while an exclusive FileStream writer remains open. On Windows this produces an IOException, and the UI remains at the last progress reading. The change closes streams before hashing, shows verification, displays a retryable error after failure, and sets a 60-second per-read timeout. Native negative-control and success tests are added. Verify the Alpha 34 release tag/hosted workflow/assets before claiming publication. Affected users must install Alpha 34 manually; test the corrected updater with a later Alpha 35 prerelease.

**Previous published prerelease:** Lenticulizer **v3.0.0-alpha.33** for Windows x64, with Blender add-on **v1.18.43**. This is an intentionally small updater smoke-test version, not a production verification of the updater.

- Release: https://github.com/TechSavage1989/Lenticulizer/releases/tag/v3.0.0-alpha.33
- Tag/validated release commit: `1a0b2c78b025c875121b0531131beb469cf15356`
- Hosted Windows validation and release job: https://github.com/TechSavage1989/Lenticulizer/actions/runs/41161318073 (completed successfully)
- GitHub API release feed now lists Alpha 33 first, then Alpha 32. The release has all five assets uploaded.
- Downloadable portable ZIP: 549,160,151 bytes, SHA-256 `880440f0a5c759a83e367592c0fb4b31e47f97aff9f37d850f49a6064cedb8b8`.
- Matching source ZIP: 375,267,751 bytes, SHA-256 `47357df3c7715ddf00fc60e4a3f7064cb0adec8dd6aef29abb900edf57309ad4`.
- Blender add-on ZIP (unchanged): SHA-256 `975854f306081f4f374acd02b361bc3130b8c349bdfa685b343246bfe775fdd0`.
- Update manifest SHA-256: `c427abd6b333b3738244ff925a7cfea42d62a904a79017be0ecafe255737b756`. SHA256SUMS.txt SHA-256: `840463793ef485e05fb94fbf0d063cd3e5b3a081b8c0e6295efa2a343dc11996`.
- The Windows runner's printed portable and source hashes matched the uploaded GitHub asset digests. Actual Alpha 32-to-33 update/restart/rollback on the user's Windows PC remains unverified.

**Previous published updater baseline:** Lenticulizer **v3.0.0-alpha.32** for Windows x64, with Blender add-on **v1.18.43**.

- Public repository: https://github.com/TechSavage1989/Lenticulizer
- Default branch: `main`
- Release: https://github.com/TechSavage1989/Lenticulizer/releases/tag/v3.0.0-alpha.32
- Exact release commit/tag: `db2af51e311f0d9df2846d608f9a6f47ba1e92e9`
- Hosted Windows validation and release job: https://github.com/TechSavage1989/Lenticulizer/actions/runs/41159999807
- Latest user-confirmed pre-repository behavior baseline: Alpha 31 + add-on 1.18.43.
- Alpha 32 native Windows CI succeeded. End-to-end updater installation/rollback and live Blender viewport interaction remain unverified.

Source and binary publication were explicitly approved. GitHub is now the public source and prerelease feed. Do not overwrite the Alpha 32 tag or its assets; future updates require new versions and tags.

## Alpha 32 baseline release files and checksums

The Alpha 32 release contains:

| File | Purpose | SHA-256 |
| --- | --- | --- |
| `Lenticulizer_Windows_Portable.zip` | Self-contained Windows app with stable `Lenticulizer.exe` | `0eb3262a83aa79c1fd203d3aa87dca0c939035b1ac3b32ad0107128bb39e5171` |
| `Lenticulizer_3D_Blender_Addon_v1.18.43.zip` | Matching Blender 5.0 add-on | `975854f306081f4f374acd02b361bc3130b8c349bdfa685b343246bfe775fdd0` |
| `Lenticulizer_v3.0.0-alpha.32_Source.zip` | Source/build archive including runtime assets | `497915aaf7d557d3f183b1db025486b8bab7620e146d477666b94d26315b2dfd` |
| `update-manifest.json` | Release identity/version/package/hash/size contract | `ad7a6745c27238f160fdbe5c048f51918e864554c1832e81cd7b041af324b189` |
| `SHA256SUMS.txt` | Published checksums | `f7d93169ab0591122bfc9edbca94af3f74c1bb2ec03a73070f1e02ce992c8a6d` |

Digests and uploaded asset sizes were verified against the GitHub release API. The release tag resolves to the exact successful workflow commit. These are integrity checks, **not publisher code signing**.

## Functional baseline retained

- Lenticular Lens and Lens-Free Relief workflows.
- Source image ordering/interlacing and 16-bit height/depth maps.
- Automatic / Semi-Automatic / Manual settings modes.
- LPI, DPI, phase/registration, IOR, viewing angle, lens/base and optional backing controls.
- Alpha 29 compact Images/Optics layout and layout preferences.
- Clean production outputs and optional labeled test-print export.
- Blender add-on 1.18.43 with Project & Images, Optics & Calibration, and Output tabs.
- User-provided `Lenticulizer_3D_Project(6).blend` baseline, recorded SHA-256 `54154ce98dae6b232ef486886ecdaf61f5370510abe9c247ad712d002ca99897`.

## Windows portable/update design

- New portable executable name: `Lenticulizer.exe`, without version suffix.
- In-place updates preserve an existing custom/versioned executable path so shortcuts are not silently broken.
- Window placement: `%LOCALAPPDATA%\Lenticulizer\Settings\window.json`.
- Logs/runtime/WebView2/session state remain in per-user application data.
- Update cache, downloads, staging, helper, and health markers: `%LOCALAPPDATA%\Lenticulizer\Updates`.
- One retained `Lenticulizer.previous.exe` rollback executable.

The native update service provides startup, five-minute, and focus-return checks; ETag/cached requests; offline/error states; manual cooldown, retry and rate-limit backoff; explicit Download and Install and restart; host and manifest validation; size/SHA-256 validation; strict one-EXE ZIP/PE/product/version checks; staging; health-confirmed relaunch; and rollback on failure.

**Alpha 31 has no updater.** The first transition to Alpha 32 is manual. Do not claim the Alpha 32 updater successfully upgrades to a later version until an actual previous-version-to-new-release test has passed.

## Source map and build

- `app/`: Windows shell, WebView2 host, updater, app preferences and packaging.
- `backend/`: processing, optics, project/Blender integration.
- `ui/`: embedded browser HTML/CSS/JavaScript.
- `blender/`: current add-on source and ZIP.
- `validation/`: core/Windows/Blender fixtures and regression/contract checks.
- `scripts/`: runtime restoration, root allowlist and maintenance.
- `packaging/`: runtime/source packaging.
- `vendor/`: pinned WebView2 manifest/notices and restored runtime assets.
- `docs/`: architecture and release history.
- `.github/workflows/ci.yml`: Windows validation, artifacts and gated prerelease publishing.

Expected Windows source build command: `Build_SelfContained.bat`.

Toolchain: .NET SDK 10.0.400 with patch roll-forward, x64 Windows, local `NuGet.Config`, Python and Node for validation. The workflow restores pinned Microsoft WebView2 Fixed Version 152.0.4191.62 from a checked HTTPS cabinet and checks archive/file hashes and Microsoft signatures; the large runtime ZIP is not tracked in Git.

Expected portable output: `dist\Lenticulizer.exe`. Release packager creates `Lenticulizer_Windows_Portable.zip`, `update-manifest.json` and `SHA256SUMS.txt`. The release also includes the paired Blender add-on and complete source package.

Root exceptions are only the read-first Markdown files, required .NET configuration and build wrappers. See `scripts/root-allowlist.txt`. The guard and negative control work both in a checkout and a clean extracted source archive without `.git`.

## Validation at release commit

The successful Windows workflow `41159999807` performed:

- JavaScript bridge/drop and source syntax/DOM contracts.
- 30 Python heightmap fixtures and 33 Blender API-double regression checks.
- Root-layout guard, deliberate-clutter negative control and source archive plan.
- Explicit NuGet restore and .NET 10 application compilation (zero compiler warnings/errors reported in the main build).
- 57,512 core heightmap checks and 30 cross-language maps.
- 48,647 runtime compatibility checks, including 360 matching PNG16 arrays.
- 119 drop-import tests and 2,246 actual integrated application checks, including 12 direct-processing output pairs.
- Imported heightmap vertical/horizontal stripe-phase tests, with the source fitted correctly before sampling.
- Verification of 557 actual bundled runtime files.
- Self-contained publish, embedded-core/runtime verification, Windows UI-check script, portable package, source package and release artifact upload.
- GitHub release job, unique prerelease tag and all five uploaded release assets.

The Alpha 32 phase-test regression was caused by the test comparing fitted output pixels with unfitted source-center colors. The corrected test retains gradient source images, checks each output coordinate against the correctly fitted source image, and includes a negative control against the flawed old assumption.

**Not yet validated as an end-to-end real installed workflow:** manual Alpha 31-to-32 migration on the user's system; real Windows focus/interval/offline/rate-limit behavior across app sessions; Alpha 32-to-next-version download/stage/restart; health-timeout forced rollback; custom-shortcut preservation; live Blender viewport rendering; physical printing.

## Next development and release gates

1. Test the published Alpha 32 ZIP on a normal Windows PC with actual user projects and Blender 5.0 integration.
2. Verify Alpha 34's Windows file-sharing negative control and native hash success case. Manually replace Alpha 32/33 with the Alpha 34 executable. Create a new Alpha 35 test release to exercise the **actual corrected updater** (download, verification, staging, install, relaunch, settings/shortcut preservation, cleanup and rollback). Do not overwrite released tags.
3. Exercise offline/rate-limit, partial download, tampered package, active-operation and failed-health negative controls on native Windows.
4. Verify only one rollback and no extra app-owned staging remain.
5. Address any release issues before describing the automatic updater as production-verified.
6. Keep README, AGENTS and this handoff current, revalidate hosted CI, and publish future releases with exact artifacts/hashes.

No server setup, Codex CLI automation, unattended workers, payment setup or API-account setup.
