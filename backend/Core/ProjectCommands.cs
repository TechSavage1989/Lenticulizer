using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;

namespace Lenticulizer.Core
{
    // A prepared command owns private files. Only the session's successful
    // compare-and-write transaction may install them at their chosen destination.
    internal sealed class PreparedCommand
    {
        public string Id, Kind, Path, Message;
        public Action Commit;
        public Dictionary<string, object> Result()
        {
            return new Dictionary<string, object> { {"id", Id}, {"kind", Kind}, {"status", "ready"}, {"path", Path ?? ""}, {"message", Message ?? ""} };
        }
    }

    public sealed class BlenderTemplate
    {
        readonly string externalPath;
        readonly Assembly resourceAssembly;
        public BlenderTemplate(string externalPath, Assembly resourceAssembly)
        { this.externalPath = externalPath; this.resourceAssembly = resourceAssembly; }
        public void CopyTo(string destination)
        {
            using (Stream input = File.Exists(externalPath) ? (Stream)File.OpenRead(externalPath) : resourceAssembly.GetManifestResourceStream("Lenticulizer.BlenderTemplate.blend"))
            {
                if (input == null) throw new FileNotFoundException("The Blender baseline scene is missing.");
                using (var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None)) input.CopyTo(output);
            }
        }
    }

    public sealed class ProjectCommands
    {
        readonly BlenderTemplate template;
        public ProjectCommands(BlenderTemplate template) { this.template = template; }
        public static bool IsCommand(ProjectState state)
        {
            if (!string.Equals(state.ChangedBy, "electron", StringComparison.OrdinalIgnoreCase) &&
                !string.Equals(state.ChangedBy, "integrated", StringComparison.OrdinalIgnoreCase)) return false;
            switch (state.Priority)
            {
                case "analyze": case "calibration": case "blender-sync": case "blender-open": case "blender-reset": case "blender-export": return true;
                default: return false;
            }
        }
        internal static void InstallFile(string source, string destination)
        {
            // Stage beside the destination so installation is on one volume.
            string temp = destination + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                File.Copy(source, temp, false);
                if (File.Exists(destination)) File.Replace(temp, destination, null);
                else File.Move(temp, destination);
            }
            finally { if (File.Exists(temp)) File.Delete(temp); }
        }
        internal PreparedCommand Prepare(ProjectState state, string staging, Func<bool> cancelled)
        {
            if (cancelled()) throw new OperationCanceledException();
            var request = ProjectJson.Object(ProjectJson.Parse(state.InputJson), "command_request");
            var command = new PreparedCommand { Id = ProjectJson.Text(request, "id", "revision-" + state.Revision), Kind = state.Priority, Commit = delegate { } };
            if (state.Priority == "analyze") { command.Message = "Image analysis complete."; return command; }
            if (state.Priority == "blender-sync") { command.Message = "Current project published for the connected Blender session."; return command; }
            if (state.Priority == "blender-open" || state.Priority == "blender-reset")
            {
                command.Path = Path.Combine(Path.GetDirectoryName(state.ProjectPath), "Lenticulizer_3D_Project.blend");
                bool overwrite = state.Priority == "blender-reset";
                if (overwrite || !File.Exists(command.Path))
                {
                    string scene = Path.Combine(staging, "baseline.blend");
                    template.CopyTo(scene);
                    command.Commit = delegate { if (overwrite || !File.Exists(command.Path)) InstallFile(scene, command.Path); };
                }
                command.Message = overwrite ? "Blender project scene reset." : "Blender project scene ready.";
                return command;
            }
            string destination = ProjectJson.Text(request, "destination", "");
            if (!System.IO.Path.IsPathRooted(destination)) throw new ArgumentException("Choose an export destination in the app.");
            if (!File.Exists(state.InterlacedPath)) throw new InvalidOperationException("Build or import an interlaced image first.");
            if (state.Priority == "calibration")
            {
                if (state.BuildsFromHeightmap) throw new InvalidOperationException("Procedural calibration changes lens geometry. Use the registration control to align an imported heightmap.");
                if (!Directory.Exists(destination)) throw new DirectoryNotFoundException("The calibration destination no longer exists.");
                string folder = Path.Combine(staging, "coupons");
                int count;
                using (var bitmap = new Bitmap(state.InterlacedPath)) count = new CalibrationService(state, bitmap).Generate(folder, cancelled);
                string name = "Lenticular_Calibration_" + CalibrationService.SafeCalibrationName(state.CalibrationMode) + "_" + DateTime.Now.ToString("yyyyMMdd_HHmmss", CultureInfo.InvariantCulture) + "_" + Guid.NewGuid().ToString("N").Substring(0, 6);
                command.Path = Path.Combine(destination, name);
                command.Commit = delegate
                {
                    string temp = command.Path + ".tmp";
                    try
                    {
                        Directory.CreateDirectory(temp);
                        foreach (string file in Directory.GetFiles(folder)) File.Copy(file, Path.Combine(temp, Path.GetFileName(file)));
                        Directory.Move(temp, command.Path);
                    }
                    finally { if (Directory.Exists(temp)) Directory.Delete(temp, true); }
                };
                command.Message = "Exported " + count + " calibration heightmaps and their source coupon.";
            }
            else if (state.Priority == "blender-export")
            {
                if (!Directory.Exists(Path.GetDirectoryName(destination))) throw new DirectoryNotFoundException("The export folder no longer exists.");
                string folder = Path.Combine(staging, "portable");
                BuildPackage(state, folder, cancelled);
                string archive = Path.Combine(staging, "portable.zip");
                ZipFile.CreateFromDirectory(folder, archive);
                command.Path = destination;
                command.Commit = delegate { InstallFile(archive, destination); };
                command.Message = "Portable Blender package exported.";
            }
            if (cancelled()) throw new OperationCanceledException();
            return command;
        }
        void BuildPackage(ProjectState p, string folder, Func<bool> cancelled)
        {
            Directory.CreateDirectory(folder);
            if (p.BuildsFromHeightmap || !string.IsNullOrEmpty(p.ReferencePath)) { BuildImportedPackage(p,folder,cancelled); return; }
            var optics = new OpticalEngine(p.Optics);
            double wi, hi; optics.GetSize(out wi, out hi);
            double lpi = optics.Positive(p.Optics.LpiText, "LPI");
            double peak = optics.HeightUm(lpi) / 1000.0;
            if (peak > optics.MaximumTopHeightMm() + 0.0001) throw new InvalidOperationException("Selected height exceeds printer maximum.");
            optics.ValidateTheoreticalProfileGeometry(lpi, peak);
            double valley = optics.BaseHeightForSelectionMm(lpi);
            if (valley > peak) throw new InvalidOperationException("Valley height cannot be greater than peak height.");
            bool vertical = p.Optics.OrientationSelection == "Vertical";
            int views = optics.GetEffectiveViewCount();
            double angle = optics.ViewingAngleForPeakMm(lpi, peak);
            string image = "interlaced_image" + Path.GetExtension(p.InterlacedPath);
            File.Copy(p.InterlacedPath, Path.Combine(folder, image));
            using (var bitmap = new Bitmap(p.InterlacedPath))
                ProductionEngine.WriteHeightmapForPath(Path.Combine(folder, "heightmap16.png"), wi, hi, lpi, vertical, peak, valley, bitmap.Width, bitmap.Height, p.InterlacedPath, p.PhasePitch, p.Optics);
            if (cancelled()) throw new OperationCanceledException();
            File.WriteAllText(Path.Combine(folder, "blender_simulation.py"), BlenderScript.BuildBlenderSimulationScript(image, "heightmap16.png", wi * 25.4, hi * 25.4, p.BackingMm, peak, valley, angle, views, vertical, optics.RefractiveIndex(), optics.IsLensFreeMode()), new UTF8Encoding(false));
            template.CopyTo(Path.Combine(folder, "Lenticulizer_3D_Template.blend"));
            File.WriteAllText(Path.Combine(folder, "README.txt"), BlenderScript.BuildBlenderReadme(peak, valley, p.BackingMm, wi * 25.4, hi * 25.4, optics.IsLensFreeMode()), new UTF8Encoding(false));
            using (var writer = new StreamWriter(Path.Combine(folder, "simulation_settings.csv"), false, new UTF8Encoding(false)))
            {
                writer.WriteLine("Setting,Value");
                Csv(writer, "Interlaced image", image); Csv(writer, "Heightmap", "heightmap16.png");
                Csv(writer, "Print width mm", wi * 25.4); Csv(writer, "Print height mm", hi * 25.4);
                Csv(writer, "LPI", lpi); Csv(writer, "Views", views);
                Csv(writer, "Lens orientation", vertical ? "Vertical" : "Horizontal");
                Csv(writer, "UV Thickness mm", peak); Csv(writer, "Valley height mm", valley);
                Csv(writer, "Lens rise mm", peak - valley); Csv(writer, "Viewing angle deg", angle);
                Csv(writer, "Backing thickness mm", p.BackingMm);
                Csv(writer, optics.IsLensFreeMode() ? "Relief topology" : "Lens shape", optics.IsLensFreeMode() ? "One planar facet per view" : optics.SelectedLensProfileKind());
                Csv(writer, "Settings mode", optics.CurrentSettingsMode());
            }
        }
        void BuildImportedPackage(ProjectState p,string folder,Func<bool> cancelled)
        {
            if (!File.Exists(p.HeightmapPath)) throw new InvalidOperationException("Generate the matched image and heightmap first.");
            var root=ProjectJson.Parse(ProjectSerializer.Publish(p,1,"ready",""));
            var assets=ProjectJson.Object(root,"assets");
            string image="interlaced_image.png",map="heightmap_imported"+Path.GetExtension(p.HeightmapPath).ToLowerInvariant();
            File.Copy(p.InterlacedPath,Path.Combine(folder,image));
            File.Copy(p.HeightmapPath,Path.Combine(folder,map));
            assets["interlaced_image"]=image;assets["heightmap"]=map;
            string reference="reference_heightmap"+Path.GetExtension(p.ReferencePath).ToLowerInvariant();
            File.Copy(p.ReferencePath,Path.Combine(folder,reference));assets["reference_heightmap"]=reference;
            Directory.CreateDirectory(Path.Combine(folder,"sources"));var frames=new List<string>();
            for(int i=0;i<p.SourceFrames.Length;i++)
            {
                if(cancelled())throw new OperationCanceledException();
                string relative="sources/"+i+"_"+Path.GetFileName(p.SourceFrames[i]);
                File.Copy(p.SourceFrames[i],Path.Combine(folder,relative));frames.Add(relative);
            }
            assets["source_frames"]=frames.ToArray();root["project_dir"]="";
            root.Remove("command_request");root.Remove("command_result");
            root["requested_change"]=new Dictionary<string,object>{{"priority",""},{"scope","reference"}};
            File.WriteAllText(Path.Combine(folder,"project.json"),ProjectJson.Stringify(root),new UTF8Encoding(false));
            template.CopyTo(Path.Combine(folder,"Lenticulizer_3D_Template.blend"));
            using(var input=Assembly.GetExecutingAssembly().GetManifestResourceStream("Lenticulizer.BlenderAddon.zip"))
            using(var output=File.Create(Path.Combine(folder,"Lenticulizer_Blender_Addon.zip")))input.CopyTo(output);
            File.WriteAllText(Path.Combine(folder,"README.txt"),"This package includes the current output pair, source images, reference heightmap and its physical scale.\r\nInstall the included Blender add-on, open Lenticulizer_3D_Template.blend, then open this folder's project.json in the Lenticulizer sidebar.\r\nThe source images and physical heightmap scale are included. The selected project workflow is restored on import.\r\n",new UTF8Encoding(false));
        }
        static void Csv(StreamWriter writer, string key, object value)
        {
            string text = value is double ? ((double)value).ToString("0.######", CultureInfo.InvariantCulture) : Convert.ToString(value, CultureInfo.InvariantCulture);
            writer.WriteLine("\"" + key.Replace("\"", "\"\"") + "\",\"" + text.Replace("\"", "\"\"") + "\"");
        }
    }
}
