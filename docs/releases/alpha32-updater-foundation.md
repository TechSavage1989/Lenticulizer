# Alpha 32 updater foundation

Alpha 32 is the source-development line following the confirmed Alpha 31 behavior baseline. It is not yet a published Windows release.

## Scope

- Stable new-package executable name: `Lenticulizer.exe`.
- Per-user window/update state.
- GitHub Releases update-check/download/install foundation.
- Explicit user-controlled download and restart.
- Manifest/hash/archive/PE/product/version validation.
- Same-filesystem replacement staging and one rollback executable.
- UI-health-confirmed relaunch with rollback on failure.
- Release-manifest/package generation helper.
- Archive-compatible root-layout guard and negative control.

## Compatibility

Application processing behavior, Blender add-on v1.18.43, Project(6) baseline, and Alpha 31 labeled-test outputs are intended to remain unchanged.

Alpha 31 has no updater, so the first move to Alpha 32 must be manual.

## Release format

A compatible release must contain:

- `Lenticulizer_Windows_Portable.zip`
- `update-manifest.json`
- `SHA256SUMS.txt`

The update ZIP contains only `Lenticulizer.exe`. The manifest identifies `techsavage1989.lenticulizer`, exact version, package name, byte count, and SHA-256.

A matching SHA-256 verifies integrity against release metadata; it is not code signing.

## Validation status

Private source/static parity, updater contract, unsafe-archive negative controls, and root-clutter negative control pass, including checks from a fresh extracted source archive without `.git`.

Fresh .NET compilation, native Windows/WebView2 launch, real GitHub update/relaunch/rollback, and live Blender validation remain release gates.
