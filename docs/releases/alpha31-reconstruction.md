# Alpha 31 source reconstruction

This recovery reconciles the last maintainable source with the recorded Alpha 28–31 changes instead of treating older Alpha 27 source as current.

Key recovered elements:

- current Project(6) Blender baseline;
- Blender add-on 1.18.43;
- optional backing/support state;
- compact Images/Optics desktop layout;
- labeled-test output helper/wiring;
- same-origin generated-image reads needed for test export;
- browser-generated ZIP download handling;
- current embedded fixed-runtime manifest.

Available non-Windows validation passes are recorded in `DEVELOPMENT_HANDOFF.md`.

A compiler-built Windows executable from this reconstructed source remains required before it becomes the authoritative code baseline.
