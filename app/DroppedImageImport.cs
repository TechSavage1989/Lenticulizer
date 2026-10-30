using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Lenticulizer.Core;

namespace Lenticulizer.Desktop
{
    public sealed class ImageDropPlan
    {
        public string[] Sources = Array.Empty<string>();
        public string HeightmapPath = "";
        public Dictionary<string, object> HeightmapInfo;
    }

    public sealed class ImageDropUpdate
    {
        public Dictionary<string, object> Patch = new Dictionary<string, object>();
        public string Priority = "reference", Message = "";
        public int SourcesAdded, SourcesSkipped;
        public bool HeightmapImported, HasChanges;
    }

    // Recognition and project changes are independent of the Windows file dialog.
    // All paths supplied by the UI originate in WebView2's native dropped objects.
    public static class DroppedImageImport
    {
        static bool MapExtension(string path)
        {
            string extension = Path.GetExtension(path);
            return new[] { ".png", ".tif", ".tiff" }.Contains(extension, StringComparer.OrdinalIgnoreCase);
        }

        static bool Recognized(string path, Dictionary<string, object> info)
        {
            if (!object.Equals(info.GetValueOrDefault("grayscale"), true)) return false;
            // Explicit height-scale metadata identifies our exported maps even
            // when a flat or unusual profile needs manual pitch calibration.
            if (ProjectJson.Number(info, "scale_mm", 0) > 0) return true;
            if (!object.Equals(info.GetValueOrDefault("ok"), true)) return false;
            var data = HeightmapEngine.Load(path);
            double[] profile = ProjectJson.Text(info, "orientation", "Vertical") == "Horizontal" ? data.Y : data.X;
            double pitch = ProjectJson.Number(info, "pitch_px", 0);
            int levelsNeeded = (int)Math.Max(5, Math.Min(16, Math.Ceiling(pitch / 2)));
            var levels = new HashSet<int>();
            int previous = -1, run = 0, longest = 0;
            foreach (double sample in profile)
            {
                int value = (int)Math.Round(sample * 65535);
                levels.Add(value);
                run = value == previous ? run + 1 : 1;
                longest = Math.Max(longest, run);
                previous = value;
            }
            // Ordinary grayscale interlaces have broad constant-color stripes.
            // Require graduated profiles for unlabelled automatic imports.
            return levels.Count >= levelsNeeded && longest <= Math.Max(2, Math.Ceiling(pitch * .22));
        }

        static bool PngWithinMapLimits(string path)
        {
            if (!Path.GetExtension(path).Equals(".png", StringComparison.OrdinalIgnoreCase)) return true;
            using var stream = System.IO.File.OpenRead(path);
            var header = new byte[24];
            if (stream.Read(header, 0, header.Length) != header.Length || !header.Take(8).SequenceEqual(new byte[] {137,80,78,71,13,10,26,10})) return true;
            long width = PngCodec.Read32(header,16), height = PngCodec.Read32(header,20);
            return width >= 2 && height >= 2 && width <= 100000 && height <= 100000 && width * height <= 100000000;
        }

        public static ImageDropPlan Analyze(IEnumerable<string> dropped, string target)
        {
            if (target != "auto" && target != "heightmap") throw new ArgumentException("Unknown image drop target.");
            var paths = (dropped ?? Array.Empty<string>()).Where(ProjectJson.SupportedImage)
                .Select(Path.GetFullPath).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
            if (paths.Length == 0) throw new ArgumentException("Drop PNG, JPG, BMP or TIFF image files.");
            if (paths.Length > 9) throw new ArgumentException("Drop up to eight source images and one heightmap at a time.");
            if (target == "heightmap" && (paths.Length != 1 || !MapExtension(paths[0])))
                throw new ArgumentException("Drop one grayscale PNG or TIFF onto Reference heightmap. Use the source list for artwork.");
            var plan = new ImageDropPlan();
            var sources = new List<string>();
            foreach (string path in paths)
            {
                if (!File.Exists(path)) throw new FileNotFoundException("A dropped image is no longer available.", path);
                bool map = false;
                Dictionary<string, object> info = null;
                // A valid source image may be outside the lens analyzer's size
                // limits (for example a one-pixel solid-color source).
                if (target == "auto" && !PngWithinMapLimits(path)) { sources.Add(path); continue; }
                if (MapExtension(path))
                {
                    try { info = HeightmapEngine.Analyze(path); }
                    catch (Exception error) when (error is IOException || error is InvalidDataException || error is ArgumentException || error is NotSupportedException)
                    { throw new InvalidDataException("Could not inspect " + Path.GetFileName(path) + ": " + error.Message, error); }
                    if (target == "heightmap" && !object.Equals(info.GetValueOrDefault("grayscale"), true))
                        throw new ArgumentException("This image contains color. Drop a grayscale heightmap here, or add the image to the source list.");
                    map = target == "heightmap" || Recognized(path, info);
                }
                if (map)
                {
                    if (plan.HeightmapPath != "") throw new ArgumentException("More than one heightmap was detected. Drop one heightmap at a time.");
                    plan.HeightmapPath = path; plan.HeightmapInfo = info;
                }
                else sources.Add(path);
            }
            plan.Sources = sources.ToArray();
            return plan;
        }

        public static Dictionary<string, object> HeightmapPatch(Dictionary<string, object> current, string path, Dictionary<string, object> info, bool importing)
        {
            var settings = ProjectJson.Object(current, "settings");
            var changes = new Dictionary<string, object> { { "reference_heightmap_detection", "Automatic" } };
            if (importing)
            {
                double width = ProjectJson.Number(info, "width_mm", 0), height = ProjectJson.Number(info, "height_mm", 0), scale = ProjectJson.Number(info, "scale_mm", 0);
                changes["reference_heightmap_width_mm"] = width > 0 ? width : ProjectJson.Number(settings, "width_mm", 100);
                changes["reference_heightmap_height_mm"] = height > 0 ? height : ProjectJson.Number(settings, "height_mm", 100);
                changes["reference_heightmap_thickness_mm"] = scale > 0 ? scale : ProjectJson.Number(settings, "thickness_mm", 1.86);
                changes["reference_heightmap_show"] = true;
                changes["reference_heightmap_pitch_px"] = 0;
                changes["reference_heightmap_phase_pitch"] = 0;
            }
            if (object.Equals(info.GetValueOrDefault("ok"), true))
            {
                changes["reference_heightmap_orientation"] = info["orientation"];
                changes["reference_heightmap_pitch_px"] = info["pitch_px"];
                changes["reference_heightmap_phase_pitch"] = info["phase_pitch"];
            }
            return new Dictionary<string, object> {
                { "settings", changes }, { "assets", new Dictionary<string, object> { { "reference_heightmap", path } } }, { "reference_heightmap_info", info }
            };
        }

        public static ImageDropUpdate BuildUpdate(ImageDropPlan plan, Dictionary<string, object> current)
        {
            var result = new ImageDropUpdate { HeightmapImported = plan.HeightmapPath != "" };
            var settings = ProjectJson.Object(current, "settings");
            bool buildingMap = ProjectJson.Text(settings, "workflow", "") == "Build from heightmap";
            if (result.HeightmapImported)
            {
                result.Patch = HeightmapPatch(current, plan.HeightmapPath, plan.HeightmapInfo, true);
                result.HasChanges = true;
                if (buildingMap) result.Priority = "rebuild-pair";
            }
            var existing = ProjectJson.Object(current, "assets").GetValueOrDefault("source_frames") as object[] ?? Array.Empty<object>();
            var sources = existing.OfType<string>().ToList();
            foreach (string path in plan.Sources)
            {
                if (sources.Contains(path, StringComparer.OrdinalIgnoreCase)) continue;
                if (sources.Count >= 8) { result.SourcesSkipped++; continue; }
                sources.Add(path); result.SourcesAdded++;
            }
            if (result.SourcesAdded > 0)
            {
                var assets = ProjectJson.Object(result.Patch, "assets"); assets["source_frames"] = sources.ToArray(); result.Patch["assets"] = assets;
                var changes = ProjectJson.Object(result.Patch, "settings");
                changes["views"] = sources.Count;
                if (!buildingMap) changes["workflow"] = "Build from source frames";
                result.Patch["settings"] = changes;
                result.HasChanges = true; result.Priority = "rebuild-pair";
            }
            var messages = new List<string>();
            if (result.HeightmapImported)
                messages.Add(object.Equals(plan.HeightmapInfo.GetValueOrDefault("ok"), true)
                    ? (buildingMap ? "Heightmap imported. Rebuilding the matching output pair." : "Heightmap imported. Review its scale, then choose Build from heightmap.")
                    : "Heightmap imported. Automatic spacing needs review; choose Manual and set direction, pixels per lens and registration.");
            if (result.SourcesAdded > 0) messages.Add(result.SourcesAdded + " source image(s) added in drop order.");
            if (result.SourcesSkipped > 0) messages.Add(result.SourcesSkipped + " source image(s) skipped because the eight-view limit is reached.");
            if (!result.HeightmapImported && result.SourcesAdded == 0 && result.SourcesSkipped == 0) messages.Add("These source images are already in the list.");
            result.Message = string.Join(" ", messages);
            return result;
        }
    }
}
