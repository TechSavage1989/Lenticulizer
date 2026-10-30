# Alpha 32 updater foundation

Alpha 32 is the source-development line that follows the confirmed Alpha 31 behavior baseline. It is not yet a published Windows release.

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

Alpha 31 has no updater, so the first move to Alpha 32 must be manual. After Alpha 32, updates can use the new mechanism once a compatible GitHub release feed is actually published and validated.

## Release format

A compatible release must contain these assets:

- `Lenticulizer_Windows_Portable.zip`
- `update-manifest.json`
- `SHA256SUMS.txt`

The portable update ZIP contains only `Lenticulizer.exe`. The manifest identifies `techsavage1989.lenticulizer`, the exact version, package name, package byte count, and package SHA-256.

A matching SHA-256 is integrity verification against the release manifest, not code signing.

## Validation status

Source/static parity, updater contract, unsafe-archive negative controls, and root-clutter negative control pass in the current reconstruction environment.

A fresh .NET build, native Windows launch, real GitHub update cycle, rollback process test, live WebView2 behavior, and live Blender validation remain release gates.
