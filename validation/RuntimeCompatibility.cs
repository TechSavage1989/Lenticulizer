using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using Lenticulizer.Core;

// The emitter runs against the preserved Alpha 21 processing assembly. The same
// case evaluator runs against the actual .NET 10 application during validation.
internal static class RuntimeCompatibility
{
    public static IEnumerable<Dictionary<string,object>> Inputs()
    {
        foreach (string mode in new[] { "Automatic", "Semi-Automatic", "Manual" })
        foreach (string orientation in new[] { "Vertical", "Horizontal" })
        foreach (string output in new[] { "Lenticular Lens", "Lens-Free Relief" })
        foreach (double lpi in new[] { 10.0, 24.0, 36.0, 50.0, 80.0 })
        foreach (double ior in new[] { 1.33, 1.55, 1.8 })
        foreach (string profile in new[] { "Reference Calibrated", "Theoretical Optics" })
            yield return new Dictionary<string,object>
            {
                {"schema",1}, {"settings",new Dictionary<string,object>
                {
                    {"mode",mode}, {"orientation",orientation}, {"output_mode",output},
                    {"lpi",lpi}, {"ior",ior}, {"lens_profile_selection",profile},
                    {"lpi_helper_mode","Manual"}, {"width_mm",45.25}, {"height_mm",32.125},
                    {"views",output == "Lens-Free Relief" ? 2 : 3}, {"printer_dpi",1440},
                    {"print_profile",mode == "Manual" ? "Manual Thickness" : "Recommended (Reference Calibrated)"},
                    {"manual_thickness_mm",1.86}, {"manual_base_mm",0.3}, {"phase_pitch",0.137},
                    {"base_mode","Recommended (Reference Calibrated)"}, {"relief_prism_height_mm",0.8}
                }},
                {"extension",new Dictionary<string,object>{{"literal","Unicode \u00e9 # & + % ' \\path"},{"exponent",1.25e-7}}}
            };
    }

    public static Dictionary<string,object> Evaluate(Dictionary<string,object> input, string directory, string name)
    {
        var result = new Dictionary<string,object>();
        try
        {
            var state = SettingsRules.Read(ProjectJson.Stringify(input), Path.Combine(directory,"project.json"), null, false);
            result["settings"] = ProjectJson.Object(ProjectJson.Parse(ProjectSerializer.Solve(state)), "settings");
            var engine = new OpticalEngine(state.Optics);
            double lpi = double.Parse(state.Optics.LpiText,CultureInfo.InvariantCulture);
            double peak = engine.PeakHeightForSelectionMm(lpi), bottom = engine.BaseHeightForSelectionMm(lpi);
            string profile = engine.SelectedLensProfileKind();
            ushort[] axis = engine.BuildAxis(97,17.25,Math.Max(0,peak-bottom)/(25.4/lpi),state.PhasePitch,profile,bottom/peak);
            result["axis"] = axis.Select(value => (int)value).ToArray();
            result["profile"] = profile;
            string png = Path.Combine(directory,name+".png");
            ProductionEngine.WriteHeightmapForPath(png,45.25/25.4,32.125/25.4,lpi,state.Optics.OrientationSelection=="Vertical",peak,bottom,97,53,"",state.PhasePitch,state.Optics);
            result["png"] = Convert.ToBase64String(File.ReadAllBytes(png)); File.Delete(png);
        }
        catch (Exception error) { result["error"] = error.Message; }
        return result;
    }

#if EMIT_REFERENCE
    static int Main(string[] args)
    {
        string temporary = Path.Combine(Path.GetTempPath(),"Lenticulizer-reference-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        try
        {
            var cases = new List<object>(); int index=0;
            foreach (var input in Inputs()) cases.Add(new Dictionary<string,object>{{"input",input},{"expected",Evaluate(input,temporary,(index++).ToString())}});
            File.WriteAllText(args[0],ProjectJson.Stringify(new Dictionary<string,object>{{"cases",cases.ToArray()}}));
            Console.WriteLine("Created "+cases.Count+" Alpha 21 optical/settings/heightmap reference cases."); return 0;
        }
        finally { Directory.Delete(temporary,true); }
    }
#endif
}
