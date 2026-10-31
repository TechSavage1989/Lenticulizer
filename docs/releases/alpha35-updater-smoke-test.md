# Alpha 35 updater smoke test

## Release scope

v3.0.0-alpha.35 is a small Windows x64 version and Help/About change to test Alpha 34's corrected in-app updater. Processing, optics, 3D preview, project schema, WebView2, updater/installer, stable Lenticulizer.exe, and Blender add-on v1.18.43 are unchanged.

## Publication

- New immutable tag: v3.0.0-alpha.35.
- Windows source, native parity/integration, negative-control, WebView2/runtime and UI checks must pass.
- Verify the release tag matches the CI commit and all five assets exist: Lenticulizer_Windows_Portable.zip, update-manifest.json, SHA256SUMS.txt, Lenticulizer_v3.0.0-alpha.35_Source.zip, and Lenticulizer_3D_Blender_Addon_v1.18.43.zip.
- Verify uploaded hashes and sizes against GitHub release assets and the CI log. Do not overwrite Alpha 34.

## Native user test

1. Start the installed Alpha 34 using its existing shortcut. Save a representative project and note the current preferences and window position.
2. After Alpha 35 is published, confirm update detection automatically or via Help > Updates > Check for updates.
3. Click Download and observe download completion followed by Verifying update and Update downloaded and verified.
4. Click Install and restart. Confirm the old process exits and Alpha 35 relaunches with a healthy UI.
5. Confirm both title bar and Help/About report 3.0.0-alpha.35; projects, window placement, user settings and original shortcut still work.
6. Verify only one rollback executable remains, stale downloads/staging are cleaned, and controlled failure cases (offline, interrupted/tampered package, health timeout) are handled and rolled back safely.

GitHub-hosted CI is not a substitute for real in-place updater, persistence, cleanup and rollback testing.
