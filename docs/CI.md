# Continuous integration

The Windows CI workflow is `.github/workflows/ci.yml`.

On each push to `main` and pull request it validates source and creates **private workflow artifacts**. It publishes a GitHub prerelease only through its gated release job after successful validation and an authorized release trigger. The Alpha 32 prerelease was approved and published on the verified release-trigger commit; routine source/documentation commits do **not** create new releases.

## Validations

- Root/source layout, clean extracted-source archive and negative controls.
- JavaScript bridge/UI checks and Python raster/Blender/updater/source-package contracts.
- .NET restore through the repository `NuGet.Config`.
- Windows x64 build and native .NET parity/integration tests.
- Self-contained `Lenticulizer.exe` publish.
- Embedded core and WebView2 Fixed Version runtime verification.
- Windows UI-check script, source archive, portable ZIP and manifest/checksum creation.
- Uploaded workflow artifacts and gated prerelease creation.

The source checkout omits the large `vendor/FixedRuntime/runtime.zip`. CI first runs `Restore_Build_Assets.bat`, which downloads the pinned 152.0.4191.62 x64 cabinet, verifies the archive and extracted files against the checked-in hashes, checks critical Microsoft signatures and reconstructs the embedded runtime ZIP.

The first successful published release workflow was [run 41159999807](https://github.com/TechSavage1989/Lenticulizer/actions/runs/41159999807) at commit `db2af51e311f0d9df2846d608f9a6f47ba1e92e9` with prerelease tag `v3.0.0-alpha.32`.

## Validation limits

The Windows UI-check script and executable parity tests ran in CI. They do **not** prove a complete user-driven update experience. Real focus/timer/offline/rate-limit behavior, end-to-end updater download/install/relaunch/rollback, settings/shortcut persistence and live Blender viewport/render tests remain separate release gates. Do not claim they passed until performed.

A matching SHA-256 verifies file integrity against the release metadata but is not publisher signing. No additional secrets or user credentials are needed to use the published ZIP.
