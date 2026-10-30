using System;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Threading;

namespace Lenticulizer.Desktop
{
    internal static class UpdateInstaller
    {
        static string UpdateRoot => Path.Combine(Program.LocalRoot, "Lenticulizer", "Updates");
        static string RollbackRoot => Path.Combine(UpdateRoot, "Rollback");
        static string HealthRoot => Path.Combine(UpdateRoot, "Health");
        static string HelperRoot => Path.Combine(UpdateRoot, "Helper");

        internal static string Begin(UpdateInstallPlan plan)
        {
            if (plan == null || !File.Exists(plan.StagedExe)) throw new FileNotFoundException("The staged update executable is missing.");
            string target = Environment.ProcessPath ?? throw new InvalidOperationException("The current executable path is unavailable.");
            EnsureNoOtherRunningTarget(target);
            Directory.CreateDirectory(HelperRoot);
            string token = Guid.NewGuid().ToString("N");
            string helper = Path.Combine(HelperRoot, "LenticulizerUpdateHelper-" + token + ".exe");
            File.Copy(target, helper, true);
            string args = "--apply-update " + Quote(target) + " " + Quote(plan.StagedExe) + " " + Quote(plan.Version) + " " + Process.GetCurrentProcess().Id + " " + Quote(token) + " " + Quote(plan.PackagePath);
            Process.Start(new ProcessStartInfo(helper, args) { UseShellExecute = false, CreateNoWindow = true, WorkingDirectory = Path.GetDirectoryName(helper) ?? HelperRoot });
            return token;
        }

        static void EnsureNoOtherRunningTarget(string target)
        {
            string expected = Path.GetFullPath(target);
            string processName = Path.GetFileNameWithoutExtension(expected);
            foreach (var process in Process.GetProcessesByName(processName))
            {
                using (process)
                {
                    if (process.Id == Process.GetCurrentProcess().Id) continue;
                    try
                    {
                        string other = process.MainModule?.FileName ?? "";
                        if (other != "" && string.Equals(Path.GetFullPath(other), expected, StringComparison.OrdinalIgnoreCase))
                            throw new InvalidOperationException("Close the other Lenticulizer window before installing the update.");
                    }
                    catch (InvalidOperationException) { throw; }
                    catch { }
                }
            }
        }

        internal static int RunHelper(string[] args)
        {
            string target = "", staged = "", version = "", token = "", packagePath = "";
            string backup = "", targetDirectory = "", sameVolumeStage = "";
            bool backupCreated = false;
            try
            {
                if (args.Length < 7) throw new ArgumentException("Incomplete update-helper arguments.");
                target = Path.GetFullPath(args[1]);
                staged = Path.GetFullPath(args[2]);
                version = args[3];
                if (!int.TryParse(args[4], out int parentPid)) throw new ArgumentException("Invalid parent process id.");
                token = args[5];
                packagePath = Path.GetFullPath(args[6]);
                WaitForExit(parentPid, 60000);
                Directory.CreateDirectory(RollbackRoot);
                Directory.CreateDirectory(HealthRoot);
                backup = Path.Combine(RollbackRoot, "Lenticulizer.previous.exe");
                string metadata = Path.Combine(RollbackRoot, "previous.json");
                string health = HealthPath(token);
                TryDelete(health);
                if (!File.Exists(target)) throw new FileNotFoundException("The installed Lenticulizer executable is missing.", target);
                File.Copy(target, backup, true);
                backupCreated = true;
                File.WriteAllText(metadata, JsonSerializer.Serialize(new { target, previousVersion = FileVersionInfo.GetVersionInfo(target).ProductVersion ?? "", replacementVersion = version, savedUtc = DateTimeOffset.UtcNow.ToString("o") }));

                targetDirectory = Path.GetDirectoryName(target) ?? throw new InvalidOperationException("The installed executable directory is unavailable.");
                sameVolumeStage = Path.Combine(targetDirectory, ".Lenticulizer.update-" + Guid.NewGuid().ToString("N") + ".exe");
                File.Copy(staged, sameVolumeStage, true);
                File.Move(sameVolumeStage, target, true);
                sameVolumeStage = "";

                using var launched = Process.Start(new ProcessStartInfo(target, "--update-health " + Quote(token)) { UseShellExecute = true, WorkingDirectory = targetDirectory });
                if (launched == null) throw new InvalidOperationException("The updated application could not be started.");
                if (WaitForHealth(health, launched, 75000))
                {
                    CleanupStaging(staged);
                    TryDelete(packagePath);
                    return 0;
                }

                try { if (!launched.HasExited) { launched.Kill(true); launched.WaitForExit(10000); } } catch { }
                RestoreAndRelaunch(target, backup, targetDirectory);
                CleanupStaging(staged);
                TryDelete(packagePath);
                return 2;
            }
            catch (Exception error)
            {
                string restoreError = "";
                TryDelete(sameVolumeStage);
                if (backupCreated && target != "" && backup != "" && File.Exists(backup))
                {
                    try
                    {
                        if (targetDirectory == "") targetDirectory = Path.GetDirectoryName(target) ?? "";
                        RestoreAndRelaunch(target, backup, targetDirectory);
                    }
                    catch (Exception rollbackError) { restoreError = Environment.NewLine + "Rollback failed: " + rollbackError; }
                }
                CleanupStaging(staged);
                TryDelete(packagePath);
                try
                {
                    Directory.CreateDirectory(UpdateRoot);
                    File.WriteAllText(Path.Combine(UpdateRoot, "LastInstallError.txt"), DateTimeOffset.UtcNow.ToString("o") + Environment.NewLine + error + restoreError);
                }
                catch { }
                return 1;
            }
        }

        static void RestoreAndRelaunch(string target, string backup, string targetDirectory)
        {
            File.Copy(backup, target, true);
            var restored = Process.Start(new ProcessStartInfo(target, "--update-rollback-notice") { UseShellExecute = true, WorkingDirectory = targetDirectory });
            if (restored == null) throw new InvalidOperationException("The previous Lenticulizer version was restored but could not be relaunched.");
        }

        internal static void ReportHealthy(string token)
        {
            if (string.IsNullOrWhiteSpace(token)) return;
            try
            {
                Directory.CreateDirectory(HealthRoot);
                File.WriteAllText(HealthPath(token), JsonSerializer.Serialize(new { ok = true, version = Program.Version, pid = Process.GetCurrentProcess().Id, utc = DateTimeOffset.UtcNow.ToString("o") }));
            }
            catch (Exception error) { Program.Log("Update health marker: " + error.Message); }
        }

        internal static void CleanupCompletedUpdateArtifacts()
        {
            try
            {
                if (Directory.Exists(HelperRoot))
                    foreach (string helper in Directory.GetFiles(HelperRoot, "LenticulizerUpdateHelper-*.exe"))
                        if (!string.Equals(Path.GetFullPath(helper), Environment.ProcessPath, StringComparison.OrdinalIgnoreCase)) TryDelete(helper);
                if (Directory.Exists(HealthRoot))
                    foreach (string file in Directory.GetFiles(HealthRoot)) if (File.GetLastWriteTimeUtc(file) < DateTime.UtcNow.AddDays(-2)) TryDelete(file);
                string staging = Path.Combine(UpdateRoot, "Staging");
                if (Directory.Exists(staging))
                    foreach (string dir in Directory.GetDirectories(staging)) if (Directory.GetLastWriteTimeUtc(dir) < DateTime.UtcNow.AddDays(-2)) TryDeleteDirectory(dir);
            }
            catch { }
        }

        static bool WaitForHealth(string health, Process process, int timeoutMs)
        {
            var deadline = Environment.TickCount64 + timeoutMs;
            while (Environment.TickCount64 < deadline)
            {
                if (File.Exists(health)) return true;
                try { if (process.HasExited) return false; } catch { return false; }
                Thread.Sleep(250);
            }
            return File.Exists(health);
        }

        static void WaitForExit(int pid, int timeoutMs)
        {
            try { using var process = Process.GetProcessById(pid); process.WaitForExit(timeoutMs); if (!process.HasExited) throw new TimeoutException("The previous Lenticulizer process did not exit in time."); }
            catch (ArgumentException) { }
        }

        static void CleanupStaging(string staged)
        {
            try { var dir = Path.GetDirectoryName(staged); if (!string.IsNullOrEmpty(dir) && Directory.Exists(dir)) Directory.Delete(dir, true); } catch { }
        }
        static string HealthPath(string token) => Path.Combine(HealthRoot, "health-" + token + ".json");
        static string Quote(string value) => "\"" + value.Replace("\"", "\\\"") + "\"";
        static void TryDelete(string path) { try { if (File.Exists(path)) File.Delete(path); } catch { } }
        static void TryDeleteDirectory(string path) { try { if (Directory.Exists(path)) Directory.Delete(path, true); } catch { } }
    }
}
