using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;

namespace Lenticulizer.Core
{
    public sealed class BuildRequest
    {
        internal readonly ProjectState State;
        internal readonly long Generation;
        internal readonly string ExpectedDocument;
        internal readonly string InterlaceFingerprint;
        internal readonly string HeightmapFingerprint;
        internal readonly bool Interlace, Heightmap;
        internal BuildRequest(ProjectState state, long generation, string expected, bool interlace, bool heightmap)
        {
            State = state.Snapshot(); Generation = generation; ExpectedDocument = expected;
            Interlace = interlace; Heightmap = heightmap || interlace;
            InterlaceFingerprint = ProjectBuild.InterlaceKey(State);
            HeightmapFingerprint = ProjectBuild.HeightmapKey(State);
        }
    }
    public sealed class BuildResult : IDisposable
    {
        internal ProjectState State;
        internal string DirectoryPath;
        internal bool Published;
        internal PreparedCommand Command;
        internal string CommandDirectory;
        internal string Status = "ready";
        public void Dispose()
        {
            if (!string.IsNullOrEmpty(CommandDirectory))
                try { Directory.Delete(CommandDirectory, true); } catch { }
            if (!Published && !string.IsNullOrEmpty(DirectoryPath))
                try { Directory.Delete(DirectoryPath, true); } catch { }
        }
    }
    internal interface IProjectBuilder : IDisposable
    {
        BuildResult Run(BuildRequest request, Func<bool> cancelled);
    }
    public sealed class ProjectBuild : IProjectBuilder
    {
        readonly RasterEngine rasters = new RasterEngine();
        readonly string workingRoot;
        readonly ProjectCommands commands;
        public ProjectBuild(string workingRoot) : this(workingRoot, null) { }
        public ProjectBuild(string workingRoot, ProjectCommands commands) { this.workingRoot = workingRoot; this.commands = commands; }
        internal static string Hash(string value)
        {
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value))).Replace("-", "").ToLowerInvariant();
        }
        internal static string Stamp(string path)
        {
            if (string.IsNullOrEmpty(path)) return "";
            var f = new FileInfo(path);
            return path + "|" + (f.Exists ? f.Length + "|" + f.LastWriteTimeUtc.Ticks : "missing");
        }
        internal static string InterlaceKey(ProjectState p)
        {
            var o = p.Optics;
            var sb = new StringBuilder();
            sb.Append(p.Workflow).Append('|').Append(o.OutputModeSelection).Append('|').Append(o.WidthText).Append('|').Append(o.HeightText)
                .Append('|').Append(o.SizeUnitSelection).Append('|').Append(o.LpiText).Append('|').Append(o.ViewCountText)
                .Append('|').Append(o.PixelsPerLenticuleText).Append('|').Append(o.OrientationSelection);
            if (p.BuildsFromHeightmap) sb.Append('|').Append(Stamp(p.ReferencePath)).Append('|').Append(HeightmapWorkflow.Key(p));
            foreach (string frame in p.SourceFrames) sb.Append('|').Append(Stamp(frame));
            return Hash(sb.ToString());
        }
        internal static string HeightmapKey(ProjectState p)
        {
            if (p.BuildsFromHeightmap) return InterlaceKey(p);
            var s = ProjectJson.Object(ProjectJson.Parse(ProjectSerializer.Solve(p)), "settings");
            foreach (string key in new[] { "backing_mm", "workflow", "lpi_helper_mode", "lpi_helper_preset", "build_detail_mode", "printer_dpi" }) s.Remove(key);
            return Hash(ProjectJson.Canonical(ProjectJson.Stringify(s)) + "|" + (p.BuildsFromFrames ? InterlaceKey(p) : Stamp(p.InterlacedPath)));
        }
        static void Check(Func<bool> cancelled) { if (cancelled()) throw new OperationCanceledException("A newer project revision superseded this build."); }

        BuildResult RunProduction(BuildRequest request, Func<bool> cancelled)
        {
            var result = new BuildResult { State = request.State.Snapshot() };
            var p = result.State;
            try
            {
                Check(cancelled);
                HeightmapWorkflow.Refresh(p);
                if (p.BuildsFromHeightmap) return HeightmapWorkflow.Build(p, result, request, workingRoot, rasters, cancelled);
                if (!request.Interlace && !request.Heightmap) return result;
                if (p.BuildsFromFrames && p.SourceFrames.Length < 2)
                {
                    result.Status = "waiting-for-sources";
                    return result;
                }
                result.DirectoryPath = Path.Combine(workingRoot, Hash(p.ProjectPath).Substring(0, 20), "revisions", Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(result.DirectoryPath);
                var optics = new OpticalEngine(p.Optics);
                bool vertical = p.Optics.OrientationSelection == "Vertical";
                bool relief = optics.IsLensFreeMode();
                double wi, hi; optics.GetSize(out wi, out hi);
                double lpi = optics.Positive(p.Optics.LpiText, "LPI");
                if (request.Interlace)
                {
                    optics.ValidateLensFreeViewConfigurationForBuild();
                    int w, h;
                    RasterEngine.GetBuildTargetCanvasSize(wi, hi, lpi, vertical, out w, out h, optics.Positive(p.Optics.PixelsPerLenticuleText, "Pixels per lenticule"));
                    double dpi = (vertical ? w : h) / (vertical ? wi : hi);
                    double pitch = dpi / lpi;
                    if (pitch < 2) throw new InvalidOperationException("Current LPI produces fewer than 2 pixels per cell.");
                    string output = Path.Combine(result.DirectoryPath, relief ? "color_map_autogenerated.png" : "interlaced_autogenerated.png");
                    using (var bitmap = rasters.BuildInterlacedBitmap(w, h, pitch, vertical, p.SourceFrames, relief))
                    {
                        double dx = w / wi, dy = h / hi;
                        bitmap.SetResolution((float)dx, (float)dy);
                        using (var stream = new FileStream(output, FileMode.CreateNew, FileAccess.Write, FileShare.None)) bitmap.Save(stream, ImageFormat.Png);
                        PngCodec.SetPngPhysicalResolution(output, PngCodec.DpiToPixelsPerMeter(dx), PngCodec.DpiToPixelsPerMeter(dy));
                        PngCodec.SetPngLenticularMetadata(output, lpi, p.SourceFrames.Length, wi, hi, vertical, p.Optics.OutputModeSelection, relief ? optics.ReliefPrismHeightMm() : 0.0);
                    }
                    p.InterlacedPath = output;
                    // Preserve the established post-interlace registration values,
                    // now as explicit state transitions rather than image-load events.
                    p.Optics.WidthText = (wi * 25.4).ToString("0.###", CultureInfo.InvariantCulture);
                    p.Optics.HeightText = (hi * 25.4).ToString("0.###", CultureInfo.InvariantCulture);
                    p.Optics.LpiText = lpi.ToString("0.######", CultureInfo.InvariantCulture);
                    p.Optics.ViewCountText = p.SourceFrames.Length.ToString(CultureInfo.InvariantCulture);
                    SettingsRules.Normalize(p);
                    optics = new OpticalEngine(p.Optics);
                    optics.GetSize(out wi, out hi);
                    lpi = optics.Positive(p.Optics.LpiText, "LPI");
                    using (var analysisSource = new Bitmap(p.InterlacedPath)) ImageAnalysis.Analyze(p, analysisSource);
                    Check(cancelled);
                }
                if (string.IsNullOrWhiteSpace(p.InterlacedPath) || !File.Exists(p.InterlacedPath))
                {
                    result.Status = "waiting-for-interlace";
                    return result;
                }
                double peak = optics.HeightUm(lpi) / 1000.0;
                if (peak > optics.MaximumTopHeightMm() + 0.0001) throw new InvalidOperationException("Selected height exceeds printer maximum.");
                optics.ValidateTheoreticalProfileGeometry(lpi, peak);
                double baseMm = optics.BaseHeightForSelectionMm(lpi);
                if (baseMm > 0 && baseMm < optics.MinimumValleyHeightMm()) throw new InvalidOperationException("Non-zero base is below printer minimum.");
                if (baseMm > peak) throw new InvalidOperationException("Valley is above peak.");
                string map = Path.Combine(result.DirectoryPath, relief ? "depthmap16_autogenerated.png" : "heightmap16_autogenerated.png");
                using (var source = new Bitmap(p.InterlacedPath))
                    ProductionEngine.WriteHeightmapForPath(map, wi, hi, lpi, vertical, peak, baseMm, source.Width, source.Height, p.InterlacedPath, p.PhasePitch, p.Optics);
                string verification;
                if (!PngCodec.VerifyImagePair(p.InterlacedPath, map, out verification)) throw new InvalidOperationException("Image pair verification failed: " + verification);
                p.HeightmapPath = map;
                Check(cancelled);
                return result;
            }
            catch { result.Dispose(); throw; }
        }
        public BuildResult Run(BuildRequest request, Func<bool> cancelled)
        {
            BuildResult result = RunProduction(request, cancelled);
            if (commands == null || !ProjectCommands.IsCommand(request.State)) return result;
            try
            {
                var p = result.State;
                if (p.Priority == "analyze" && !p.BuildsFromHeightmap)
                {
                    var analyzed = p.Snapshot();
                    using (var bitmap = new Bitmap(p.InterlacedPath)) ImageAnalysis.Analyze(analyzed, bitmap);
                    if (analyzed.Optics.LpiText != p.Optics.LpiText)
                    {
                        SettingsRules.Normalize(analyzed);
                        var updated = RunProduction(new BuildRequest(analyzed, request.Generation, request.ExpectedDocument, analyzed.BuildsFromFrames, true), cancelled);
                        result.Dispose(); result = updated; p = result.State;
                    }
                    else { result.State = analyzed; p = analyzed; }
                }
                Check(cancelled);
                result.CommandDirectory = Path.Combine(workingRoot, "commands", Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(result.CommandDirectory);
                if ((p.Priority=="blender-export"||p.Priority=="calibration") && result.Status!="ready") throw new InvalidOperationException("Finish generating a valid image and heightmap pair before exporting this project.");
                result.Command = commands.Prepare(p, result.CommandDirectory, cancelled);
                p.CommandResultJson = ProjectJson.Stringify(result.Command.Result());
                p.Priority = "";
                return result;
            }
            catch (OperationCanceledException) { result.Dispose(); throw; }
            catch (Exception error)
            {
                result.State.CommandResultJson = ProjectSerializer.CommandFailure(request.State, error.Message);
                result.State.Priority = "";
                return result;
            }
        }
        public void Dispose() { rasters.Dispose(); }
    }
}
