using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Web.Script.Serialization;

namespace Lenticulizer.Core
{
    // Mutable only while assembling a transaction. Controllers and workers take
    // deep snapshots; no WinForms object or callback is retained in project state.
    public sealed class ProjectState
    {
        public OpticalSettings Optics = new OpticalSettings();
        public string ProjectPath = "";
        public string Workflow = "Build from source frames";
        public string LpiHelperMode = "Recommended";
        public string LpiHelperPreset = "Easier";
        public string BuildDetailMode = "Auto from printer DPI";
        public double BackingMm = 5.0;
        public double PhasePitch;
        public string CalibrationMode = "Thickness Test";
        public string CalibrationSize = "20 mm";
        public string InterlacedPath = "";
        public string HeightmapPath = "";
        public string ReferencePath = "", ReferenceInfoJson = "{}";
        public double ReferenceWidthMm = 100, ReferenceHeightMm = 100, ReferenceScaleMm = 1.86;
        public string ReferenceOrientation = "Vertical", ReferenceStyle = "OPAQUE", ReferenceDetection = "Automatic";
        public double ReferencePitchPx, ReferencePhasePitch;
        public bool ReferenceShow;
        public string[] SourceFrames = new string[0];
        public string AnalysisText = "";
        public string ChangedBy = "";
        public string Priority = "";
        public string Scope = "";
        public int Revision;
        public string InputJson = "{}";
        public string CommandResultJson = "";

        public ProjectState()
        {
            // Legacy startup has no physical size or manual override entered.
            Optics.WidthText = Optics.HeightText = Optics.ViewCountText = "";
            Optics.ManualHeightText = Optics.ManualBaseText = "";
            SettingsRules.Normalize(this);
        }

        public ProjectState Snapshot()
        {
            var result = (ProjectState)MemberwiseClone();
            result.Optics = Optics.Snapshot();
            result.SourceFrames = (string[])SourceFrames.Clone();
            return result;
        }

        public bool BuildsFromHeightmap { get { return Workflow == "Build from heightmap"; } }
        public bool BuildsFromFrames { get { return Workflow == "Build from source frames" || BuildsFromHeightmap; } }
    }

    // Uses the framework JSON parser, including escaped paths, Unicode and
    // exponent-form numbers. Unknown document fields survive publication.
    public static class ProjectJson
    {
        static JavaScriptSerializer Serializer()
        {
            return new JavaScriptSerializer { MaxJsonLength = 16 * 1024 * 1024, RecursionLimit = 64 };
        }
        public static Dictionary<string, object> Parse(string json)
        {
            if (json != null && json.StartsWith("\uFEFF", StringComparison.Ordinal)) json = json.Substring(1);
            var value = Serializer().DeserializeObject(json) as Dictionary<string, object>;
            if (value == null) throw new ArgumentException("A project must be a JSON object.");
            return value;
        }
        public static string Stringify(object value) { return Serializer().Serialize(value); }
        public static Dictionary<string, object> Object(Dictionary<string, object> parent, string key)
        {
            object value;
            if (parent.TryGetValue(key, out value) && value is Dictionary<string, object>)
                return (Dictionary<string, object>)value;
            return new Dictionary<string, object>();
        }
        public static string Text(Dictionary<string, object> parent, string key, string fallback)
        {
            object value;
            return parent.TryGetValue(key, out value) && value is string ? (string)value : fallback;
        }
        public static double Number(Dictionary<string, object> parent, string key, double fallback)
        {
            object value;
            if (!parent.TryGetValue(key, out value) || value == null || value is bool) return fallback;
            double number;
            if (!double.TryParse(Convert.ToString(value, CultureInfo.InvariantCulture), NumberStyles.Float,
                CultureInfo.InvariantCulture, out number) || double.IsNaN(number) || double.IsInfinity(number)) return fallback;
            return number;
        }
        public static string Canonical(string json) { return Stringify(Sorted(Parse(json))); }
        static object Sorted(object value)
        {
            var map = value as Dictionary<string, object>;
            if (map != null)
            {
                var result = new SortedDictionary<string, object>(StringComparer.Ordinal);
                foreach (var pair in map) result.Add(pair.Key, Sorted(pair.Value));
                return result;
            }
            var array = value as object[];
            if (array != null)
            {
                var result = new object[array.Length];
                for (int i = 0; i < array.Length; i++) result[i] = Sorted(array[i]);
                return result;
            }
            return value;
        }
        public static string AbsoluteAssetPath(string path, string projectPath)
        {
            if (string.IsNullOrWhiteSpace(path)) return "";
            return Path.GetFullPath(Path.IsPathRooted(path) ? path : Path.Combine(Path.GetDirectoryName(projectPath), path));
        }
        public static bool SupportedImage(string path)
        {
            string ext = Path.GetExtension(path).ToLowerInvariant();
            return ext == ".png" || ext == ".jpg" || ext == ".jpeg" || ext == ".bmp" || ext == ".tif" || ext == ".tiff" || ext == ".gif";
        }
    }
}
