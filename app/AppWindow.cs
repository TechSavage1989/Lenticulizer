using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Forms;
using Lenticulizer.Core;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Lenticulizer.Desktop
{
    internal sealed class AppWindow : Form
    {
        const string Origin = AppResources.Origin;
        const string ImagesFilter = "Images|*.png;*.jpg;*.jpeg;*.bmp;*.tif;*.tiff";
        readonly WebView2 view = new WebView2();
        readonly CancellationTokenSource startupCancellation = new CancellationTokenSource();
        readonly Panel preparing = new Panel { Dock = DockStyle.Fill };
        readonly Label preparingLabel = new Label { Dock = DockStyle.Top, Height = 70, TextAlign = ContentAlignment.MiddleCenter, ForeColor = Color.White, Text = "Preparing Lenticulizer..." };
        readonly ProgressBar preparingProgress = new ProgressBar { Dock = DockStyle.Top, Height = 18, Minimum = 0, Maximum = 100 };
        readonly SemaphoreSlim dialogs = new SemaphoreSlim(1, 1);
        readonly SemaphoreSlim commits = new SemaphoreSlim(1, 1);
        readonly Dictionary<string, string[]> pendingBlender = new Dictionary<string, string[]>();
        readonly UpdateService updater = new UpdateService();
        readonly System.Windows.Forms.Timer updateTimer = new System.Windows.Forms.Timer { Interval = 300000 };
        IntegratedProject project;
        bool closing, closed, ready, restartForUpdate, rollbackNoticeShown;
        int activeOperations;
        string addonPath;
        readonly string uiReport;
        readonly string updateHealthToken;
        readonly bool rollbackNotice;
        bool checkFinished;
        int imageRequests, imageResponses;
        readonly List<string> resourceErrors = new List<string>();
        public int ExitCode { get; private set; }
        public AppWindow(string uiReport, string updateHealthToken, bool rollbackNotice)
        {
            this.uiReport = uiReport;
            this.updateHealthToken = updateHealthToken ?? "";
            this.rollbackNotice = rollbackNotice;
            Text = "Lenticulizer " + Program.Version;
            BackColor = Color.FromArgb(32,37,44); Size = new Size(1540,980); MinimumSize = new Size(1120,760);
            AutoScaleMode = AutoScaleMode.Dpi; StartPosition = FormStartPosition.CenterScreen;
            using (var icon = AppResources.OpenEmbedded("/assets/Lenticulizer.ico")) Icon = new Icon(icon);
            AppPreferences.RestoreWindow(this);
            view.Dock = DockStyle.Fill; view.DefaultBackgroundColor = BackColor; Controls.Add(view);
            preparing.BackColor = BackColor; preparing.Padding = new Padding(60,150,60,30);
            preparing.Controls.Add(preparingProgress); preparing.Controls.Add(preparingLabel); Controls.Add(preparing); preparing.BringToFront();
            updater.StatusChanged += value => OnUi(delegate { if (ready) Send(new { @event = "update-status", data = value }); });
            updateTimer.Tick += async delegate { if (!closing) await CheckUpdatesSafe(false); };
            Shown += async delegate { updateTimer.Start(); _ = CheckUpdatesSafe(false); await Initialize(); };
            Activated += async delegate { if (!closing && updater.ShouldCheckOnFocus(TimeSpan.FromMinutes(2))) await CheckUpdatesSafe(false); };
            FormClosing += CloseApplication;
        }
        async Task CheckUpdatesSafe(bool manual)
        {
            try { await updater.CheckAsync(manual, startupCancellation.Token); }
            catch (OperationCanceledException) { }
            catch (Exception error) { Program.Log("Automatic update check: " + error); }
        }

        string PrepareBlenderAddon()
        {
            string directory = Path.Combine(Program.LocalRoot, "Lenticulizer", "BlenderAddon");
            Directory.CreateDirectory(directory);
            string destination = Path.Combine(directory, "Lenticulizer_3D_Blender_Addon_v1.18.43.zip");
            string temporary = destination + ".tmp-" + Guid.NewGuid().ToString("N");
            try
            {
                using (var input = Assembly.GetExecutingAssembly().GetManifestResourceStream("Lenticulizer.BlenderAddon.zip"))
                {
                    if (input == null) throw new InvalidDataException("The application is missing its Blender add-on package.");
                    bool write = !File.Exists(destination) || new FileInfo(destination).Length != input.Length;
                    if (!write) return destination;
                    using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) input.CopyTo(output);
                }
                File.Move(temporary, destination, true);
                return destination;
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        async Task Initialize()
        {
            try
            {
                var progress = new Progress<int>(value => { if (!closing) { preparingProgress.Value = value; preparingLabel.Text = value < 100 ? "Preparing Lenticulizer... " + value + "%" : "Opening Lenticulizer..."; } });
                await Task.Run(() => BundledRuntime.Prepare(value => ((IProgress<int>)progress).Report(value), startupCancellation.Token));
                if (closing) return;
                CoreWebView2Environment.SetLoaderDllFolderPath(BundledRuntime.Root);
                string profile = Path.Combine(Program.LocalRoot, "Lenticulizer", "WebView2", "Fixed_" + BundledRuntime.Manifest.version);
                var environment = await CoreWebView2Environment.CreateAsync(BundledRuntime.BrowserFolder, profile);
                if (closing) return;
                await view.EnsureCoreWebView2Async(environment);
                if (closing) return;
                var core = view.CoreWebView2;
                core.Settings.AreDefaultContextMenusEnabled = false;
                core.Settings.AreBrowserAcceleratorKeysEnabled = false;
                core.Settings.AreHostObjectsAllowed = false;
                core.Settings.IsStatusBarEnabled = false;
                view.AllowExternalDrop = true;
                core.AddWebResourceRequestedFilter(AppResources.Filter, CoreWebView2WebResourceContext.All, CoreWebView2WebResourceRequestSourceKinds.All);
                core.WebResourceRequested += LoadResource;
                core.WebMessageReceived += Receive;
                core.NavigationCompleted += delegate(object sender, CoreWebView2NavigationCompletedEventArgs e) { if (e.IsSuccess) preparing.Visible = false; };
                if (uiReport != "") core.NavigationCompleted += async delegate(object sender, CoreWebView2NavigationCompletedEventArgs e) {
                    if (!e.IsSuccess) { FinishCheck(false, new Dictionary<string,object>{{"error", "Interface navigation failed: " + e.WebErrorStatus}}); return; }
                    try
                    {
                        using (var stream = System.Reflection.Assembly.GetExecutingAssembly().GetManifestResourceStream("Lenticulizer.WindowsUiChecks.js"))
                        using (var reader = new StreamReader(stream)) await core.ExecuteScriptAsync(reader.ReadToEnd());
                    }
                    catch (Exception error) { FinishCheck(false, new Dictionary<string,object>{{"error",error.Message}}); }
                };
                core.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) { if (!IsAppPage(e.Uri)) e.Cancel = true; };
                core.FrameNavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) { e.Cancel = true; };
                core.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e) { e.Handled = true; };
                core.DownloadStarting += delegate(object sender, CoreWebView2DownloadStartingEventArgs e) {
                    // Browser-generated labeled-test ZIPs use the normal WebView2 download UI.
                    // Navigation and new-window restrictions remain unchanged.
                    e.Handled = false;
                };
                core.ProcessFailed += delegate(object sender, CoreWebView2ProcessFailedEventArgs e) { Program.Log("Web interface failure: " + e.ProcessFailedKind); if (!closing) ShowError("The web interface stopped. Close and reopen Lenticulizer. Your project and generated files remain in the session folder."); };
                string session = Path.Combine(Program.LocalRoot, "Lenticulizer", "Sessions", "Integrated_" + DateTime.UtcNow.ToString("yyyyMMdd_HHmmss_fff") + "_" + Guid.NewGuid().ToString("N").Substring(0,6));
                Directory.CreateDirectory(session);
                string path = Path.Combine(session, "project.json");
                File.WriteAllText(path, ProjectJson.Stringify(Program.NewProject(session)), new System.Text.UTF8Encoding(false));
                addonPath = PrepareBlenderAddon();
                project = new IntegratedProject(path, Path.Combine(Program.LocalRoot, "Lenticulizer", "Working"), Path.Combine(BundledRuntime.Root, "Lenticular-Builder.blend"), Program.LocalRoot);
                project.Diagnostic += Program.Log;
                project.Updated += value => OnUi(delegate { Publish(value); });
                await Task.Run(() => project.Start());
                if (closing) return;
                core.Navigate(Origin + "/src/index.html");
                Program.Log("Integrated application started. Core and window PID " + Process.GetCurrentProcess().Id);
                if (uiReport != "") { await Task.Delay(90000); if (!checkFinished && !closing) FinishCheck(false,new Dictionary<string,object>{{"error","Windows interface check timed out."}}); }
            }
            catch (WebView2RuntimeNotFoundException)
            {
                if (uiReport != "") { FinishCheck(false,new Dictionary<string,object>{{"error","The bundled WebView2 Runtime could not be loaded."}}); return; }
                if (!closing) ShowError("The bundled browser runtime could not be loaded. Close Lenticulizer and reopen it. If this persists, run the included runtime verification command. A system-wide WebView2 installation is not required.");
                Close();
            }
            catch (Exception error) { Program.Log(error.ToString()); if (!closing) { if (uiReport != "") FinishCheck(false,new Dictionary<string,object>{{"error",error.Message}}); else { ShowError(error.Message); Close(); } } }
        }
        static bool IsAppPage(string value)
        {
            Uri uri;
            return Uri.TryCreate(value, UriKind.Absolute, out uri) && uri.Scheme == "https" && uri.Host == "lenticulizer.app" && uri.Port == 443 && uri.AbsolutePath == "/src/index.html";
        }
        void OnUi(Action action)
        {
            if (closing || IsDisposed || !IsHandleCreated) return;
            try { BeginInvoke(new Action(delegate { if (!closing && !IsDisposed) action(); })); }
            catch (InvalidOperationException) { }
        }
        void ShowError(string message) { MessageBox.Show(this, message, "Lenticulizer", MessageBoxButtons.OK, MessageBoxIcon.Error); }
        void Send(object message)
        {
            if (!closing && !IsDisposed && view.CoreWebView2 != null) view.CoreWebView2.PostWebMessageAsJson(ProjectJson.Stringify(message));
        }
        void Publish(Dictionary<string, object> value)
        {
            if (ProjectJson.Text(value, "active_project_path", "") != project.ProjectPath) return;
            if (value.ContainsKey("project_switched")) pendingBlender.Clear();
            var result = ProjectJson.Object(value, "command_result");
            string id = ProjectJson.Text(result, "id", ""); string[] launch;
            if (pendingBlender.TryGetValue(id, out launch))
            {
                pendingBlender.Remove(id);
                if (ProjectJson.Text(result, "status", "") == "ready" && launch[1] == project.ProjectPath)
                {
                    try { DesktopFiles.LaunchBlender(launch[0], ProjectJson.Text(result, "path", ""), launch[1], project.HandoffDirectories()); }
                    catch (Exception error) { Program.Log(error.ToString()); ShowError("Could not open Blender: " + error.Message); }
                }
            }
            if (ready) Send(new { @event = "project-updated", data = value });
        }
        async void Receive(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            int id = 0;
            try
            {
                if (closing || !IsAppPage(e.Source)) return;
                var message = ProjectJson.Parse(e.WebMessageAsJson);
                id = (int)ProjectJson.Number(message, "id", 0);
                string method = ProjectJson.Text(message, "method", "");
                string expected = ProjectJson.Text(message, "projectPath", project.ProjectPath);
                var args = ProjectJson.Object(message, "args");
                if (uiReport != "" && method == "ui-check:result") { FinishCheck(args.ContainsKey("ok") && object.Equals(args["ok"],true),args); return; }
                if (uiReport != "" && method == "ui-check:fixtures")
                {
                    var paths = new List<string>();
                    for (int i = 0; i < 3; i++)
                    {
                        string path = Path.Combine(project.SessionDirectory,"check source # & + % ' \u00e9-"+i+".png");
                        using (var bitmap = new Bitmap(32+i,24+i)) { using (var graphics = Graphics.FromImage(bitmap)) graphics.Clear(i==0?Color.Red:i==1?Color.Yellow:Color.Blue); bitmap.Save(path,System.Drawing.Imaging.ImageFormat.Png); }
                        paths.Add(path); project.ImageInfo(path);
                    }
                    Send(new { id, result = paths.ToArray() }); return;
                }
                string[] dropped = null;
                if (method == "images:dropped" || method == "files:import") dropped = e.AdditionalObjects.OfType<CoreWebView2File>().Select(file => file.Path).ToArray();
                bool trackOperation = method != "bootstrap" && method != "processing:status" && !method.StartsWith("update:", StringComparison.Ordinal);
                if (trackOperation) Interlocked.Increment(ref activeOperations);
                object result;
                try { result = await Dispatch(method, args, expected, dropped); }
                finally { if (trackOperation) Interlocked.Decrement(ref activeOperations); }
                Send(new { id, result });
                if (method == "bootstrap" && !closing) Publish(await Task.Run(() => project.Read()));
                if (method == "update:install" && restartForUpdate && !closing) BeginInvoke(new Action(delegate { Close(); }));
            }
            catch (Exception error) { Program.Log(error.ToString()); Send(new { id, error = error.Message }); }
        }
        async Task<object> Dispatch(string method, Dictionary<string, object> args, string expected, string[] dropped)
        {
            if (method == "bootstrap")
            {
                var value = await Task.Run(() => project.Read()); ready = true;
                UpdateInstaller.ReportHealthy(updateHealthToken);
                _ = Task.Run(async delegate
                {
                    await Task.Delay(5000).ConfigureAwait(false);
                    UpdateInstaller.CleanupCompletedUpdateArtifacts();
                });
                if (rollbackNotice && !rollbackNoticeShown)
                {
                    rollbackNoticeShown = true;
                    BeginInvoke(new Action(delegate { MessageBox.Show(this, "The last update did not start successfully, so Lenticulizer restored the previous working version.", "Update rolled back", MessageBoxButtons.OK, MessageBoxIcon.Warning); }));
                }
                return new { version = Program.Version, sessionDir = project.SessionDirectory, projectPath = project.ProjectPath, project = value, uiTesting = uiReport != "", backendExists = true, integrated = true, blenderAddon = addonPath, blenderAddonExists = File.Exists(addonPath), update = updater.CurrentStatus };
            }
            if (method == "processing:status") return new { ok = true, running = !closing, integrated = true };
            if (method == "update:status") return updater.CurrentStatus;
            if (method == "update:check") return await updater.CheckAsync(true, startupCancellation.Token);
            if (method == "update:download") return await updater.DownloadAsync(startupCancellation.Token);
            if (method == "update:open-release")
            {
                var update = updater.CurrentStatus;
                string url = ProjectJson.Text(update, "readMoreUrl", "");
                if (url == "") url = ProjectJson.Text(update, "releaseUrl", "");
                OpenTrustedUpdateUrl(url);
                return true;
            }
            if (method == "update:install")
            {
                if (BusyForRestart()) throw new InvalidOperationException("Finish the current build, file dialog, or Blender action before restarting for an update.");
                if (MessageBox.Show(this, "Save any external work, then install the verified update and restart Lenticulizer?", "Install update", MessageBoxButtons.OKCancel, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.OK) return new { ok = false, canceled = true };
                var plan = updater.PrepareInstall();
                UpdateInstaller.Begin(plan);
                restartForUpdate = true;
                return new { ok = true, installing = true, version = plan.Version };
            }
            if (method == "runtime:notices")
            {
                using (var process = Process.Start(new ProcessStartInfo(BundledRuntime.NoticesPath) { UseShellExecute = true })) { }
                return true;
            }
            if (method == "project:read") return await Task.Run(() => project.Read());
            if (method == "settings:solve") return await Task.Run(() => project.Solve(ProjectJson.Object(args, "patch"), expected));
            if (method == "images:dropped")
            {
                CheckProject(expected);
                return (dropped ?? new string[0]).Where(ProjectJson.SupportedImage).Take(8).Select(project.ImageInfo).ToArray();
            }
            string priority = ProjectJson.Text(args, "priority", "settings");
            bool command = new[] { "analyze", "calibration", "blender-sync", "blender-open", "blender-reset", "blender-export" }.Contains(priority);
            if (method == "project:patch" && !command)
            {
                pendingBlender.Clear();
                return await ApplyPatch(ProjectJson.Object(args, "patch"), priority, expected);
            }
            // Serialize file imports with OS dialogs; analysis runs off the UI thread.
            await dialogs.WaitAsync();
            try
            {
                if (closing) throw new InvalidOperationException("The application is closing.");
                CheckProject(expected);
                if (method == "project:patch") return await Command(args, priority, expected);
                if (method == "files:import") return await ImportDroppedFiles(dropped, ProjectJson.Text(args, "target", "auto"), expected);
                if (method == "heightmap:import" || method == "heightmap:analyze")
                {
                    var before = await Task.Run(() => project.Read());
                    string original = ProjectJson.Text(ProjectJson.Object(before, "assets"), "reference_heightmap", "");
                    string path = original;
                    if (method == "heightmap:import")
                    {
                        using (var dialog = new OpenFileDialog { Title = "Import lens heightmap", Filter = "Grayscale heightmaps|*.png;*.tif;*.tiff", CheckFileExists = true })
                        { if (dialog.ShowDialog(this) != DialogResult.OK) return null; path = dialog.FileName; }
                    }
                    if (string.IsNullOrEmpty(path)) throw new InvalidOperationException("Import a heightmap first.");
                    var info = await Task.Run(() => HeightmapEngine.Analyze(path));
                    CheckProject(expected);
                    var current = await Task.Run(() => project.Read());
                    if (ProjectJson.Text(ProjectJson.Object(current, "assets"), "reference_heightmap", "") != original)
                        throw new InvalidOperationException("The reference heightmap changed during analysis. Repeat the action for the current map.");
                    var settings = ProjectJson.Object(current, "settings");
                    var patch = DroppedImageImport.HeightmapPatch(current, path, info, method == "heightmap:import");
                    return await ApplyPatch(patch, ProjectJson.Text(settings,"workflow","")=="Build from heightmap" ? "rebuild-pair" : "reference", expected);
                }
                if (method == "images:add" || method == "images:import")
                {
                    string[] paths;
                    using (var dialog = new OpenFileDialog { Title = method == "images:add" ? "Add source images" : "Import existing interlaced image", Filter = ImagesFilter, Multiselect = method == "images:add", CheckFileExists = true })
                    { if (dialog.ShowDialog(this) != DialogResult.OK) return method == "images:add" ? (object)new object[0] : null; paths = dialog.FileNames; }
                    CheckProject(expected);
                    var items = paths.Select(project.ImageInfo).ToArray();
                    if (method == "images:add") return items;
                    var patch = new Dictionary<string, object> { {"assets", new Dictionary<string,object> { {"interlaced_image", paths[0]}, {"heightmap", ""} }}, {"settings", new Dictionary<string,object> { {"workflow", "Use existing interlaced image"} }} };
                    await ApplyPatch(patch, "rebuild-heightmap", expected);
                    return items[0];
                }
                if (method == "path:show" || method == "path:open")
                {
                    string path = ProjectJson.Text(args, "path", "");
                    if (!File.Exists(path) && !Directory.Exists(path)) throw new FileNotFoundException("This file or folder is not available.");
                    if (method == "path:show") using (var process = Process.Start(new ProcessStartInfo("explorer.exe", "/select," + DesktopFiles.Quote(path)) { UseShellExecute = false })) { }
                    else using (var process = Process.Start(new ProcessStartInfo(path) { UseShellExecute = true })) { }
                    return true;
                }
                if (method == "asset:export" || method == "asset:export-both") return await Export(method == "asset:export-both", ProjectJson.Text(args, "kind", "interlaced"), expected);
                throw new ArgumentException("Unknown application action: " + method);
            }
            finally { dialogs.Release(); }
        }
        async Task<object> ImportDroppedFiles(string[] dropped, string target, string expected)
        {
            var before = await Task.Run(() => project.Read());
            string original = ProjectJson.Text(ProjectJson.Object(before, "assets"), "reference_heightmap", "");
            var plan = await Task.Run(() => DroppedImageImport.Analyze(dropped, target));
            CheckProject(expected);
            await commits.WaitAsync();
            try
            {
                if (closing) throw new InvalidOperationException("The application is closing.");
                return await Task.Run(() =>
                {
                    CheckProject(expected);
                    var current = project.Read();
                    if (plan.HeightmapPath != "" && ProjectJson.Text(ProjectJson.Object(current, "assets"), "reference_heightmap", "") != original)
                        throw new InvalidOperationException("The reference heightmap changed during import. Drop the map again for the current project.");
                    var update = DroppedImageImport.BuildUpdate(plan, current);
                    var next = update.HasChanges ? project.Patch(update.Patch, update.Priority, expected) : current;
                    return new { project = next, heightmapImported = update.HeightmapImported, sourcesAdded = update.SourcesAdded, sourcesSkipped = update.SourcesSkipped, message = update.Message };
                });
            }
            finally { commits.Release(); }
        }
        static void OpenTrustedUpdateUrl(string value)
        {
            if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps || !string.Equals(uri.Host, "github.com", StringComparison.OrdinalIgnoreCase) || !uri.AbsolutePath.StartsWith("/TechSavage1989/Lenticulizer/", StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("The release-notes link is not an authorized Lenticulizer GitHub URL.");
            using (var process = Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute = true })) { }
        }
        bool BusyForRestart()
        {
            if (Volatile.Read(ref activeOperations) > 0 || dialogs.CurrentCount == 0 || commits.CurrentCount == 0 || pendingBlender.Count > 0) return true;
            try
            {
                if (project != null)
                {
                    var current = project.Read();
                    string generation = ProjectJson.Text(ProjectJson.Object(current, "generation"), "status", "");
                    if (generation == "queued" || generation == "running" || generation == "building") return true;
                }
            }
            catch { return true; }
            return false;
        }
        void CheckProject(string expected)
        {
            if (!string.IsNullOrEmpty(expected) && expected != project.ProjectPath) throw new InvalidOperationException("The active project changed. Repeat this action in the current project.");
        }
        string Folder(string title)
        {
            using (var dialog = new FolderBrowserDialog { Description = title, ShowNewFolderButton = true })
                return dialog.ShowDialog(this) == DialogResult.OK ? dialog.SelectedPath : "";
        }
        async Task<object> Command(Dictionary<string, object> args, string priority, string expected)
        {
            string destination = "", exe = "";
            bool canceled = false;
            if (priority == "blender-reset") canceled = MessageBox.Show(this, "Replace this project's Blender scene with the current baseline? Project settings and generated images are retained.", "Reset project Blender scene", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning, MessageBoxDefaultButton.Button2) != DialogResult.OK;
            if (!canceled && (priority == "blender-open" || priority == "blender-reset"))
            {
                exe = DesktopFiles.DiscoverBlender();
                if (exe == "") using (var dialog = new OpenFileDialog { Title = "Locate Blender", Filter = "Blender executable|blender.exe", CheckFileExists = true })
                { if (dialog.ShowDialog(this) == DialogResult.OK) exe = dialog.FileName; else canceled = true; }
            }
            if (priority == "calibration") { destination = Folder("Export calibration coupons"); canceled = destination == ""; }
            if (priority == "blender-export") using (var dialog = new SaveFileDialog { Title = "Export portable Blender package", FileName = "Lenticulizer_3D_Blender_Package.zip", Filter = "ZIP archive|*.zip", DefaultExt = "zip", AddExtension = true, OverwritePrompt = true })
            { if (dialog.ShowDialog(this) == DialogResult.OK) destination = dialog.FileName; else canceled = true; }
            if (canceled) { var result = await Task.Run(() => project.Read()); result["command_canceled"] = true; return result; }
            CheckProject(expected);
            var request = new Dictionary<string, object> { {"id", Guid.NewGuid().ToString("N")}, {"kind", priority} };
            if (destination != "") request["destination"] = destination;
            var patch = ProjectJson.Object(args, "patch"); patch["command_request"] = request;
            pendingBlender.Clear();
            if (exe != "") pendingBlender[(string)request["id"]] = new[] { exe, project.ProjectPath };
            try { return await ApplyPatch(patch, priority, expected); }
            catch { pendingBlender.Remove((string)request["id"]); throw; }
        }
        async Task<object> Export(bool both, string kind, string expected)
        {
            var snapshot = await Task.Run(() => project.Read());
            string[] sources = both ? DesktopFiles.Pair(snapshot) : new[] { DesktopFiles.Asset(snapshot, kind) };
            string folder = ""; string[] destinations;
            if (both)
            {
                folder = Folder("Export interlaced image and matching heightmap");
                if (folder == "") return new { ok = false, canceled = true };
                destinations = sources.Select(path => Path.Combine(folder, Path.GetFileName(path))).ToArray();
                if (string.Equals(destinations[0], destinations[1], StringComparison.OrdinalIgnoreCase)) destinations[1] = Path.Combine(folder, "Heightmap_" + Path.GetFileName(sources[1]));
                if (destinations.Where((path, i) => File.Exists(path) && !string.Equals(path, sources[i], StringComparison.OrdinalIgnoreCase)).Any() && MessageBox.Show(this, "Replace the existing output files in this folder?", "Export both", MessageBoxButtons.OKCancel, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.OK) return new { ok = false, canceled = true };
            }
            else using (var dialog = new SaveFileDialog { Title = kind == "heightmap" ? "Export 16-bit heightmap / depth map" : "Export interlaced image", FileName = Path.GetFileName(sources[0]), Filter = "Image|*" + Path.GetExtension(sources[0]), AddExtension = true, DefaultExt = Path.GetExtension(sources[0]).TrimStart('.'), OverwritePrompt = true })
            { if (dialog.ShowDialog(this) != DialogResult.OK) return new { ok = false, canceled = true }; destinations = new[] { dialog.FileName }; }
            CheckProject(expected);
            await Task.Run(() => DesktopFiles.Export(sources, destinations));
            return new { ok = true, path = destinations[0], folder, paths = destinations };
        }
        async Task<Dictionary<string,object>> ApplyPatch(Dictionary<string,object> patch, string priority, string expected)
        {
            // Acquire on the UI thread before dispatching work, preserving the
            // order of received commits even when thread-pool scheduling differs.
            await commits.WaitAsync();
            try
            {
                if (closing) throw new InvalidOperationException("The application is closing.");
                return await Task.Run(() => project.Patch(patch, priority, expected));
            }
            finally { commits.Release(); }
        }
        async void LoadResource(object sender, CoreWebView2WebResourceRequestedEventArgs e)
        {
            var deferral = e.GetDeferral();
            try
            {
                string address = e.Request.Uri, method = e.Request.Method;
                bool isImage = new Uri(address).AbsolutePath == "/local-image";
                if (isImage) imageRequests++;
                // File reads, TIFF decoding, and embedded-resource reads run away
                // from the UI thread; WebView2 response creation stays on it.
                var resource = await Task.Run(() => AppResources.Read(address, method, path => project.ReadImage(path)));
                if (closing) return;
                e.Response = view.CoreWebView2.Environment.CreateWebResourceResponse(new MemoryStream(resource.Bytes, false), resource.Status, resource.Reason, resource.Headers);
                if (isImage && resource.Status == 200) imageResponses++;
            }
            catch (Exception error)
            {
                Program.Log("Interface resource: " + error.Message);
                if (uiReport != "") resourceErrors.Add(error.Message);
                if (!closing)
                {
                    var resource = error is UnauthorizedAccessException ? AppResources.Error(403, "Forbidden")
                        : error is FileNotFoundException || error is DirectoryNotFoundException ? AppResources.Error(404, "Not Found")
                        : AppResources.Error(500, "Internal Server Error");
                    e.Response = view.CoreWebView2.Environment.CreateWebResourceResponse(new MemoryStream(resource.Bytes, false), resource.Status, resource.Reason, resource.Headers);
                }
            }
            finally { deferral.Complete(); }
        }
        async void CloseApplication(object sender, FormClosingEventArgs e)
        {
            if (closed) return;
            e.Cancel = true;
            if (closing) return;
            if (uiReport != "" && !checkFinished) { checkFinished = true; ExitCode = 1; File.WriteAllText(uiReport,"{\"ok\":false,\"error\":\"The interface check was closed before completion.\"}"); }
            closing = true; ready = false; Text = restartForUpdate ? "Installing update..." : "Closing Lenticulizer..."; Enabled = false;
            AppPreferences.SaveWindow(this);
            updateTimer.Stop();
            startupCancellation.Cancel();
            if (project != null) await Task.Run(delegate { project.Dispose(); if (!project.WaitForStop(5000)) Program.Log("Shutdown reached the worker cancellation timeout."); });
            updater.Dispose();
            view.Dispose(); closed = true; Close();
        }
        void FinishCheck(bool ok, Dictionary<string,object> report)
        {
            if (checkFinished || closing) return;
            checkFinished = true; ExitCode = ok ? 0 : 1;
            report["ok"] = ok; report["version"] = Program.Version; report["runtime"] = view.CoreWebView2 == null ? "unavailable" : view.CoreWebView2.Environment.BrowserVersionString;
            report["process_id"] = Process.GetCurrentProcess().Id;
            report["image_requests"] = imageRequests; report["image_responses"] = imageResponses;
            report["resource_errors"] = resourceErrors.ToArray();
            report["dotnet_runtime"] = Environment.Version.ToString(); report["bundled_browser"] = BundledRuntime.Manifest == null ? "unavailable" : BundledRuntime.Manifest.version;
            File.WriteAllText(uiReport,ProjectJson.Stringify(report));
            Close();
        }
    }
}
