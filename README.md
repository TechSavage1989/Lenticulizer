<h1 align="center">Lenticulizer</h1>

<p align="center">Prepare lenticular and lens-free relief artwork, optical settings, calibration outputs, and Blender previews for 3D printing.</p>

<p align="center"><a href="#download">Download</a> | <a href="#getting-started">Get started</a> | <a href="#features">Features</a> | <a href="#updates-and-settings">Updates</a> | <a href="#development">Development</a></p>

## Features

Lenticulizer is a Windows-first desktop tool for preparing lenticular and lens-free relief prints and synchronizing projects with its Blender add-on.

- Order source images and generate interlaced artwork.
- Build Lenticular Lens or Lens-Free Relief output.
- Use Automatic, Semi-Automatic, or Manual settings modes.
- Work with LPI, printer DPI, phase/registration, viewing angle, IOR, lens/base, and optional support-backing controls.
- Generate and inspect 16-bit height/depth maps, including reference-heightmap workflows.
- Review a live 3D preview and synchronize the project with Blender.
- Generate calibration outputs.
- Export clean production files or a separate labeled test-print set.
- Use the paired Blender add-on v1.18.43 with Project & Images, Optics & Calibration, and Output tabs.


## Download

**Alpha 33 is published as a Windows x64 updater smoke-test prerelease.** Start from Alpha 32 to test in-app detection, download, installation and relaunch. Alpha 31 still requires a manual upgrade to Alpha 32 first.

- [GitHub releases index](https://github.com/TechSavage1989/Lenticulizer/releases) — find current prereleases and future versions.
- [Alpha 32 prerelease details](https://github.com/TechSavage1989/Lenticulizer/releases/tag/v3.0.0-alpha.32).
- [Alpha 33 update-test prerelease](https://github.com/TechSavage1989/Lenticulizer/releases/tag/v3.0.0-alpha.33).
- [Download the Windows portable ZIP](https://github.com/TechSavage1989/Lenticulizer/releases/download/v3.0.0-alpha.32/Lenticulizer_Windows_Portable.zip).
- [Blender add-on v1.18.43](https://github.com/TechSavage1989/Lenticulizer/releases/download/v3.0.0-alpha.32/Lenticulizer_3D_Blender_Addon_v1.18.43.zip).

The portable ZIP contains the self-contained `Lenticulizer.exe`. It is not an installer. This prerelease has passed hosted Windows build/parity/UI checks, but its live updater-install/rollback path and Blender viewport behavior still require user-device verification.

The separate 375 MB source archive is for developers; normal users only need the Windows portable ZIP. Release assets include `update-manifest.json` and `SHA256SUMS.txt` for integrity checks.

The Git repository intentionally does not store the roughly 357 MB Fixed Version WebView2 runtime as a normal Git blob. The build restores the pinned 152.0.4191.62 x64 cabinet, verifies its SHA-256, validates every expanded runtime file against the checked-in manifest, checks critical Microsoft signatures, and then recreates the embedded runtime archive. Release source archives may include the restored runtime for offline/reproducible builds.

## Requirements

For users of a future packaged build:

- Windows x64 is the current target.
- The packaged application is intended to be portable and self-contained.
- Blender 5.0 is optional and needed only for Blender integration.

For source builds:

- .NET SDK 10.0.400.
- The included Fixed WebView2 Runtime build assets under `vendor/FixedRuntime/`.
- `NuGet.Config` pins restore to the official NuGet v3 source so builds do not depend on machine-specific package-source settings.
- Release/source validation requires Node.js plus Python with `validation/requirements.txt`; they are not runtime dependencies of the packaged Windows application. The current validation environment used Node 22.16.0 and Python 3.13.5.


## Getting started

1. Open the [GitHub releases index](https://github.com/TechSavage1989/Lenticulizer/releases), choose the current Windows prerelease, and download `Lenticulizer_Windows_Portable.zip`.
2. Extract the ZIP into a **new folder** such as `Documents\Lenticulizer`. Do not launch the EXE from inside the ZIP.
3. Run `Lenticulizer.exe`. No .NET SDK, Visual Studio, or separate WebView2 install is required for the bundled portable application.
4. Add images and generate an interlaced image or heightmap to verify your workflow.
5. Optional: install the matching Blender add-on v1.18.43 and open/sync a project to Blender 5.0.

**Upgrading from Alpha 31:** Alpha 31 cannot download this update itself. Close Alpha 31 and start Alpha 32 manually from its new folder. Keep your previous Alpha 31 folder as a rollback until you verify your projects and Blender integration.

**Testing Alpha 32 to Alpha 33:** Open the installed Alpha 32 application, select **Help > Updates**, and use **Check for updates** if the automatic check has not yet found the published Alpha 33 release. Click **Download**, then **Install and restart**. Confirm the original shortcut starts the new build, the title bar and Help/About show Alpha 33, and your projects/settings still work. See the [native test checklist](docs/releases/alpha33-updater-smoke-test.md).

For development, the source build entry remains `Build_SelfContained.bat`; see [Development](#development).

## How to use

1. Add and order source images.
2. Choose Lenticular Lens or Lens-Free Relief.
3. Set print size, lens direction, LPI, printer DPI, and phase/registration.
4. Review the calculated optical settings and adjust the controls available in the selected settings mode.
5. Generate the interlaced image and height/depth map.
6. Review the live 3D preview or synchronize the project to Blender.
7. Export production files, calibration outputs, or an optional labeled test set.

Normal production exports stay clean. Labeled test output is generated separately so test settings do not become part of production artwork or raised heightmap geometry.

## Updates and settings

Alpha 32 is the first published prerelease containing the GitHub Releases updater. Alpha 33 is its first deliberately small updater smoke-test target. The Windows build and packaged UI passed hosted CI; **the live download/install/relaunch/rollback experience has not yet been tested end to end against a newer release**.

Implemented design (some interactions still require native-device validation):

- Check in the background at startup.
- Check every five minutes while the app is running and on focus return when at least two minutes have passed.
- Use single-flight requests, ETags, cached release metadata, manual-check cooldowns, and GitHub rate-limit/backoff information.
- Report offline or failed checks as unavailable/errors rather than “up to date.”
- Never download or restart automatically.
- Show explicit **Download** and **Install and restart** actions.
- Verify the release manifest, expected package SHA-256, archive layout, Windows PE identity, product identity, and version before installing.
- Stage safely, retain one rollback executable, and restore it if the new app does not complete its UI health handshake.

A SHA-256 match verifies bytes against the release manifest; it is **not publisher code signing**.

New packages use the stable filename `Lenticulizer.exe`. In-place updates preserve the executable path already used by the current installation so an older custom/versioned shortcut is not silently broken.

Mutable state is kept under the current Windows user's local application data, including:

- `Lenticulizer\Settings`
- `Lenticulizer\Logs`
- `Lenticulizer\Runtime`
- `Lenticulizer\WebView2`
- `Lenticulizer\Sessions`
- `Lenticulizer\Updates`

## Troubleshooting

- **No update is shown:** Verify the Alpha 33 prerelease has been published with its portable ZIP and update manifest, then retry Help > Updates from Alpha 32. An offline or failed check must not say you are up to date.
- **Update cannot restart:** finish any active build, file dialog, or Blender action before using **Install and restart**.
- **A new version fails to open:** the updater is designed to restore the one retained previous executable when the new version does not report a healthy UI startup.
- **Blender behavior differs:** keep the desktop app and documented add-on version paired. The current source baseline uses Blender add-on v1.18.43 and the Project(6) Blender scene baseline.

## Development

Read these first:

- [AGENTS.md](AGENTS.md)
- [DEVELOPMENT_HANDOFF.md](DEVELOPMENT_HANDOFF.md)
- [Alpha 31 baseline](docs/releases/alpha31-baseline.md)
- [Alpha 32 updater foundation](docs/releases/alpha32-updater-foundation.md)
- [Alpha 33 updater smoke-test plan](docs/releases/alpha33-updater-smoke-test.md)
- [Prepared CI validation](docs/CI.md)

Primary source checks available in an extracted archive without `.git`:

```text
node validation/BridgeTests.js
node validation/DropUiTests.js
python validation/DesktopHeightmapContractChecks.py
python validation/HeightmapFixtures.py
python validation/BlenderHeightmapChecks.py
python validation/Alpha32FoundationChecks.py
python validation/UpdaterContractChecks.py
python validation/RootGuardChecks.py
python validation/SourceArchiveChecks.py
```

`validation/RootGuardChecks.py` includes a clean-tree check and an isolated unapproved-root-file negative control.

Windows GitHub CI built and validated the Alpha 32 executable at release commit [db2af51](https://github.com/TechSavage1989/Lenticulizer/commit/db2af51e311f0d9df2846d608f9a6f47ba1e92e9). See the [successful workflow](https://github.com/TechSavage1989/Lenticulizer/actions/runs/41159999807) for source, runtime, .NET parity, UI-check, packaging, and archive results. End-to-end updater installation/rollback on an existing user's Windows system and live Blender rendering are not yet verified.

No repository license has been established, so this README does not claim one.
