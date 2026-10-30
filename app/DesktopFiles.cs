using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using Lenticulizer.Core;

namespace Lenticulizer.Desktop
{
    public static class DesktopFiles
    {
        public static string DiscoverBlender()
        {
            string configured = Environment.GetEnvironmentVariable("BLENDER_EXE");
            if (!string.IsNullOrEmpty(configured) && File.Exists(configured)) return configured;
            var found = new List<string>();
            foreach (string name in new[] { "ProgramFiles", "ProgramFiles(x86)" })
            {
                string root = Environment.GetEnvironmentVariable(name);
                if (string.IsNullOrEmpty(root)) continue;
                string folder = Path.Combine(root, "Blender Foundation");
                if (!Directory.Exists(folder)) continue;
                foreach (string directory in Directory.GetDirectories(folder, "Blender *"))
                { string exe = Path.Combine(directory, "blender.exe"); if (File.Exists(exe)) found.Add(exe); }
            }
            return found.OrderByDescending(path => {
                Version version; return Version.TryParse(Path.GetFileName(Path.GetDirectoryName(path)).Substring(8), out version) ? version : new Version(0,0);
            }).FirstOrDefault() ?? "";
        }
        public static string Quote(string path)
        {
            // A Windows filename cannot contain a quote. Escape final backslashes
            // before the closing quote so directories also survive argv parsing.
            if (path.IndexOf('"') >= 0 || path.IndexOf('\0') >= 0) throw new ArgumentException("Invalid local path.");
            int trailing = path.Length - path.TrimEnd('\\').Length;
            return "\"" + path + new string('\\', trailing) + "\"";
        }
        public static void LaunchBlender(string exe, string scene, string project, string[] directories)
        {
            if (!File.Exists(exe) || !File.Exists(scene)) throw new FileNotFoundException("Blender or the prepared scene is missing.");
            try
            {
                foreach (string directory in directories)
                {
                    Directory.CreateDirectory(directory);
                    foreach (string name in new[] { "pending_blender_project.txt", "current_blender_project.txt" })
                        File.WriteAllText(Path.Combine(directory, name), project, new UTF8Encoding(false));
                }
                // Suppress the Windows console while Blender opens its normal GUI.
                using (var process = Process.Start(new ProcessStartInfo(exe, Quote(scene)) { WorkingDirectory = Path.GetDirectoryName(scene), UseShellExecute = false, CreateNoWindow = true })) { }
            }
            catch
            {
                foreach (string directory in directories)
                    foreach (string name in new[] { "pending_blender_project.txt", "current_blender_project.txt" })
                    {
                        string file = Path.Combine(directory, name);
                        try { if (File.Exists(file) && File.ReadAllText(file).Trim() == project) File.Delete(file); } catch (IOException) { }
                    }
                throw;
            }
        }
        public static string Asset(Dictionary<string, object> project, string kind)
        {
            string path = ProjectJson.Text(ProjectJson.Object(project, "assets"), kind == "heightmap" ? "heightmap" : "interlaced_image", "");
            if (!File.Exists(path)) throw new FileNotFoundException("The requested output image is not available.");
            return path;
        }
        public static string[] Pair(Dictionary<string, object> project)
        {
            var generation = ProjectJson.Object(project, "generation");
            if (generation.Count > 0 && ProjectJson.Text(generation, "status", "") != "ready")
                throw new InvalidOperationException("Wait for a successful generation before exporting both files.");
            return new[] { Asset(project, "interlaced"), Asset(project, "heightmap") };
        }
        sealed class Copy
        {
            public string Source, Destination, Temporary, Backup;
            public bool Installed;
        }
        public static string[] Export(string[] sources, string[] destinations)
        {
            if (sources.Length != destinations.Length) throw new ArgumentException("Each output needs a destination.");
            var copies = new List<Copy>();
            var unique = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (int i = 0; i < sources.Length; i++)
            {
                string destination = Path.GetFullPath(destinations[i]);
                if (!unique.Add(destination)) throw new ArgumentException("The output files need different destinations.");
                if (string.Equals(Path.GetFullPath(sources[i]), destination, StringComparison.OrdinalIgnoreCase)) continue;
                string suffix = ".lenticulizer-" + Guid.NewGuid().ToString("N");
                copies.Add(new Copy { Source = sources[i], Destination = destination, Temporary = destination + suffix + ".tmp", Backup = destination + suffix + ".bak" });
            }
            try
            {
                // Prepare every file before installing either member of a pair.
                foreach (var item in copies) File.Copy(item.Source, item.Temporary, false);
                foreach (var item in copies)
                {
                    if (File.Exists(item.Destination)) File.Move(item.Destination, item.Backup);
                    File.Move(item.Temporary, item.Destination); item.Installed = true;
                }
            }
            catch
            {
                foreach (var item in copies.AsEnumerable().Reverse())
                {
                    if (item.Installed && File.Exists(item.Destination)) File.Delete(item.Destination);
                    if (File.Exists(item.Backup)) File.Move(item.Backup, item.Destination);
                }
                throw;
            }
            finally
            {
                foreach (var item in copies) { if (File.Exists(item.Temporary)) File.Delete(item.Temporary); }
            }
            foreach (var item in copies) { if (File.Exists(item.Backup)) File.Delete(item.Backup); }
            return destinations;
        }
    }
}
