<h1 align="center">Lenticulizer</h1>

<p align="center">Prepare lenticular and lens-free relief artwork, optical settings, calibration outputs, and Blender previews for 3D printing.</p>

<p align="center">
  <a href="#download">Download</a> |
  <a href="#getting-started">Get started</a> |
  <a href="#features">Features</a> |
  <a href="#updates-and-settings">Updates</a> |
  <a href="#development">Development</a>
</p>

## Features

Lenticulizer is a Windows-first desktop tool for preparing lenticular and lens-free relief prints and keeping those settings synchronized with a Blender add-on.

Current confirmed functionality includes:

- Source-image ordering and interlaced-image generation.
- Lenticular Lens and Lens-Free Relief workflows.
- Automatic, Semi-Automatic, and Manual settings modes.
- LPI, printer-DPI, phase/registration, viewing-angle, IOR, lens/base, and support-backing controls.
- 16-bit height/depth-map generation and reference-heightmap workflows.
- Live 3D preview and Blender project synchronization.
- Calibration outputs.
- Clean production exports plus optional labeled test-print exports.
- Blender add-on workflow with Project & Images, Optics & Calibration, and Output tabs.

## Download

This repository does **not yet have a published GitHub release**. The repository is being bootstrapped from the latest confirmed development baseline before it becomes the authoritative release/update feed.

- [Releases index](https://github.com/TechSavage1989/Lenticulizer/releases)

Do not treat the GitHub repository as an update source until a release is explicitly published and documented here.

## Requirements

Current target:

- Windows x64.
- Portable/self-contained desktop packaging.
- Blender 5.0 for the optional Blender integration.

The latest confirmed development baseline predates repository publication. Native Windows launch, updater installation behavior, and live Blender interaction must be revalidated from the repository-built artifacts before a GitHub release is called ready.

## Getting started

No repository-hosted binary is available yet.

For development continuation, read these first:

1. [AGENTS.md](AGENTS.md)
2. [DEVELOPMENT_HANDOFF.md](DEVELOPMENT_HANDOFF.md)
3. [Alpha 31 baseline notes](docs/releases/alpha31-baseline.md)

A user-facing download procedure will be added here when the first verified GitHub release is published.

## How to use

The established workflow is:

1. Add and order source images.
2. Choose Lenticular Lens or Lens-Free Relief.
3. Set print dimensions, lens direction, LPI, printer DPI, and phase/registration.
4. Review calculated optical settings and adjust only the controls allowed by the selected settings mode.
5. Generate the interlaced image and height/depth map.
6. Review the live 3D preview or synchronize the project to Blender.
7. Export clean production files, calibration outputs, or an optional labeled test set.

The Blender add-on mirrors the same workflow while keeping the selected-source, interlaced-image, heightmap, and lens/prism inspection viewers in the project workspace.

## Updates and settings

The GitHub repository currently has **no published release feed**, and the recoverable maintainable source inspected during repository bootstrap does **not contain a production updater implementation**.

The intended updater behavior is documented in [DEVELOPMENT_HANDOFF.md](DEVELOPMENT_HANDOFF.md). It must be implemented and validated before this repository is used as the live update feed.

Portable packaging should keep the executable name stable and store mutable settings, logs, cache, downloads, and staging data in per-user application storage rather than beside the executable.

## Troubleshooting

Until the first repository-built release is published:

- Do not assume the GitHub Releases page contains the current application.
- Do not replace a known-working local build solely because this repository exists.
- Preserve one known-good rollback build while repository migration and updater validation are in progress.
- For Blender integration, keep the desktop app and add-on versions documented as a matched pair.

## Development

Start with:

- [AGENTS.md](AGENTS.md) — read-first repository and workflow rules.
- [DEVELOPMENT_HANDOFF.md](DEVELOPMENT_HANDOFF.md) — current baseline, source status, validation state, and next work.
- [docs/releases/alpha31-baseline.md](docs/releases/alpha31-baseline.md) — last confirmed pre-repository functional baseline.

The repository currently contains documentation only. Application source has **not** been published here yet because source-publication scope must be explicit.

No repository license has been established, so this README does not claim one.
