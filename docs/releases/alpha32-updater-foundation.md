# Alpha 32 updater foundation

Alpha 32 is a published Windows x64 portable prerelease following the confirmed Alpha 31 behavior baseline. Release tag: [v3.0.0-alpha.32](https://github.com/TechSavage1989/Lenticulizer/releases/tag/v3.0.0-alpha.32).

## Scope

- Stable new-package executable name: `Lenticulizer.exe`.
- Per-user window/update state rather than mutable state beside the executable.
- GitHub Releases update-check/download/install foundation.
- Explicit user-controlled download and restart.
- Package/hash/identity validation.
- Same-filesystem replacement staging and one rollback executable.
- UI-health-confirmed relaunch with rollback on failure.
- Release-manifest/package generation helper.
- Root-layout allowlist and archive-compatible guard.

## Compatibility

Application behavior, image processing, Blender add-on v1.18.43, Project(6) baseline, and Alpha 31 labeled-test outputs are intended to remain unchanged.

Alpha 31 has no updater, so the first move to Alpha 32 is manual. The GitHub release feed is now published; end-to-end use of the Alpha 32 updater still needs a later test release and real Windows install/restart/rollback validation.

## Release format

A compatible release must contain these assets:

- `Lenticulizer_Windows_Portable.zip`
- `update-manifest.json`
- `SHA256SUMS.txt`

The portable update ZIP contains only `Lenticulizer.exe`. The manifest identifies `techsavage1989.lenticulizer`, the exact version, package name, package byte count, and package SHA-256.

A matching SHA-256 is integrity verification against the release manifest, not code signing.

## Validation status

The release commit `db2af51e311f0d9df2846d608f9a6f47ba1e92e9` passed [Windows source and native parity CI](https://github.com/TechSavage1989/Lenticulizer/actions/runs/41159999807), including compilation, runtime/heightmap/Blender-double tests, Windows UI-check script, packaging, and upload of all five assets. The GitHub tag points to that commit.

Actual use on the user's Windows machine, an installed Alpha 32-to-next-version update, live rollback/health failure, and live Blender viewport rendering remain unverified.
