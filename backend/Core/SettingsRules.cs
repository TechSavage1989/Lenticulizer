using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;

namespace Lenticulizer.Core
{
    public static class SettingsRules
    {
        static readonly CultureInfo Inv = CultureInfo.InvariantCulture;
        static readonly string[] LensNames = { "Auto Recommended", "Auto Mathematically Optimal", "Reference Calibrated", "Mathematically Optimal Aspheric", "Aspheric", "Rounded / Circular", "Multi-facet / Prismatic", "Linear / Triangular", "Cosine" };
        static readonly string[] PrintNames = { "Lower Thickness", "Recommended (Reference Calibrated)", "Mathematically Optimal", "Higher Thickness", "Manual Thickness" };
        static readonly string[] BaseNames = { "Recommended (Reference Calibrated)", "Mathematically Optimal", "No base", "Printer minimum", "Raised base", "Manual base height" };
        static string Select(string input, string current, params string[] choices)
        {
            if (string.IsNullOrWhiteSpace(input)) return current;
            foreach (string item in choices) if (string.Equals(item, input, StringComparison.OrdinalIgnoreCase)) return item;
            foreach (string item in choices)
                if (item.IndexOf(input, StringComparison.OrdinalIgnoreCase) >= 0 || input.IndexOf(item, StringComparison.OrdinalIgnoreCase) >= 0) return item;
            return current;
        }
        static bool Starts(string value, string prefix) { return value.StartsWith(prefix, StringComparison.OrdinalIgnoreCase); }
        static string Numeric(Dictionary<string, object> s, string key, string current, double minimum, bool inclusive)
        {
            double value = ProjectJson.Number(s, key, double.NaN);
            return (inclusive ? value >= minimum : value > minimum) ? value.ToString("0.######", Inv) : current;
        }
        public static ProjectState Read(string json, string path, ProjectState previous, bool includeAssets)
        {
            ProjectState p = previous == null ? new ProjectState() : previous.Snapshot();
            var root = ProjectJson.Parse(json);
            if (ProjectJson.Number(root, "schema", 1) != 1) throw new ArgumentException("Unsupported project schema.");
            var s = ProjectJson.Object(root, "settings");
            var a = ProjectJson.Object(root, "assets");
            var request = ProjectJson.Object(root, "requested_change");
            OpticalSettings o = p.Optics;
            p.ProjectPath = Path.GetFullPath(path);
            p.InputJson = json;
            p.CommandResultJson = "";
            p.Revision = (int)ProjectJson.Number(root, "revision", 0);
            p.ChangedBy = ProjectJson.Text(root, "changed_by", "");
            p.Priority = ProjectJson.Text(request, "priority", "");
            p.Scope = ProjectJson.Text(request, "scope", "");
            p.AnalysisText = ProjectJson.Text(root, "analysis_text", p.AnalysisText);
            o.SizeUnitSelection = "mm";
            o.WidthText = Numeric(s, "width_mm", o.WidthText, 0, false);
            o.HeightText = Numeric(s, "height_mm", o.HeightText, 0, false);
            o.LpiText = Numeric(s, "lpi", o.LpiText, 0, false);
            double views = ProjectJson.Number(s, "views", -1);
            if (views > 0) o.ViewCountText = ((int)views).ToString(Inv);
            double dpi = ProjectJson.Number(s, "printer_dpi", -1);
            if (dpi > 0) o.PrinterDpiSelection = Select(((int)dpi).ToString(Inv), o.PrinterDpiSelection, "600", "720", "1200", "1440", "2400");
            o.SettingsModeSelection = Select(ProjectJson.Text(s, "mode", "Automatic"), o.SettingsModeSelection, "Automatic", "Semi-Automatic", "Manual");
            o.OutputModeSelection = Select(ProjectJson.Text(s, "output_mode", "Lenticular Lens"), o.OutputModeSelection, "Lenticular Lens", "Lens-Free Relief");
            string helper = ProjectJson.Text(s, "lpi_helper_mode", "Manual");
            p.LpiHelperMode = Starts(helper, "recommend") ? "Recommended" : Starts(helper, "detect") ? "Detect from image" : "Manual";
            string detail = ProjectJson.Text(s, "build_detail_mode", "Balanced").Trim().ToUpperInvariant().Replace("-", "_").Replace(" ", "_");
            p.BuildDetailMode = detail == "RECOMMENDED" || detail == "AUTO" || detail == "AUTO_FROM_PRINTER_DPI" ? "Auto from printer DPI" : detail.Contains("QUICK") ? "Quick draft" : detail.Contains("FINE") ? "Fine detail" : detail.Contains("CUSTOM") ? "Custom" : "Balanced";
            double ppl = ProjectJson.Number(s, "pixels_per_lenticule", -1);
            if (ppl > 0) o.PixelsPerLenticuleText = ((int)ppl).ToString(Inv);
            double relief = ProjectJson.Number(s, "relief_prism_height_mm", -1);
            if (relief >= 0.30 && relief <= 5.0) o.ReliefPrismHeightText = relief.ToString("0.###", Inv);
            p.Workflow = Select(ProjectJson.Text(s, "workflow", "Build from source frames"), p.Workflow, "Build from source frames", "Use existing interlaced image", "Build from heightmap");
            o.OrientationSelection = Select(ProjectJson.Text(s, "orientation", "Vertical"), o.OrientationSelection, "Vertical", "Horizontal");
            o.LensProfileSelection = Select(ProjectJson.Text(s, "lens_profile_selection", ProjectJson.Text(s, "lens_profile", "Reference Calibrated")), o.LensProfileSelection, LensNames);
            o.LensProfileIndex = Array.IndexOf(LensNames, o.LensProfileSelection);
            if (Starts(o.LensProfileSelection, "Auto Recommended")) o.LensProfileIndex = 0;
            string print = ProjectJson.Text(s, "print_profile", "Recommended (Reference Calibrated)");
            string baseMode = ProjectJson.Text(s, "base_mode", "Recommended (Reference Calibrated)");
            o.PrintProfileSelection = Starts(print, "Automatic for Selected Lens") ? PrintNames[1] : Select(print, o.PrintProfileSelection, PrintNames);
            o.BaseModeSelection = Starts(baseMode, "Automatic for Selected Lens") ? BaseNames[0] : Select(baseMode, o.BaseModeSelection, BaseNames);
            double manual = ProjectJson.Number(s, "manual_thickness_mm", -1);
            if (manual >= 0) { o.ManualHeightUnitSelection = "mm"; o.ManualHeightText = manual.ToString("0.######", Inv); }
            o.ManualBaseText = Numeric(s, "manual_base_mm", o.ManualBaseText, 0, true);
            o.RefractiveIndexText = Numeric(s, "ior", o.RefractiveIndexText, 1, false);
            string angle = ProjectJson.Text(s, "viewing_angle_mode", "Standard");
            o.ViewingAngleSelection = Starts(angle, "custom") ? "Custom" : Starts(angle, "narrow") ? "Narrow" : Starts(angle, "extra") ? "Extra Wide" : Starts(angle, "wide") ? "Wide" : "Standard";
            double custom = ProjectJson.Number(s, "custom_viewing_angle_deg", -1);
            if (custom > 0 && custom < 179) o.CustomViewingAngleText = custom.ToString("0.######", Inv);
            double backing = ProjectJson.Number(s, "backing_mm", -1);
            if (backing >= 0) p.BackingMm = backing;
            double phase = ProjectJson.Number(s, "phase_pitch", 999);
            if (phase >= -0.5 && phase <= 0.5) p.PhasePitch = Math.Round(phase * 1000.0) / 1000.0;
            p.CalibrationMode = Select(ProjectJson.Text(s, "calibration_mode", "Thickness Test"), p.CalibrationMode, "Thickness Test", "Viewing Test", "Alignment Test", "Lens Type Test");
            p.CalibrationSize = Select(ProjectJson.Text(s, "calibration_coupon_size", "20 mm"), p.CalibrationSize, "15 mm", "20 mm", "25 mm");
            HeightmapWorkflow.Read(p, s, root);
            if (includeAssets)
            {
                p.InterlacedPath = ProjectJson.AbsoluteAssetPath(ProjectJson.Text(a, "interlaced_image", ""), p.ProjectPath);
                p.ReferencePath = ProjectJson.AbsoluteAssetPath(ProjectJson.Text(a, "reference_heightmap", ""), p.ProjectPath);
                p.HeightmapPath = ProjectJson.AbsoluteAssetPath(ProjectJson.Text(a, "heightmap", ""), p.ProjectPath);
                object frames;
                var paths = new List<string>();
                if (a.TryGetValue("source_frames", out frames) && frames is object[])
                    foreach (object value in (object[])frames)
                    {
                        if (!(value is string) || string.IsNullOrWhiteSpace((string)value)) continue;
                        string full = ProjectJson.AbsoluteAssetPath((string)value, p.ProjectPath);
                        if (File.Exists(full) && ProjectJson.SupportedImage(full) && paths.Count < 8) paths.Add(full);
                    }
                p.SourceFrames = paths.ToArray();
                o.FrameCount = paths.Count;
                if (views <= 0 && paths.Count > 0) o.ViewCountText = paths.Count.ToString(Inv);
            }
            if (p.BuildsFromHeightmap) { HeightmapWorkflow.Normalize(p); return p; }
            // Match the established load order: the old selected preset is applied
            // first, then the incoming preset, before settings-mode constraints.
            ApplyLpi(p);
            string preset = ProjectJson.Text(s, "lpi_helper_preset", "Balanced");
            p.LpiHelperPreset = Starts(preset, "Easier") ? "Easier" : Starts(preset, "Finer") ? "Finer" : "Balanced";
            ApplyLpi(p);
            ApplyMode(p);
            Normalize(p);
            return p;
        }

        public static void Normalize(ProjectState p)
        {
            if (p.BuildsFromHeightmap) { HeightmapWorkflow.Normalize(p); return; }
            ApplyLpi(p);
            BuildDetail(p);
            if (!new OpticalEngine(p.Optics).IsLensFreeMode()) ApplyMode(p);
            string reason;
            string recommended = new OpticalEngine(p.Optics).RecommendLensProfileKind(out reason);
            if (p.Optics.LensProfileIndex == 0) p.Optics.LensProfileSelection = "Auto Recommended - " + recommended;
            NormalizeBase(p);
            BuildDetail(p);
            NormalizeBase(p);
            if (p.BuildsFromFrames && p.LpiHelperMode == "Detect from image") p.LpiHelperMode = "Recommended";
            if (!p.BuildsFromFrames && p.LpiHelperMode == "Recommended") p.LpiHelperMode = "Detect from image";
            ApplyLpi(p);
        }

        static void ApplyMode(ProjectState p)
        {
            var e = new OpticalEngine(p.Optics);
            if (e.IsLensFreeMode())
            {
                if (e.IsAutomaticSettingsMode()) { p.LpiHelperMode = "Recommended"; p.LpiHelperPreset = "Balanced"; }
                else if (e.IsSemiAutomaticSettingsMode()) { if (p.LpiHelperMode == "Detect from image") p.LpiHelperMode = "Recommended"; }
                else p.LpiHelperMode = "Manual";
                ApplyLpi(p);
                double lpi;
                if (e.IsAutomaticSettingsMode() && e.TryPositive(p.Optics.LpiText, out lpi))
                    p.Optics.ReliefPrismHeightText = e.RecommendedReliefPrismHeightMm(lpi).ToString("0.###", Inv);
            }
            else if (e.IsAutomaticSettingsMode())
            {
                p.BuildDetailMode = "Auto from printer DPI";
                p.Optics.PrintProfileSelection = e.LensSelectionRequestsMathematicalOptics() ? PrintNames[2] : PrintNames[1];
                p.Optics.BaseModeSelection = e.LensSelectionRequestsMathematicalOptics() ? BaseNames[1] : BaseNames[0];
            }
        }
        static void ApplyLpi(ProjectState p)
        {
            if (p.LpiHelperMode != "Recommended") return;
            var e = new OpticalEngine(p.Optics);
            int views = e.IsLensFreeMode() ? e.ReliefBaselineViewCount() : 3;
            int parsed;
            if (!e.IsLensFreeMode() && int.TryParse(p.Optics.ViewCountText, NumberStyles.Integer, Inv, out parsed) && parsed > 0) views = parsed;
            double easier, balanced, finer; int a, b, c;
            e.GetRecommendedLpiTargets(e.GetSelectedPrinterDpi(), views, out easier, out a, out balanced, out b, out finer, out c);
            double selected = double.Parse((p.LpiHelperPreset == "Easier" ? easier : p.LpiHelperPreset == "Finer" ? finer : balanced).ToString("0.###", Inv), Inv);
            double current;
            if (selected > 0 && (!e.TryPositive(p.Optics.LpiText, out current) || Math.Abs(current - selected) > 0.0001))
                p.Optics.LpiText = selected.ToString("0.###", Inv);
        }
        static void BuildDetail(ProjectState p)
        {
            var e = new OpticalEngine(p.Optics);
            int views = e.GetEffectiveViewCount();
            if (p.BuildDetailMode == "Custom")
            {
                if (string.IsNullOrWhiteSpace(p.Optics.PixelsPerLenticuleText)) p.Optics.PixelsPerLenticuleText = e.SnapPixelsPerLenticule(48, views).ToString(Inv);
                return;
            }
            double lpi;
            if (!e.TryPositive(p.Optics.LpiText, out lpi)) lpi = 20;
            double target = p.BuildDetailMode == "Quick draft" ? Math.Max(24, views * 6) : p.BuildDetailMode == "Balanced" ? Math.Max(48, views * 8) : p.BuildDetailMode == "Fine detail" ? Math.Max(72, views * 10) : e.GetSelectedPrinterDpi() / lpi;
            p.Optics.PixelsPerLenticuleText = e.SnapPixelsPerLenticule(target, views).ToString(Inv);
        }
        static void NormalizeBase(ProjectState p)
        {
            var e = new OpticalEngine(p.Optics);
            try
            {
                double lpi = e.Positive(p.Optics.LpiText, "LPI");
                double target = e.PeakTargetForSelectionMm(lpi);
                double baseMm = e.BaseHeightForSelectionMm(lpi);
                if (e.CurrentBaseModeKind() != "MANUAL") p.Optics.ManualBaseText = baseMm.ToString("0.00", Inv);
                else if (string.IsNullOrWhiteSpace(p.Optics.ManualBaseText)) p.Optics.ManualBaseText = e.RecommendedBaseHeightMm(lpi, target).ToString("0.00", Inv);
                ApplyMode(p);
                e = new OpticalEngine(p.Optics);
                double peak = e.PeakHeightForSelectionMm(lpi);
                if ((e.SelectedLensProfileKind() == "Mathematically Optimal Aspheric" || e.UseMathematicallyOptimalOptics()) && peak + 0.000001 < e.TheoreticalMinimumPeakMm(lpi)) throw new InvalidOperationException();
                if (peak > 0 && peak < e.MinimumValleyHeightMm()) throw new InvalidOperationException();
                if (e.IsCustomViewingAngleMode() && e.UseMathematicallyOptimalOptics() && e.TheoreticalBaseForPeakMm(lpi, peak) > 0 && e.TheoreticalBaseForPeakMm(lpi, peak) < e.MinimumValleyHeightMm() - 0.000001) throw new InvalidOperationException();
                e.ViewingAngleForPeakMm(lpi, peak);
            }
            catch { if (e.CurrentBaseModeKind() != "MANUAL") p.Optics.ManualBaseText = ""; }
        }
    }
}
