using System;
using System.IO;
using System.Text;
using System.Threading;

namespace Lenticulizer.Core
{
    // Owns committed settings, file synchronization and production scheduling.
    // SOLVE is transient: it cannot edit a project, enqueue work, or alter an
    // already captured build. Commands and generation share the same worker.
    public sealed class ProjectSession : IDisposable
    {
        readonly object gate = new object();
        readonly IProjectBuilder builder;
        readonly LatestBuildQueue<BuildRequest, BuildResult> queue;
        readonly Timer poll;
        string path, observed = "", interlaceKey = "", heightmapKey = "";
        string observedSources = "";
        ProjectState current;
        long generation;
        bool disposed;
        public event Action<ProjectState> Published;
        public event Action<string> Diagnostic;

        public ProjectSession(string projectPath, string workingRoot, int debounceMs)
            : this(projectPath, new ProjectBuild(workingRoot), debounceMs) { }
        public ProjectSession(string projectPath, string workingRoot, int debounceMs, ProjectCommands commands)
            : this(projectPath, new ProjectBuild(workingRoot, commands), debounceMs) { }
        internal ProjectSession(string projectPath, IProjectBuilder projectBuilder, int debounceMs)
        {
            path = Path.GetFullPath(projectPath);
            builder = projectBuilder;
            queue = new LatestBuildQueue<BuildRequest, BuildResult>(debounceMs, builder.Run, Completed, builder.Dispose);
            poll = new Timer(Poll, null, Timeout.Infinite, Timeout.Infinite);
        }
        public void Start()
        {
            Poll(null);
            lock (gate) { if (!disposed) poll.Change(350, 350); }
        }
        public ProjectState Snapshot() { lock (gate) return current == null ? null : current.Snapshot(); }
        public string Solve(string json)
        {
            ProjectState basis; string projectPath;
            lock (gate)
            {
                if (disposed) throw new ObjectDisposedException("ProjectSession");
                basis = current == null ? null : current.Snapshot(); projectPath = path;
            }
            return ProjectSerializer.Solve(SettingsRules.Read(json, projectPath, basis, false));
        }
        public void Open(string projectPath)
        {
            lock (gate)
            {
                if (disposed) return;
                string next = Path.GetFullPath(projectPath);
                if (!string.Equals(next, path, StringComparison.OrdinalIgnoreCase))
                {
                    generation++; queue.Cancel();
                    path = next; current = null; observed = interlaceKey = heightmapKey = observedSources = "";
                }
            }
            Poll(null);
        }
        public string Apply(string json)
        {
            string response;
            lock (gate)
            {
                if (disposed) throw new ObjectDisposedException("ProjectSession");
                // APPLY notifications can arrive after a later Electron write.
                // Disk remains authoritative for committed transactions.
                if (File.Exists(path)) json = File.ReadAllText(path, Encoding.UTF8);
                string token = ProjectJson.Canonical(json);
                if (current != null && token == observed) return ProjectSerializer.Solve(current);
                ProjectState next = SettingsRules.Read(json, path, current, true);
                string ik, hk;
                try
                {
                    response = ProjectSerializer.Solve(next);
                    ik = ProjectBuild.InterlaceKey(next); hk = ProjectBuild.HeightmapKey(next);
                }
                catch (Exception error)
                {
                    generation++; queue.Cancel(); current = next; observed = token;
                    observedSources = SourceKey(next);
                    TryPublishLocked(next, token, "failed", error.Message, true);
                    return ProjectJson.Stringify(new System.Collections.Generic.Dictionary<string, object> { {"ok", false}, {"error", error.Message} });
                }
                if (current == null)
                {
                    if (File.Exists(next.InterlacedPath)) interlaceKey = ik;
                    if (File.Exists(next.HeightmapPath)) heightmapKey = hk;
                }
                current = next; observed = token; observedSources = SourceKey(next); generation++;
                ScheduleLocked(next, token, ik, hk);
            }
            return response;
        }
        void ScheduleLocked(ProjectState next, string token, string ik, string hk)
        {
            bool blender = string.Equals(next.ChangedBy, "blender", StringComparison.OrdinalIgnoreCase);
            bool pair = next.Priority == "generate-pair" || next.Priority == "rebuild-pair" || next.Priority == "sources" || (blender && next.Scope == "images");
            bool map = pair || next.Priority == "rebuild-heightmap" || next.Priority == "heightmap" || (blender && (next.Scope == "settings" || next.Scope == "geometry"));
            bool buildInterlace = next.BuildsFromFrames && (pair || ik != interlaceKey || !File.Exists(next.InterlacedPath));
            bool buildMap = buildInterlace || map || hk != heightmapKey || !File.Exists(next.HeightmapPath);
            queue.Submit(new BuildRequest(next, generation, token, buildInterlace, buildMap));
        }
        static string SourceKey(ProjectState p)
        {
            var sb = new StringBuilder();
            foreach (string frame in p.SourceFrames) sb.Append(ProjectBuild.Stamp(frame)).Append('\n');
            sb.Append(ProjectBuild.Stamp(p.ReferencePath));
            if (!p.BuildsFromFrames) sb.Append(ProjectBuild.Stamp(p.InterlacedPath));
            return sb.ToString();
        }
        void Poll(object unused)
        {
            try
            {
                string json;
                lock (gate)
                {
                    if (disposed || !File.Exists(path)) return;
                    json = File.ReadAllText(path, Encoding.UTF8);
                    if (current != null && ProjectJson.Canonical(json) == observed)
                    {
                        string sources = SourceKey(current);
                        if (sources != observedSources)
                        {
                            observedSources = sources; generation++;
                            ScheduleLocked(current, observed, ProjectBuild.InterlaceKey(current), ProjectBuild.HeightmapKey(current));
                        }
                        return;
                    }
                }
                Apply(json);
            }
            catch (IOException) { } // retry transient writer locks on the next tick
            catch (Exception e) { Report(e.Message); }
        }
        void Report(string message)
        {
            Action<string> handler = Diagnostic;
            if (handler != null) try { handler(message); } catch { }
        }
        void Completed(BuildRequest request, BuildResult result, Exception error)
        {
            ProjectState published = null;
            try
            {
                lock (gate)
                {
                    if (disposed || request.Generation != generation || error is OperationCanceledException) return;
                    if (ProjectBuild.InterlaceKey(request.State) != request.InterlaceFingerprint || ProjectBuild.HeightmapKey(request.State) != request.HeightmapFingerprint)
                    {
                        // Source files changed in place during rendering. The polling
                        // pass will capture their new signatures and rebuild once.
                        observedSources = "";
                        return;
                    }
                    ProjectState next = error == null ? result.State : request.State.Snapshot();
                    string status = error == null ? result.Status : "failed";
                    if (TryPublishLocked(next, request.ExpectedDocument, status, error == null ? "" : error.Message, false, result == null ? null : result.Command))
                    {
                        if (result != null) result.Published = true;
                        current = next;
                        if (error == null && status == "ready")
                        {
                            // Record the explicit post-build registration state.
                            interlaceKey = ProjectBuild.InterlaceKey(next);
                            heightmapKey = ProjectBuild.HeightmapKey(next);
                        }
                        observedSources = SourceKey(next);
                        published = next.Snapshot();
                    }
                }
            }
            catch (Exception e)
            {
                Report("Could not publish generation: " + e.Message);
                // Retry a failed publication through the file-sync path. Rendered
                // staging files are discarded; the input project stays authoritative.
                lock (gate) { if (!disposed && request.Generation == generation) observed = ""; }
            }
            finally { if (result != null) result.Dispose(); }
            if (published != null)
            {
                Action<ProjectState> handler = Published;
                if (handler != null) try { handler(published); } catch (Exception e) { Report(e.Message); }
            }
        }

        bool TryPublishLocked(ProjectState next, string expected, string status, string error, bool skipCalculation = false, PreparedCommand command = null)
        {
            // Windows FileShare.None prevents a simultaneous project replacement
            // by Electron or Blender while compare-and-write is in progress.
            // Readers retry locked files. Generation files use private paths, so
            // stale work never overwrites a currently referenced image or map.
            string json;
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None))
            {
                byte[] original = new byte[checked((int)stream.Length)];
                int count = 0, read;
                while (count < original.Length && (read = stream.Read(original, count, original.Length - count)) > 0) count += read;
                if (count != original.Length || ProjectJson.Canonical(Encoding.UTF8.GetString(original)) != expected) return false;
                if (command != null)
                {
                    try { command.Commit(); }
                    catch (Exception failure) { next.CommandResultJson = ProjectSerializer.CommandFailure(next, failure.Message); }
                }
                json = ProjectSerializer.Publish(next, next.Revision + 1, status, error, skipCalculation);
                byte[] bytes = new UTF8Encoding(false).GetBytes(json);
                try
                {
                    stream.Position = 0; stream.Write(bytes, 0, bytes.Length); stream.SetLength(bytes.Length); stream.Flush(true);
                }
                catch
                {
                    try { stream.Position = 0; stream.Write(original, 0, original.Length); stream.SetLength(original.Length); stream.Flush(true); } catch { }
                    throw;
                }
            }
            next.Revision++; next.ChangedBy = "app"; next.InputJson = json;
            observed = ProjectJson.Canonical(json);
            return true;
        }

        public bool WaitForStop(int milliseconds) { return queue.WaitForStop(milliseconds); }
        public void Dispose()
        {
            lock (gate)
            {
                if (disposed) return;
                disposed = true; generation++;
                poll.Dispose(); queue.Dispose();
            }
        }
    }
}
