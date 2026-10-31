# Alpha 34 updater file-sharing fix

## Root cause

Alpha 32 and Alpha 33 download an update into an exclusive FileStream, then attempt SHA-256 verification with HashFile(temporary) before the exclusive writer is closed. Windows denies the second open. The UI remains stuck showing the last streamed progress value, which can be slightly below the full ZIP size even when the download completed.

## Correction

- Dispose the input and exclusive output streams before size/hash verification and final ZIP move.
- Report "Verifying update" after writing the complete package.
- Show download errors and restore the Retry download button after a failed transfer/hash.
- Apply a 60-second per-read no-data timeout, without removing size/SHA-256/manifest or installer security checks.
- Keep Lenticulizer.exe, per-user data, image-processing features, and Blender add-on v1.18.43 unchanged.

## Native regression

IntegratedAppTests invokes UpdateService.VerifyAndFinalizePackage on Windows. The negative control confirms an open exclusive writer prevents hashing. The positive control confirms hashing/moving succeeds after closing it. Tampered payloads and mismatched expected sizes must fail without overwriting the verified package. Python source contracts assert the verifying/error/timeout/retry states.

## User migration

The old Alpha 32/33 binaries cannot receive this correction through their own broken updater. Download the Alpha 34 Windows portable ZIP from GitHub using a browser and replace the original Lenticulizer.exe while the app is closed, preserving its folder and shortcut. Back up the old executable first. User projects and settings are stored separately.

Native Alpha 34-to-next-version update, relaunch, cleanup and rollback must still be tested before declaring the automatic updater production-verified.
