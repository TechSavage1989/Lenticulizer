using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;

namespace Lenticulizer.Core
{
    public static class ProjectSerializer
    {
        public static string Solve(ProjectState p)
        {
            if (p.BuildsFromHeightmap) return HeightmapWorkflow.Solve(p);
            OpticalSettings s = p.Optics;
            OpticalEngine optics = new OpticalEngine(s);
            double wi, hi;
            optics.GetSize(out wi, out hi);
            double widthMm = wi * 25.4;
            double heightMm = hi * 25.4;
            double lpi = optics.Positive(s.LpiText, "LPI");
            double peakMm = optics.PeakHeightForSelectionMm(lpi);
            double baseMm = optics.BaseHeightForSelectionMm(lpi);
            double riseMm = Math.Max(0.0, peakMm - baseMm);
            double viewing = optics.ViewingAngleForPeakMm(lpi, peakMm);
            int views = optics.GetEffectiveViewCount();
            int dpi = optics.GetSelectedPrinterDpi();
            int ppl = 0;
            int.TryParse(s.PixelsPerLenticuleText, NumberStyles.Integer, CultureInfo.InvariantCulture, out ppl);
            if (ppl <= 0) ppl = Math.Max(views, 1);
            double manualThicknessMm = peakMm;
            double tempManual;
            if (optics.TryPositive(s.ManualHeightText, out tempManual))
            {
                if (s.ManualHeightUnitSelection == "um") tempManual /= 1000.0;
                manualThicknessMm = tempManual;
            }
            double manualBaseMm = baseMm;
            double tempBase;
            if (double.TryParse(s.ManualBaseText, NumberStyles.Float, CultureInfo.InvariantCulture, out tempBase) && tempBase >= 0) manualBaseMm = tempBase;
            double customAngle = 0.0;
            double.TryParse(s.CustomViewingAngleText, NumberStyles.Float, CultureInfo.InvariantCulture, out customAngle);

            var sb = new StringBuilder();
            sb.Append("{\"ok\":true,\"settings\":{");
            sb.Append("\"mode\":").Append(ProjectJson.Stringify(optics.CurrentSettingsMode())).Append(',');
            sb.Append("\"output_mode\":").Append(ProjectJson.Stringify(s.OutputModeSelection)).Append(',');
            sb.Append("\"relief_prism_height_mm\":").Append(optics.ReliefPrismHeightMm().ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"workflow\":").Append(ProjectJson.Stringify(p.Workflow)).Append(',');
            sb.Append("\"width_mm\":").Append(widthMm.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"height_mm\":").Append(heightMm.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"lpi\":").Append(lpi.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"lpi_helper_mode\":").Append(ProjectJson.Stringify(p.LpiHelperMode)).Append(',');
            sb.Append("\"lpi_helper_preset\":").Append(ProjectJson.Stringify(p.LpiHelperPreset)).Append(',');
            sb.Append("\"views\":").Append(views.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"printer_dpi\":").Append(dpi.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"build_detail_mode\":").Append(ProjectJson.Stringify(p.BuildDetailMode)).Append(',');
            sb.Append("\"pixels_per_lenticule\":").Append(ppl.ToString(CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"orientation\":").Append(ProjectJson.Stringify(s.OrientationSelection)).Append(',');
            sb.Append("\"lens_profile\":").Append(ProjectJson.Stringify(optics.SelectedLensProfileKind())).Append(',');
            sb.Append("\"lens_profile_selection\":").Append(ProjectJson.Stringify(s.LensProfileSelection)).Append(',');
            sb.Append("\"print_profile\":").Append(ProjectJson.Stringify(PrintLabel(optics.CurrentPrintProfileKind()))).Append(',');
            sb.Append("\"manual_thickness_mm\":").Append(manualThicknessMm.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"base_mode\":").Append(ProjectJson.Stringify(BaseLabel(optics.CurrentBaseModeKind()))).Append(',');
            sb.Append("\"manual_base_mm\":").Append(manualBaseMm.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"thickness_mm\":").Append(peakMm.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"base_mm\":").Append(baseMm.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"rise_mm\":").Append(riseMm.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"viewing_angle_mode\":").Append(ProjectJson.Stringify(optics.ViewingAngleSelectionLabel())).Append(',');
            sb.Append("\"custom_viewing_angle_deg\":").Append(customAngle.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"viewing_angle_deg\":").Append(viewing.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"ior\":").Append(optics.RefractiveIndex().ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"backing_mm\":").Append(p.BackingMm.ToString("0.######", CultureInfo.InvariantCulture)).Append(',');
            sb.Append("\"phase_pitch\":").Append(p.PhasePitch.ToString("0.######", CultureInfo.InvariantCulture));
            sb.Append("},\"analysis_text\":").Append(ProjectJson.Stringify(p.AnalysisText)).Append('}');
            return sb.ToString();
        }

        static string PrintLabel(string kind)
        {
            return kind == "LOWER" ? "Lower Thickness" : kind == "THEORETICAL" ? "Mathematically Optimal" : kind == "HIGHER" ? "Higher Thickness" : kind == "MANUAL" ? "Manual Thickness" : "Recommended (Reference Calibrated)";
        }
        static string BaseLabel(string kind)
        {
            return kind == "THEORETICAL" ? "Mathematically Optimal" : kind == "NONE" ? "No base" : kind == "MINIMUM" ? "Printer minimum" : kind == "RAISED" ? "Raised base" : kind == "MANUAL" ? "Manual base height" : "Recommended (Reference Calibrated)";
        }
        public static string CommandFailure(ProjectState p, string error)
        {
            var request = ProjectJson.Object(ProjectJson.Parse(p.InputJson), "command_request");
            return ProjectJson.Stringify(new Dictionary<string, object> {
                {"id", ProjectJson.Text(request, "id", "revision-" + p.Revision)},
                {"kind", ProjectJson.Text(request, "kind", p.Priority)}, {"status", "failed"}, {"error", error} });
        }
        public static string Publish(ProjectState p, int revision, string status, string error, bool skipCalculation = false)
        {
            var root = ProjectJson.Parse(p.InputJson);
            var settings = ProjectJson.Object(root, "settings");
            if (!skipCalculation)
                foreach (var entry in ProjectJson.Object(ProjectJson.Parse(Solve(p)), "settings")) settings[entry.Key] = entry.Value;
            HeightmapWorkflow.Write(p, settings);
            root["reference_heightmap_info"] = ProjectJson.Parse(p.ReferenceInfoJson);
            settings["manual_thickness_unit"] = "mm";
            settings["calibration_mode"] = p.CalibrationMode;
            settings["calibration_coupon_size"] = p.CalibrationSize;
            root["settings"] = settings;
            var assets = ProjectJson.Object(root, "assets");
            assets["source_frames"] = p.SourceFrames;
            assets["interlaced_image"] = p.InterlacedPath;
            assets["heightmap"] = p.HeightmapPath;
            assets["reference_heightmap"] = p.ReferencePath;
            root["assets"] = assets;
            root["schema"] = 1;
            root["revision"] = revision;
            root["changed_by"] = "app";
            root["changed_utc_ticks"] = DateTime.UtcNow.Ticks;
            root["project_dir"] = Path.GetDirectoryName(p.ProjectPath);
            root["project_name"] = new DirectoryInfo(Path.GetDirectoryName(p.ProjectPath)).Name;
            root["analysis_text"] = p.AnalysisText;
            root["requested_change"] = new Dictionary<string, object> { {"priority", p.Priority}, {"scope", "geometry"} };
            root["generation"] = new Dictionary<string, object> { {"status", status}, {"error", error ?? ""}, {"input_revision", p.Revision} };
            if (!string.IsNullOrEmpty(p.CommandResultJson)) root["command_result"] = ProjectJson.Parse(p.CommandResultJson);
            else if (ProjectCommands.IsCommand(p) && !string.IsNullOrEmpty(error)) root["command_result"] = ProjectJson.Parse(CommandFailure(p, error));
            return ProjectJson.Stringify(root);
        }
    }
}
