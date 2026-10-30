Alpha 23 verification gates

Build_SelfContained.bat compiles with the pinned Microsoft .NET 10 SDK, runs the
actual assembly runtime and Windows integration harnesses, publishes a self-
contained EXE and runs --verify-core, --verify-runtime and --verify-ui.

RuntimeTests executes platform-independent members of the actual Windows app
assembly under .NET 10. It checks legacy optical/PNG16 compatibility, serialization,
cache behavior, embedded runtime hashes, heightmap fixtures, stripe mapping and
shared geometry settings. It includes TIFF directory editing without Windows APIs.
IntegratedAppTests runs on Windows and additionally checks GDI+ complete builds,
WIC TIFF heightmaps, geometry-preserving imports, shared edits and exports.
WindowsUiChecks.js runs inside the actual EXE to check Front default, reference
controls, textures, native image delivery and view preservation on regeneration.

HeightmapFixtures.py regenerates PNG/TIFF fixtures and validates Python readers,
metadata and immutable source behavior. BlenderHeightmapChecks.py loads the real
add-on with Blender API doubles and exercises callbacks, project round-trips,
geometry samples and the actual NumPy/PNG raster writer. It does not execute Blender.
DesktopHeightmapContractChecks.py audits DOM references, native commands, extension
identity and ZIP/source consistency. BridgeTests.js checks message transport.

See ALPHA_23_VALIDATION.txt for executed results. Unexecuted Windows/Blender checks
are explicitly identified. A compiled test is not a claimed passing execution.
