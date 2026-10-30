using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using Lenticulizer.Core;

namespace Lenticulizer.Desktop
{
    // The controller and ProjectSession live in the application's process. Only
    // Blender uses the shared document; there is no core executable or pipe.
    public sealed class IntegratedProject : IDisposable
    {
        readonly object gate = new object();
        readonly ProjectSession session;
        readonly Timer watcher;
        readonly string localRoot;
        readonly HashSet<string> images = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        string projectPath, lastNotification = "";
        bool disposed;
        public event Action<Dictionary<string, object>> Updated;
        public event Action<string> Diagnostic;
        public string ProjectPath { get { lock (gate) return projectPath; } }
        public string SessionDirectory { get { return Path.GetDirectoryName(ProjectPath); } }

        public IntegratedProject(string path, string working, string template, string appData)
        {
            projectPath = Path.GetFullPath(path); localRoot = appData;
            session = new ProjectSession(projectPath, working, 220, new ProjectCommands(new BlenderTemplate(template, Assembly.GetExecutingAssembly())));
            session.Diagnostic += Log;
            session.Published += delegate(ProjectState state) { Observe(false); };
            watcher = new Timer(delegate { Observe(true); }, null, Timeout.Infinite, Timeout.Infinite);
        }
        public void Start() { lock (gate) { RequireProject(null); session.Start(); watcher.Change(200, 200); } }
        void Log(string message) { var handler = Diagnostic; if (handler != null) handler(message); }
        static T Retry<T>(Func<T> action)
        {
            for (int i = 0; ; i++)
            {
                try { return action(); }
                catch (IOException) { if (i >= 20) throw; }
                catch (UnauthorizedAccessException) { if (i >= 20) throw; }
                Thread.Sleep(10);
            }
        }
        void RequireProject(string expected)
        {
            if (disposed) throw new ObjectDisposedException("IntegratedProject");
            if (!string.IsNullOrEmpty(expected) && !string.Equals(Path.GetFullPath(expected), projectPath, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("The active project changed. Repeat this action in the current project.");
        }
        Dictionary<string, object> ReadLocked()
        {
            return Retry(delegate {
                using (var stream = new FileStream(projectPath, FileMode.Open, FileAccess.Read, FileShare.Read))
                using (var reader = new StreamReader(stream, Encoding.UTF8)) return ProjectJson.Parse(reader.ReadToEnd());
            });
        }
        public static Dictionary<string, object> Merge(Dictionary<string, object> basis, Dictionary<string, object> patch)
        {
            var result = ProjectJson.Parse(ProjectJson.Stringify(basis));
            foreach (var item in patch)
            {
                var nested = item.Value as Dictionary<string, object>;
                result[item.Key] = nested == null ? item.Value : Merge(ProjectJson.Object(result, item.Key), nested);
            }
            return result;
        }
        Dictionary<string, object> ForUi(Dictionary<string, object> value, bool switched = false)
        {
            var result = ProjectJson.Parse(ProjectJson.Stringify(value));
            var assets = ProjectJson.Object(result, "assets");
            foreach (var key in new[] { "interlaced_image", "heightmap", "reference_heightmap" })
            {
                string path = ProjectJson.AbsoluteAssetPath(ProjectJson.Text(assets, key, ""), projectPath);
                assets[key] = path; if (File.Exists(path)) images.Add(path);
            }
            object frames;
            if (assets.TryGetValue("source_frames", out frames) && frames is object[])
            {
                var paths = new List<string>();
                foreach (object item in (object[])frames)
                {
                    if (!(item is string)) continue;
                    string path = ProjectJson.AbsoluteAssetPath((string)item, projectPath);
                    paths.Add(path); if (File.Exists(path)) images.Add(path);
                }
                assets["source_frames"] = paths.ToArray();
            }
            result["assets"] = assets;
            result["active_project_path"] = projectPath;
            result["active_session_dir"] = Path.GetDirectoryName(projectPath);
            if (switched) result["project_switched"] = true;
            return result;
        }
        public Dictionary<string, object> Read()
        {
            lock (gate) { RequireProject(null); return ForUi(ReadLocked()); }
        }
        public Dictionary<string, object> Solve(Dictionary<string, object> patch, string expected)
        {
            lock (gate)
            {
                RequireProject(expected);
                return ProjectJson.Parse(session.Solve(ProjectJson.Stringify(Merge(ReadLocked(), patch))));
            }
        }
        public Dictionary<string, object> Patch(Dictionary<string, object> patch, string priority, string expected)
        {
            Dictionary<string, object> written;
            lock (gate)
            {
                RequireProject(expected);
                written = Retry(delegate {
                    // Read, merge and write under the same exclusive file handle.
                    // A Blender or generation commit cannot be lost between reads.
                    using (var stream = new FileStream(projectPath, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
                    {
                        byte[] original = new byte[checked((int)stream.Length)];
                        int count = 0, read;
                        while (count < original.Length && (read = stream.Read(original, count, original.Length-count)) > 0) count += read;
                        if (count != original.Length) throw new IOException("The shared project could not be read completely.");
                        var current = ProjectJson.Parse(Encoding.UTF8.GetString(original));
                        var next = Merge(current, patch);
                        next.Remove("project_switched"); next.Remove("active_project_path"); next.Remove("active_session_dir");
                        next["schema"] = 1; next["revision"] = (int)ProjectJson.Number(current, "revision", 0) + 1;
                        next["changed_by"] = "integrated"; next["changed_utc_ticks"] = DateTime.UtcNow.Ticks;
                        next["project_dir"] = Path.GetDirectoryName(projectPath);
                        next["project_name"] = new DirectoryInfo(Path.GetDirectoryName(projectPath)).Name;
                        next["requested_change"] = new Dictionary<string, object> { {"priority", priority}, {"scope", "geometry"} };
                        if (!patch.ContainsKey("command_request")) next.Remove("command_request");
                        next["generation"] = new Dictionary<string, object> { {"status", "queued"}, {"error", ""}, {"input_revision", next["revision"]} };
                        byte[] bytes = new UTF8Encoding(false).GetBytes(ProjectJson.Stringify(next));
                        try { stream.Position = 0; stream.Write(bytes, 0, bytes.Length); stream.SetLength(bytes.Length); stream.Flush(true); }
                        catch
                        {
                            try { stream.Position = 0; stream.Write(original, 0, original.Length); stream.SetLength(original.Length); stream.Flush(true); } catch { }
                            throw;
                        }
                        return next;
                    }
                });
                // Direct function call. ProjectSession schedules generation on its worker.
                session.Apply(ProjectJson.Stringify(written));
                written = ForUi(written);
            }
            Observe(false);
            return written;
        }
        public string[] HandoffDirectories()
        {
            return new[] { Path.Combine(localRoot, "Lenticulizer"), Path.Combine(localRoot, "Lenticular Lens Heightmap Generator") };
        }
        string HandoffCandidate(string file)
        {
            string path = File.ReadAllText(file, Encoding.UTF8).Trim().TrimStart('\uFEFF');
            if (Directory.Exists(path)) path = Path.Combine(path, "project.json");
            return Path.GetFullPath(path);
        }
        bool ConsumeHandoffLocked()
        {
            foreach (string directory in HandoffDirectories())
            {
                string pointer = Path.Combine(directory, "pending_app_project.txt");
                if (!File.Exists(pointer)) continue;
                if (DateTime.UtcNow - File.GetLastWriteTimeUtc(pointer) > TimeSpan.FromMinutes(5)) { File.Delete(pointer); continue; }
                string selected;
                try
                {
                    selected = HandoffCandidate(pointer);
                    if (!File.Exists(selected)) { File.Delete(pointer); continue; }
                    var candidate = ProjectJson.Parse(File.ReadAllText(selected, Encoding.UTF8));
                    if (ProjectJson.Number(candidate, "schema", 1) != 1) throw new ArgumentException("Unsupported shared-project schema.");
                }
                catch (IOException) { continue; }
                catch (ArgumentException error) { Log("Invalid shared-project handoff: " + error.Message); continue; }
                catch (NotSupportedException error) { Log("Invalid shared-project path: " + error.Message); continue; }
                string previous = projectPath;
                projectPath = selected;
                try { session.Open(selected); }
                catch { projectPath = previous; session.Open(previous); throw; }
                foreach (string duplicate in HandoffDirectories())
                {
                    string file = Path.Combine(duplicate, "pending_app_project.txt");
                    try { if (File.Exists(file) && string.Equals(HandoffCandidate(file), selected, StringComparison.OrdinalIgnoreCase)) File.Delete(file); }
                    catch (IOException) { }
                }
                images.Clear(); lastNotification = "";
                return true;
            }
            return false;
        }
        void Observe(bool handoffs)
        {
            Dictionary<string, object> next = null;
            try
            {
                lock (gate)
                {
                    if (disposed) return;
                    bool switched = handoffs && ConsumeHandoffLocked();
                    var value = ReadLocked();
                    string signature = projectPath + "\n" + ProjectJson.Stringify(value);
                    if (!switched && (signature == lastNotification || ProjectJson.Text(value, "changed_by", "") == "integrated")) return;
                    lastNotification = signature; next = ForUi(value, switched);
                }
                var handler = Updated; if (handler != null) handler(next);
            }
            catch (Exception error) { Log(error.Message); }
        }
        public Dictionary<string, object> ImageInfo(string path)
        {
            lock (gate)
            {
                RequireProject(null); path = Path.GetFullPath(path);
                if (!File.Exists(path) || !ProjectJson.SupportedImage(path)) throw new ArgumentException("Choose a supported image file.");
                images.Add(path);
                return new Dictionary<string, object> { {"path", path}, {"name", Path.GetFileName(path)}, {"url", ImageUrl(path)} };
            }
        }
        public static string ImageUrl(string path) { return AppResources.Origin + "/local-image?path=" + Uri.EscapeDataString(path); }
        public byte[] ReadImage(string path)
        {
            lock (gate)
            {
                RequireProject(null); path = Path.GetFullPath(path);
                if (!images.Contains(path) || !ProjectJson.SupportedImage(path)) throw new UnauthorizedAccessException("This image is not part of the active project.");
            }
            byte[] bytes = Retry(delegate { return File.ReadAllBytes(path); });
            string extension = Path.GetExtension(path).ToLowerInvariant();
            if (extension != ".tif" && extension != ".tiff") return bytes;
            // Chromium cannot display TIFF. Convert a bounded preview only;
            // generation continues to read the original, full-resolution file.
            using (var input = new MemoryStream(bytes, false))
            using (var original = new System.Drawing.Bitmap(input))
            {
                double scale = Math.Min(1.0, 2048.0 / Math.Max(original.Width, original.Height));
                using (var preview = new System.Drawing.Bitmap(Math.Max(1,(int)Math.Round(original.Width*scale)), Math.Max(1,(int)Math.Round(original.Height*scale))))
                using (var output = new MemoryStream())
                {
                    using (var graphics = System.Drawing.Graphics.FromImage(preview))
                    { graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic; graphics.DrawImage(original,0,0,preview.Width,preview.Height); }
                    preview.Save(output,System.Drawing.Imaging.ImageFormat.Png); return output.ToArray();
                }
            }
        }
        public void Dispose()
        {
            lock (gate)
            {
                if (disposed) return;
                disposed = true; watcher.Dispose(); session.Dispose();
            }
        }
        public bool WaitForStop(int milliseconds) { return session.WaitForStop(milliseconds); }
    }
}
