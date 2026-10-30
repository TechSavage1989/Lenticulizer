# DEVELOPMENT_HANDOFF.md

## Current status

Repository bootstrap date: 2026-10-30

Repository: `TechSavage1989/Lenticulizer`

Default branch: `main`

Repository visibility observed during bootstrap: public.

At bootstrap, the repository contained only a minimal README and had no releases or pull requests. This documentation bootstrap does not publish application source or binaries.

## Latest confirmed functional baseline

Desktop application: **Lenticulizer v3.0.0-alpha.31**

Blender add-on: **v1.18.43**

Baseline details: `docs/releases/alpha31-baseline.md`

Important: Alpha 31 was produced before this repository became the development baseline. The available validation record states that Alpha 31 was assembled from the already-compiled Alpha 30 self-contained application plus updated embedded-interface/add-on resources; it was not a fresh C# compiler build.

## Maintainable-source status

The latest recoverable source archive inspected during bootstrap is older than the functional baseline:

- Alpha 26 self-contained source is recoverable.
- Alpha 27 Help/About source is recoverable.
- Later Alpha 28–31 changes were validated and packaged during prior development, but a complete current Alpha 31 source tree has not yet been established in GitHub.

Therefore:

- do not treat Alpha 27 source as equivalent to Alpha 31;
- do not regress to an older source archive merely because it is easier to build;
- reconstruct or reconcile later changes before declaring the repository source current.

## Current known feature baseline

Alpha 31 / add-on 1.18.43 includes the established capabilities from prior development, including:

- Lenticular Lens and Lens-Free Relief modes;
- source-image ordering and interlacing;
- 16-bit height/depth-map workflow;
- Automatic / Semi-Automatic / Manual settings;
- LPI, DPI, phase/registration, viewing-angle, IOR, lens/base, and backing controls;
- live 3D preview;
- Blender synchronization;
- user-supplied Blender baseline scene from `Lenticulizer_3D_Project(6).blend`;
- Blender three-tab workflow:
  - Project & Images;
  - Optics & Calibration;
  - Output;
- labeled test-print export set in both desktop app and add-on;
- clean normal production exports remain separate from labeled test outputs.

## Blender baseline

The last user-supplied scene baseline was `Lenticulizer_3D_Project(6).blend`.

Previously recorded SHA-256:

`54154ce98dae6b232ef486886ecdaf61f5370510abe9c247ad712d002ca99897`

Do not reconstruct or resave the baseline unnecessarily. Preserve uploaded bytes when embedding unless a deliberate Blender-scene change is requested.

## Update-feed status

There is currently **no GitHub release feed** for Lenticulizer.

The recoverable maintainable desktop source inspected during bootstrap contains no production GitHub updater implementation.

Before enabling GitHub Releases as the app's updater feed, implement and validate the updater requirements in `AGENTS.md`.

Stable executable naming, per-user mutable state, safe staging, rollback, hash validation, release allowlisting, and healthy-window confirmation are part of the required design.

## Repository/source migration next step

Do not publish application source solely because this repository is public.

Before source migration:

1. Confirm approved source-publication scope.
2. Reconstruct/reconcile the current Alpha 31 source from the latest recoverable source plus later validated changes.
3. Build from that reconciled source.
4. Compare behavior/output against the Alpha 31 baseline.
5. Organize the source tree.
6. Add the root-layout guard and CI.
7. Rebuild from a fresh source archive without `.git`.
8. Only then establish the repository as authoritative.

## Validation facts inherited from Alpha 31

Recorded pre-repository validation included raster/export checks, cross-language label-plan checks, browser-interface tests with doubles, add-on export/operator tests with Blender API doubles, existing heightmap/raster regression tests, and package-integrity assertions.

Not executed in that validation:

- Windows EXE launch;
- real WebView2 save/download behavior;
- live Blender installation/interaction;
- physical printer testing.

Do not upgrade those historical checks into stronger claims.

## Build/test commands

The current repository does not yet contain an authoritative current source tree, so there is no repository build command that should be advertised as producing Alpha 31.

Older recoverable source used .NET SDK 10.0.400 and Windows self-contained build scripts, but those commands must be revalidated after source reconciliation.

## Settings/storage paths

The final repository implementation must document the actual per-user settings, logs, cache, download, staging, and rollback paths after the portable/update refactor.

Do not persist mutable settings beside the executable.

## Known limitations / open work

- Current source baseline has not yet been migrated to GitHub.
- No GitHub release/update feed exists.
- Production updater requirements are not implemented in the recoverable source.
- Stable non-versioned Windows launch filename/update migration is not yet repository-validated.
- Windows-native and live-Blender validation must be rerun from repository-built artifacts.
- Repository root guard/CI should be added together with source migration, not before the source map is known.

## Approved project scope carried forward

Preserve working Lenticulizer functionality and the Blender integration unless explicitly requested otherwise.

Do not add server setup, Codex CLI automation, unattended workers, payment setup, or API-account setup.
