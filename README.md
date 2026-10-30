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

**No Alpha 32 binary has been published yet.** This source snapshot is a development foundation and is not the live update feed.

- [GitHub releases index](https://github.com/TechSavage1989/Lenticulizer/releases)

The first repository-backed release must be built and validated on Windows before the app starts relying on GitHub Releases for updates. Do not treat an empty or failed update check as proof that the installed app is current.


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

There is no repository-hosted Alpha 32 executable yet. To validate this source on Windows:

1. Extract the complete source archive.
2. Install or make available .NET SDK 10.0.400.
3. Run `Build_SelfContained.bat` from the source root.
4. The build performs its required checks and writes the stable executable to `dist\Lenticulizer.exe`.
5. Release packaging writes `Lenticulizer_Windows_Portable.zip`, `update-manifest.json`, and `SHA256SUMS.txt` under `release\`.

A local build is not automatically a release candidate. Complete the Windows updater and launch checks documented in `DEVELOPMENT_HANDOFF.md` first.

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

Alpha 32 source introduces the repository-backed updater foundation. It is **not yet a published or native-Windows-validated update feed**.

Designed behavior:

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

- **No update is shown:** the GitHub release feed is not live until a compatible release with the required manifest/assets is published. Offline or failed checks should say so explicitly.
- **Update cannot restart:** finish any active build, file dialog, or Blender action before using **Install and restart**.
- **A new version fails to open:** the updater is designed to restore the one retained previous executable when the new version does not report a healthy UI startup.
- **Blender behavior differs:** keep the desktop app and documented add-on version paired. The current source baseline uses Blender add-on v1.18.43 and the Project(6) Blender scene baseline.

## Development

Read these first:

- [AGENTS.md](AGENTS.md)
- [DEVELOPMENT_HANDOFF.md](DEVELOPMENT_HANDOFF.md)
- [Alpha 31 baseline](docs/releases/alpha31-baseline.md)
- [Alpha 32 updater foundation](docs/releases/alpha32-updater-foundation.md)
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

The current recovery environment could not perform a fresh .NET compile or Windows/WebView2/live-Blender validation. See the handoff for the exact remaining release gates.

No repository license has been established, so this README does not claim one.
