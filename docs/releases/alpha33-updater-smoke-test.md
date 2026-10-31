# Alpha 33 updater smoke test

## Scope

Lenticulizer v3.0.0-alpha.33 is a small Windows portable release for testing an Alpha 32-to-Alpha 33 in-app update. It changes .NET version metadata, UI/About version text, a visible update-test note, manifest release notes, Windows CI release/version references, and matching source contracts/documentation.

The image-processing engines, optics, 3D preview, project schema, updater service/installer, WebView2 runtime, stable Lenticulizer.exe filename, and Blender add-on v1.18.43 are not changed.

## Release gate

- Tag: v3.0.0-alpha.33 (new tag, never overwrite Alpha 32).
- GitHub Actions: .github/workflows/ci.yml builds, validates and publishes on an exact release commit message only when validation succeeds.
- Release assets: Lenticulizer_Windows_Portable.zip, update-manifest.json, SHA256SUMS.txt, Lenticulizer_3D_Blender_Addon_v1.18.43.zip, and Lenticulizer_v3.0.0-alpha.33_Source.zip.
- Verify the tag/commit, completed hosted CI, asset names/sizes, manifest version/package SHA-256, and checksum file before announcing successful publication.

## Native Windows test

1. Download the published Alpha 32 ZIP and extract it to a normal writable folder. Launch Lenticulizer.exe and record the shortcut, project, preferences and window position.
2. After Alpha 33 is published, confirm an automatic update check shows it, or select Help > Updates > Check for updates.
3. Select Download. Verify that the status reflects download progress and completion; no unapproved install should occur.
4. Select Install and restart. Confirm that the old process exits, the new one launches and reports a healthy UI.
5. Confirm the original executable shortcut still works, the version is 3.0.0-alpha.33, the Alpha 33 test note is visible and settings/projects remain intact.
6. Verify that one previous executable remains available for rollback and leftover application-owned update staging/download files have been removed.
7. In a separate controlled test environment, validate offline/rate-limit/network errors, partial or tampered packages, blocked active operations, health timeout and rollback.
8. Confirm Blender 5.0 project rendering separately where relevant.

Passing CI is not proof of a successful real Alpha 32-to-33 download/install/relaunch/rollback. Do not describe the updater as production-verified until those live checks pass.
