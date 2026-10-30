# Continuous integration

The prepared Windows CI workflow is `.github/workflows/ci.yml`.

It is intentionally a **validation workflow only**. It does not create a GitHub release, push tags, upload release binaries, change repository visibility, or require repository secrets.

When application source publication is authorized, the workflow is intended to verify:

- root/source layout and negative-control guard;
- JavaScript bridge/UI checks;
- Python raster/Blender/updater/source-package contracts;
- .NET restore through the repository `NuGet.Config`;
- application build;
- .NET parity tests;
- self-contained publish;
- embedded-core and bundled-runtime verification;
- source-archive construction.

The workflow deliberately does **not** run the interactive Windows UI/updater install/relaunch test. GitHub-hosted CI is not treated as proof of an interactive desktop experience. Native WebView2 focus/timer/update-install/rollback and live Blender validation remain explicit release gates in `DEVELOPMENT_HANDOFF.md`.

Do not add release publication or credential-bearing steps without explicit authorization.

The Git checkout does not contain the large `vendor/FixedRuntime/runtime.zip`. CI first runs `Restore_Build_Assets.bat`, which downloads the pinned 152.0.4191.62 x64 Fixed Version cabinet, verifies the cabinet and full expanded file set against the checked-in baseline manifest, validates critical Microsoft signatures, and rebuilds the runtime archive before source/build tests.
