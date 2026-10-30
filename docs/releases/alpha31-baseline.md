# Alpha 31 baseline

This file records the last confirmed Lenticulizer functional baseline before the GitHub repository became the intended long-term development home.

## Versions

- Desktop app: **v3.0.0-alpha.31**
- Blender add-on: **v1.18.43**

## Primary Alpha 31 addition

Alpha 31 added **Labeled Test Print** export support in the desktop app and Blender add-on.

The test export produces a paired set containing:

- `Test_Interlaced.png` — original artwork with a settings footer added below it;
- `Test_Heightmap.png` — matching enlarged height/depth canvas with a zero-height footer;
- `Test_Settings.json` — settings snapshot, source checksums, and output dimensions;
- `PRINT_README.txt` — printing instructions and settings summary.

Normal production exports remain clean and separate.

The footer records the important test settings, including output mode, orientation, view count, LPI, phase, printer/raster DPI, active print size, optical settings where relevant, backing state, version, timestamp, and optional test name.

## Preservation rules

The recorded Alpha 31 validation states that:

- the active artwork is not cropped, rescaled, or shifted;
- heightmap sample values and bit depth are retained;
- image/heightmap alignment is preserved;
- the test footer does not alter the active project assets;
- ordinary production exports are unchanged;
- test labeling is not globally enabled.

## Blender baseline

The last user-supplied Blender scene baseline was `Lenticulizer_3D_Project(6).blend`.

Recorded SHA-256:

`54154ce98dae6b232ef486886ecdaf61f5370510abe9c247ad712d002ca99897`

The add-on baseline includes the three-tab sidebar workflow:

- Project & Images
- Optics & Calibration
- Output

Settings mode remains shared and available across the workflow.

## Recorded validation

The Alpha 31 validation record reported:

- real-PNG raster/export checks;
- independent decoder verification;
- cross-language label-plan checks;
- browser-interface/download checks using test doubles;
- add-on export/operator checks using Blender API doubles;
- established Blender heightmap/callback/project/raster/export regressions;
- package-integrity assertions.

## Important limitation

Alpha 31 was assembled from the already-compiled Alpha 30 self-contained application plus resource/interface updates. It was **not** a fresh C# compiler output.

The historical validation explicitly did **not** execute:

- Windows EXE launch;
- real WebView2 save/download interaction;
- live Blender installation or viewport operation;
- physical printer testing.

Future repository-built releases must rerun the relevant native experience checks and must not claim those historical checks were performed.
