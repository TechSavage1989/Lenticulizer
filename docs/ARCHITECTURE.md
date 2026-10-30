Lenticulizer 3D Alpha 23 architecture

The processing core, WinForms host and application services are compiled into a
single Microsoft .NET 10 assembly. The Windows x64 publisher embeds it and the
.NET/Windows Desktop runtime in one EXE. The complete fixed WebView2 distribution,
loader, Blender baseline, add-on and notices remain embedded and hash verified.
There is no external processing assembly or processing subprocess.

Reference heightmaps use the shared assets.reference_heightmap path and flat
settings.reference_heightmap_* fields. reference_heightmap_info carries detected
pitch, phase, direction, confidence, raw range and bounded preview axis samples.
The app and add-on share top-down raster coordinates. Blender reverses the
horizontal raw profile once when constructing local bottom-to-top mesh vertices.
A heightmap supplies geometry; the ordered source list supplies the view count.

The C# and Python readers avoid display gamma for physical height samples.
PNG filters and 8/16-bit channels are decoded exactly. Windows WIC and Blender
Non-Color image buffers cover TIFF and uncommon PNG encodings. Output PNG copies
retain compressed pixel data. TIFF copies append a replacement metadata directory
while retaining pixel strip/tile offsets and bytes. Original imports are read-only.

Detection uses autocorrelation, crest localization and cycle regression. A native
resolution window prevents short-pitch aliasing in large maps; a coarse fallback
covers longer periods. Direction, periodicity and grayscale checks gate automatic
builds. Explicit Manual settings survive refresh and round-trip synchronization.

Build from heightmap bypasses procedural optical normalization. Width, height,
LPI, thickness and base come from the imported map and entered physical scale.
The raster engine uses exact pitch and registration; default procedural calls
retain the established phase convention and source ordering. Source count must
fit at least one pixel per view inside each lens. Each desktop revision stages
both outputs and publishes only the current completed revision. Reference display
changes are excluded from generation fingerprints.

The desktop reference viewer extrudes the selected center scanline, as the Blender
reference viewer does. Opaque, tinted and clear desktop styles are inspection
shading, not a full resin ray tracer. The selected 3D camera state remains outside
project regeneration, with yaw and pitch initially zero for Front view.

Imported interlace source cropping uses the entered physical width/height ratio,
so unequal X/Y map DPI does not distort the artwork when printed. Pixel counts
still match the original map. The procedural source crop path remains unchanged.
