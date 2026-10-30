<h1 align="center">Lenticulizer</h1>

<p align="center">Prepare lenticular and lens-free relief artwork, optical settings, calibration outputs, and Blender previews for 3D printing.</p>

<p align="center"><a href="#download">Download</a> | <a href="#getting-started">Get started</a> | <a href="#features">Features</a> | <a href="#updates-and-settings">Updates</a> | <a href="#development">Development</a></p>

## Features

Lenticulizer is a Windows-first desktop tool for preparing lenticular and lens-free relief prints and synchronizing projects with its Blender add-on.

- Source-image ordering and interlaced-image generation.
- Lenticular Lens and Lens-Free Relief modes.
- Automatic, Semi-Automatic, and Manual settings modes.
- LPI, printer-DPI, phase/registration, viewing-angle, IOR, lens/base, and support-backing controls.
- 16-bit height/depth-map generation and reference-heightmap workflows.
- Live 3D preview and Blender project synchronization.
- Calibration outputs.
- Clean production exports plus optional labeled test-print exports.

## Download

There is **no published GitHub binary release yet**. The repository is still being prepared as the authoritative release/update feed.

- [Releases index](https://github.com/TechSavage1989/Lenticulizer/releases)

The latest confirmed functional baseline is Alpha 31 with Blender add-on v1.18.43. Alpha 32 is the current source-development line for stable packaging and updater work, but it has not been native-Windows validated or published.

## Requirements

Current target:

- Windows x64.
- Portable/self-contained desktop packaging.
- Blender 5.0 for optional Blender integration.

The first repository-backed release must complete the Windows/WebView2/updater validation documented in [DEVELOPMENT_HANDOFF.md](DEVELOPMENT_HANDOFF.md).

## Getting started

No repository-hosted executable is available yet.

For development continuation, read:

1. [AGENTS.md](AGENTS.md)
2. [DEVELOPMENT_HANDOFF.md](DEVELOPMENT_HANDOFF.md)
3. [Alpha 31 baseline](docs/releases/alpha31-baseline.md)
4. [Alpha 32 updater foundation](docs/releases/alpha32-updater-foundation.md)

## How to use

The established workflow is:

1. Add and order source images.
2. Choose Lenticular Lens or Lens-Free Relief.
3. Set print dimensions, lens direction, LPI, printer DPI, and phase/registration.
4. Review calculated optical settings and adjust only the controls allowed by the selected settings mode.
5. Generate the interlaced image and height/depth map.
6. Review the live 3D preview or synchronize the project to Blender.
7. Export clean production files, calibration outputs, or an optional labeled test set.

## Updates and settings

Alpha 32 source now contains the updater foundation, but the GitHub release feed is **not live yet**.

The source design includes startup, five-minute, and focus-return checks; ETags/caching; rate-limit/backoff handling; explicit offline/error states; user-controlled Download and Install and restart actions; package/hash/identity validation; safe staging; one rollback; and UI-health-confirmed relaunch.

New packaged builds use the stable filename `Lenticulizer.exe`. Mutable state is designed to remain under the current user's local application data rather than beside the executable.

A SHA-256 match verifies bytes against the release manifest; it is not publisher signing.

## Troubleshooting

Until the first repository-backed release is published:

- Do not assume the Releases page contains the current application.
- Preserve a known-good Alpha 31 rollback while Alpha 32 is compiled and native-tested.
- Alpha 31 has no updater, so the first move to a compiled Alpha 32 build must be manual.
- Keep desktop and Blender add-on versions paired as documented.

## Development

Read [AGENTS.md](AGENTS.md) and [DEVELOPMENT_HANDOFF.md](DEVELOPMENT_HANDOFF.md) first.

The public repository intentionally remains documentation-only until application-source publication is explicitly authorized. The Alpha 32 source foundation has been reconstructed and source/static validated privately, including the archive/root guard and updater contract checks.

No repository license has been established, so this README does not claim one.
