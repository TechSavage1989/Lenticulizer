# Alpha 31 source reconstruction

The Alpha 31 functional baseline has been reconstructed into a complete build-ready source tree outside the public repository. Application source remains unpublished until source-publication scope is explicit.

## Recovered baseline

- Desktop target: `v3.0.0-alpha.31`
- Blender add-on: `v1.18.43`
- Blender baseline: `Lenticulizer_3D_Project(6).blend`
- Baseline SHA-256: `54154ce98dae6b232ef486886ecdaf61f5370510abe9c247ad712d002ca99897`
- Add-on ZIP SHA-256: `975854f306081f4f374acd02b361bc3130b8c349bdfa685b343246bfe775fdd0`

The recovery reconciles the last maintainable source with the recorded Alpha 28–31 deltas rather than treating older Alpha 27 source as current.

## Reconstructed scope

- optional backing/support state with remembered thickness;
- compact Images/Optics desktop presentation and persistent local layout preferences;
- current Project(6) Blender baseline;
- Blender add-on 1.18.43;
- Alpha 31 labeled-test output helper and desktop export wiring;
- current Fixed WebView2 Runtime payload with the current baseline/add-on embedded.

## Validation performed

Passed in the recovery environment:

- JavaScript syntax for bridge, renderer and labeled-test helper;
- WebView2 bridge regression checks;
- drag/drop UI-handler regression checks;
- desktop DOM/bridge/add-on-package contract checks;
- 30 heightmap raster/direction/phase/filter/bit-depth fixtures;
- 33 Blender add-on callback/project/geometry/export checks with API doubles;
- desktop JavaScript vs Blender Python labeled-test comparison using real PNGs, including unchanged active RGB/16-bit height pixels, zero heightmap footer, matching label plans and valid ZIP CRC;
- reconstructed source identity/runtime/add-on/baseline consistency checks;
- all 555 browser/loader/notices records match the prior trusted runtime payload.

Not performed in the recovery environment:

- fresh .NET compiler build;
- Windows EXE launch / real WebView2 interaction;
- live Blender installation/viewport/rendering;
- physical print testing.

The environment does not contain .NET SDK 10.0.400 and blocks direct SDK package downloads. Microsoft release metadata confirms that SDK 10.0.400 pairs with runtime 10.0.11, matching the recovered source configuration.

## Next phase

A fresh Windows compiler build of the reconstructed tree is required before the source is declared authoritative. After that, development proceeds to the stable `Lenticulizer.exe` portable launch name and production GitHub updater requirements.
