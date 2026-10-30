Lenticulizer 3D Alpha 31 - Help and About

RUN
Extract Lenticulizer_3D_v3.0.0-alpha.32_SelfContained.exe and open it on 64-bit
Windows 10 or 11. No build, launcher, installed .NET, Node.js or WebView2 is
required. First launch prepares its bundled runtime in your Windows user cache.
The processing core runs inside the application. WebView2 uses browser helpers.
The complete fixed browser runtime is retained; this is still a large download.


NEW IN ALPHA 27
A new Help page in the desktop app provides Quick Start, image ordering, settings
modes, LPI/DPI guidance, heightmap workflow, 3D preview, Blender integration,
calibration, export, troubleshooting, About, license and attribution information.
Full bundled runtime licenses/notices remain accessible from Help and the footer.

Blender add-on v1.18.43 adds a collapsible Help & About section with practical
Quick Start, image ordering, optics/viewer guidance, app sync, troubleshooting,
version, license and attribution information. Normal working panels are unchanged.

NEW IN ALPHA 26
Open Project in Blender and Reset Project Scene request a console-free Blender
launch. The Blender application opens with its normal project window.
Use the existing Blender add-on v1.18.43.

RETAINED FROM ALPHA 25
Drop a heightmap anywhere in the app to recognize a repeating grayscale lens
profile or a map with Lenticulizer height-scale metadata. It opens in Reference
heightmap instead of being added as artwork. A mixed drop can include one
heightmap and up to eight source images. Source order is preserved.
Drop one grayscale PNG/TIFF directly onto Reference heightmap when the profile
is ambiguous. Use Manual for direction, pixels per lens and registration when
automatic analysis cannot determine them. For grayscale artwork that resembles
a lens pattern, use Add source images to import it explicitly as artwork.
Importing previews the map; choose Build from heightmap to use its geometry.
The Reference heightmap section includes a collapsible options explanation.

RETAINED FROM ALPHA 24
Import heightmap now appears once, in Images / Reference heightmap.
The Project shortcut and Images page header duplicate have been removed.
Use the existing Blender add-on v1.18.43.

HEIGHTMAP WORKFLOW (INTRODUCED IN ALPHA 23)
The desktop 3D preview starts in Front view and preserves manual rotation during
regeneration. Reference Heightmap on the Images page imports a grayscale PNG or
TIFF, previews its actual height profile, and syncs its dimensions, white-level
height, orientation, detection, registration, display style and visibility with
Blender add-on v1.18.43. Use that add-on with this release; it is also embedded
and accessible from the Blender page. The accepted Blender baseline is retained.

WORKFLOW
1. On Images, use Import heightmap in the Reference heightmap section.
2. Review Width, Height and White-Level Height. Metadata supplies values when
   present; otherwise current project dimensions and thickness are starting values.
   Set the real dimensions and height before building. Black is zero height;
   white is the entered height. A grayscale map alone cannot reveal its physical
   size, absolute height, source artwork or original number of views.
3. Use Reference 3D with Opaque, Tinted or Clear for inspection. Desktop styles
   provide approximate inspection shading; Blender supplies its resin materials.
4. Choose Build from Heightmap, then add and order at least two source images.
   Their count supplies the number of views. LPI comes from detected pixel pitch
   and the physical dimension across the lenses.
5. Generate / Regenerate Both produces a matched interlace and heightmap copy at
   the original pixel dimensions. Height samples and bit depth are preserved.
   PNG/TIFF output metadata records the selected physical dimensions and scale.
   The original imported file is never overwritten by this workflow.
6. If detection is ambiguous, choose Manual and set direction, pixels per lens
   and registration. The normal Phase slider changes image registration without
   shifting the original height samples. Return to generated lens geometry to
   resume the existing source-image workflow and procedural calibration.

Automatic detection targets repeating one-dimensional lenticule/prism profiles.
Flat, colored or ambiguous two-dimensional maps are not silently accepted as an
automatic lens calibration. The reference 3D surface uses the selected center
scanline extruded along the lens direction, matching the add-on reference viewer.
Standard TIFF and PNG are supported; convert BigTIFF to standard TIFF or PNG.
The map must contain at least one pixel per view within each lens.

All existing Automatic, Semi-Automatic and Manual settings modes remain available.
The three authored Blender Image Editors and accepted lens-view framing remain.
Blender 5.0 or later is required only for Blender features.

VERIFICATION
See docs/ALPHA_26_VALIDATION.txt for the launch change and build checks.
Prior heightmap/drop validation remains in docs/ALPHA_25_VALIDATION.txt.
The prior processing validation remains in docs/ALPHA_23_VALIDATION.txt.
Windows launch, WebView2 rendering/file dialogs and live Blender viewport checks
were not executable in this Linux build environment. The Windows integration
suite and built-in --verify-ui check are supplied for those checks.

Windows UI diagnostic from Command Prompt in the EXE folder:
start "" /wait "Lenticulizer_3D_v3.0.0-alpha.32_SelfContained.exe" --verify-ui "%TEMP%\Lenticulizer_UI_Check.json"

SOURCE BUILD
Use Microsoft .NET SDK 10.0.400 and run Build_SelfContained.bat on Windows.
This build-ready source package includes the verified Alpha 26 Fixed Version
WebView2 runtime.zip, so Restore_Build_Assets.bat is not required for this copy.
Fixtures, source, validation harnesses and Blender add-on v1.18.43 are included.
Python/NumPy are needed only to regenerate development fixtures, not for the
normal Windows build.

LOCATIONS
Runtime: %LOCALAPPDATA%\Lenticulizer\Runtime
Browser profile: %LOCALAPPDATA%\Lenticulizer\WebView2
Sessions: %LOCALAPPDATA%\Lenticulizer\Sessions
Logs: %LOCALAPPDATA%\Lenticulizer\Logs
Native .NET extraction uses its standard %TEMP%\.net cache. The app creates its
own project and output files; adjacent support files are not needed to launch.
