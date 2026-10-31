using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Windows.Forms;
using Lenticulizer.Core;

[assembly: AssemblyTitle("Lenticulizer")]
[assembly: AssemblyProduct("Lenticulizer")]
[assembly: AssemblyInformationalVersion("3.0.0-alpha.33")]
[assembly: AssemblyVersion("3.0.0.33")]
[assembly: AssemblyFileVersion("3.0.0.33")]
[assembly: System.Runtime.Versioning.SupportedOSPlatform("windows10.0.17763")]
[assembly: System.Runtime.CompilerServices.InternalsVisibleTo("IntegratedAppTests")]
[assembly: System.Runtime.CompilerServices.InternalsVisibleTo("RuntimeTests")]

namespace Lenticulizer.Desktop
{
    internal static class Program
    {
        public const string Version = "3.0.0-alpha.33";
        public static readonly string LocalRoot = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        public static readonly string Root = AppDomain.CurrentDomain.BaseDirectory;
        public static void Log(string message)
        {
            try
            {
                string directory = Path.Combine(LocalRoot, "Lenticulizer", "Logs");
                Directory.CreateDirectory(directory);
                File.AppendAllText(Path.Combine(directory, "integrated-app.log"), DateTime.UtcNow.ToString("o") + " " + message + Environment.NewLine);
            }
            catch { }
        }
        public static Dictionary<string, object> NewProject(string directory)
        {
            using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("Lenticulizer.DefaultProject.json"))
            using (var reader = new StreamReader(stream))
            {
                var value = ProjectJson.Parse(reader.ReadToEnd());
                value["changed_by"] = "integrated"; value["changed_utc_ticks"] = DateTime.UtcNow.Ticks;
                value["project_name"] = Path.GetFileName(directory); value["project_dir"] = directory;
                value["requested_change"] = new Dictionary<string, object> { {"priority", "startup"}, {"scope", "geometry"} };
                return value;
            }
        }
        [STAThread]
        static int Main(string[] args)
        {
            HeightmapEngine.OtherImageReader = WindowsHeightmapReader.Read;
            if (args.Length > 0 && args[0] == "--apply-update") return UpdateInstaller.RunHelper(args);
            if (args.Length > 0 && args[0] == "--package-release") return ReleasePackager.Build(args.Length > 1 ? args[1] : Path.Combine(Root, "release"));
            if (args.Length > 0 && args[0] == "--verify-core") return VerifyEmbeddedCore(args.Length > 1 ? args[1] : "");
            if (args.Length > 0 && args[0] == "--verify-runtime") return VerifyRuntime(args.Length > 1 ? args[1] : "");
            if (args.Length > 0 && args[0] == "--export-runtime")
            {
                try
                {
                    if (args.Length != 2) throw new ArgumentException("Supply the build assets destination after --export-runtime.");
                    BundledRuntime.ExportForBuild(args[1]); return 0;
                }
                catch (Exception error) { Console.Error.WriteLine(error); return 1; }
            }
            string reportDirectory = Path.Combine(LocalRoot, "Lenticulizer", "Logs"); Directory.CreateDirectory(reportDirectory);
            string uiReport = args.Length > 0 && args[0] == "--verify-ui" ? (args.Length > 1 ? Path.GetFullPath(args[1]) : Path.Combine(reportDirectory,"Windows_UI_Check.json")) : "";
            string updateHealthToken = args.Length > 1 && args[0] == "--update-health" ? args[1] : "";
            bool rollbackNotice = args.Length > 0 && args[0] == "--update-rollback-notice";
            try { return RunApplication(uiReport, updateHealthToken, rollbackNotice); }
            catch (Exception error)
            {
                Log(error.ToString());
                MessageBox.Show(error.Message, "Lenticulizer could not start", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
        // Keep verification independent of loading any Windows/WebView2 controls.
        [System.Runtime.CompilerServices.MethodImpl(System.Runtime.CompilerServices.MethodImplOptions.NoInlining)]
        static int RunApplication(string uiReport, string updateHealthToken, bool rollbackNotice)
        {
            Application.SetUnhandledExceptionMode(UnhandledExceptionMode.ThrowException);
            Application.SetHighDpiMode(HighDpiMode.PerMonitorV2);
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            if (Thread.CurrentThread.GetApartmentState() != ApartmentState.STA) throw new InvalidOperationException("The application must start on an STA thread.");
            using (var window = new AppWindow(uiReport, updateHealthToken, rollbackNotice)) { Application.Run(window); return window.ExitCode; }
        }
        static int VerifyEmbeddedCore(string report)
        {
            try
            {
                Assembly app = Assembly.GetExecutingAssembly();
                foreach (Type type in new[] { typeof(ProjectSession), typeof(OpticalEngine), typeof(ProductionEngine), typeof(RasterEngine), typeof(PngCodec) })
                    if (type.Assembly != app) throw new InvalidOperationException(type.Name + " is not embedded in the application executable.");
                foreach (AssemblyName dependency in app.GetReferencedAssemblies())
                    if (dependency.Name == "Lenticulizer.Core" || dependency.Name == "mscorlib" || dependency.Name == "System.Web.Extensions")
                        throw new InvalidOperationException("Unexpected legacy dependency: " + dependency.Name);
                var queue = new Queue<int>(); queue.Enqueue(22);
                if (queue.Dequeue() != 22) throw new InvalidOperationException("Collection runtime check failed.");
                foreach (string resource in new[] { "src/index.html", "src/bridge.js", "src/app.css", "src/renderer.js", "src/test-output.js", "assets/Lenticulizer.ico", "assets/Lenticulizer_Icon_Source.svg" })
                    if (AppResources.Read(AppResources.Origin + "/" + resource, "GET", null).Bytes.Length == 0) throw new InvalidOperationException("The embedded interface is incomplete: " + resource);
                string directory = Path.Combine(Path.GetTempPath(), "Lenticulizer-embedded-" + Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(directory);
                try
                {
                    var value = NewProject(directory);
                    var state = SettingsRules.Read(ProjectJson.Stringify(value), Path.Combine(directory, "project.json"), null, false);
                    if (ProjectJson.Object(ProjectJson.Parse(ProjectSerializer.Solve(state)), "settings").Count < 20) throw new InvalidOperationException("The embedded optical solve failed.");
                    // Exercise the same production PNG codec from this executable.
                    string png = Path.Combine(directory, "map.png");
                    PngCodec.WriteGray16Png(png, 4, 3, new ushort[] { 0, 16384, 32768, 65535 }, true, true, 56693, 56693);
                    byte[] bytes = File.ReadAllBytes(png);
                    if (bytes.Length < 26 || bytes[24] != 16 || bytes[25] != 0) throw new InvalidOperationException("The embedded 16-bit grayscale PNG check failed.");
                }
                finally { Directory.Delete(directory, true); }
                string message = "PASS: processing types, optical solve and 16-bit PNG generation run inside Lenticulizer.exe. No external core assembly or core process is used. PID " + Process.GetCurrentProcess().Id;
                if (!string.IsNullOrEmpty(report)) File.WriteAllText(report, message + Environment.NewLine);
                Console.WriteLine(message); return 0;
            }
            catch (Exception error)
            {
                if (!string.IsNullOrEmpty(report)) File.WriteAllText(report, error.ToString());
                Console.Error.WriteLine(error); return 1;
            }
        }
        static int VerifyRuntime(string report)
        {
            try
            {
                BundledRuntime.Prepare(null, CancellationToken.None, true);
                var value = new Dictionary<string,object>
                {
                    {"ok",true}, {"app_version",Version}, {"dotnet_runtime",Environment.Version.ToString()},
                    {"webview2_runtime",BundledRuntime.Manifest.version}, {"runtime_cache",BundledRuntime.Root},
                    {"verified_files",BundledRuntime.Manifest.files.Count}, {"process_id",Environment.ProcessId}
                };
                string result = ProjectJson.Stringify(value);
                if (report != "") File.WriteAllText(report, result); Console.WriteLine(result); return 0;
            }
            catch (Exception error)
            {
                if (report != "") File.WriteAllText(report,error.ToString()); Console.Error.WriteLine(error); return 1;
            }
        }
    }
}
