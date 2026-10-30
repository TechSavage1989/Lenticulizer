using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text.Json;
using System.Threading;

namespace Lenticulizer.Desktop
{
    internal sealed class RuntimeFile
    {
        public string path { get; set; }
        public long size { get; set; }
        public string sha256 { get; set; }
    }
    internal sealed class RuntimeManifest
    {
        public string version { get; set; }
        public string archive_sha256 { get; set; }
        public long archive_bytes { get; set; }
        public long unpacked_bytes { get; set; }
        public List<RuntimeFile> files { get; set; }
    }

    // Only the application's immutable runtime is cached here. Projects, source
    // images, output and the browser profile are stored separately.
    internal static class BundledRuntime
    {
        public static string Root { get; private set; }
        public static RuntimeManifest Manifest { get; private set; }
        public static string BrowserFolder { get { return Path.Combine(Root, "browser"); } }
        public static string NoticesPath { get { return Path.Combine(Root, "notices", "Runtime-Notices.txt"); } }

        static Stream Resource(string name)
        {
            return Assembly.GetExecutingAssembly().GetManifestResourceStream(name)
                ?? throw new InvalidDataException("The application is missing its bundled runtime.");
        }
        public static void Prepare(Action<int> progress, CancellationToken cancellation, bool verifyAll = false)
        {
            using (var input = Resource("Lenticulizer.FixedRuntime.json"))
                Manifest = JsonSerializer.Deserialize<RuntimeManifest>(input);
            string cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Lenticulizer", "Runtime");
            Root = PrepareCache(cache, Manifest, () => Resource("Lenticulizer.FixedRuntime.zip"), progress, cancellation, verifyAll);
        }

        // Recover the exact build payload from the release EXE for a source
        // rebuild, without downloading another copy of the browser.
        internal static void ExportForBuild(string directory)
        {
            directory = Path.GetFullPath(directory); Directory.CreateDirectory(directory);
            RuntimeManifest manifest;
            using (var input = Resource("Lenticulizer.FixedRuntime.json"))
                manifest = JsonSerializer.Deserialize<RuntimeManifest>(input);
            string temporary = Path.Combine(directory, "runtime-" + Guid.NewGuid().ToString("N") + ".tmp");
            try
            {
                using (var input = Resource("Lenticulizer.FixedRuntime.zip"))
                using (var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                    input.CopyTo(output);
                using (var input = File.OpenRead(temporary))
                    if (input.Length != manifest.archive_bytes || !string.Equals(Convert.ToHexString(SHA256.HashData(input)), manifest.archive_sha256, StringComparison.OrdinalIgnoreCase))
                        throw new InvalidDataException("The embedded runtime failed export verification.");
                File.Move(temporary, Path.Combine(directory, "runtime.zip"), true);
                using (var input = Resource("Lenticulizer.FixedRuntime.json"))
                using (var output = File.Create(Path.Combine(directory, "manifest.json")))
                    input.CopyTo(output);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }

        internal static string PrepareCache(string cache, RuntimeManifest manifest, Func<Stream> openArchive,
            Action<int> progress, CancellationToken cancellation, bool verifyAll)
        {
            if (manifest == null || manifest.archive_sha256 == null || manifest.archive_sha256.Length != 64
                || manifest.archive_sha256.Any(c => !Uri.IsHexDigit(c)) || manifest.files == null || manifest.files.Count == 0)
                throw new InvalidDataException("Invalid bundled runtime manifest.");
            cache = Path.GetFullPath(cache); Directory.CreateDirectory(cache);
            string key = manifest.archive_sha256.Substring(0, 24);
            string destination = Path.Combine(cache, key);
            using (var mutex = new Mutex(false, "LenticulizerRuntime_" + key))
            {
                bool acquired = false;
                try
                {
                    while (!acquired)
                    {
                        cancellation.ThrowIfCancellationRequested();
                        try { acquired = mutex.WaitOne(250); }
                        catch (AbandonedMutexException) { acquired = true; }
                    }
                    var candidates = new[] { destination }.Concat(Directory.GetDirectories(cache, key + "-repair-*"));
                    foreach (string candidate in candidates)
                    {
                        if (Ready(candidate, manifest, verifyAll, cancellation)) { progress?.Invoke(100); return candidate; }
                    }
                    // A damaged cache may still be held open by an earlier app
                    // window. Use a fresh cache rather than overwriting its DLLs.
                    if (Directory.Exists(destination)) destination += "-repair-" + Guid.NewGuid().ToString("N");
                    foreach (string abandoned in Directory.GetDirectories(cache, key + ".staging-*"))
                        try { Directory.Delete(abandoned, true); } catch (IOException) { } catch (UnauthorizedAccessException) { }
                    string stage = Path.Combine(cache, key + ".staging-" + Guid.NewGuid().ToString("N"));
                    Directory.CreateDirectory(stage);
                    try
                    {
                        progress?.Invoke(0);
                        using (var input = openArchive())
                            if (!string.Equals(Convert.ToHexString(SHA256.HashData(input)), manifest.archive_sha256, StringComparison.OrdinalIgnoreCase))
                                throw new InvalidDataException("The bundled runtime checksum is invalid. Download Lenticulizer again.");
                        var expected = manifest.files.ToDictionary(item => item.path, StringComparer.Ordinal);
                        long total = 0; int lastProgress = -1;
                        byte[] buffer = new byte[1024 * 1024];
                        using (var input = openArchive())
                        using (var zip = new ZipArchive(input, ZipArchiveMode.Read))
                        {
                            if (zip.Entries.Count != expected.Count) throw new InvalidDataException("Incomplete runtime archive.");
                            foreach (var entry in zip.Entries)
                            {
                                cancellation.ThrowIfCancellationRequested();
                                RuntimeFile file;
                                if (!expected.TryGetValue(entry.FullName, out file) || entry.Length != file.size)
                                    throw new InvalidDataException("Unexpected runtime archive entry.");
                                expected.Remove(entry.FullName);
                                string target = Target(stage, file.path);
                                Directory.CreateDirectory(Path.GetDirectoryName(target));
                                using (var source = entry.Open())
                                using (var output = new FileStream(target, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                                using (var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256))
                                {
                                    int count; long written = 0;
                                    while ((count = source.Read(buffer, 0, buffer.Length)) != 0)
                                    {
                                        cancellation.ThrowIfCancellationRequested();
                                        output.Write(buffer, 0, count); hash.AppendData(buffer, 0, count);
                                        written += count; total += count;
                                        int percent = (int)Math.Min(99, total * 100 / Math.Max(1, manifest.unpacked_bytes));
                                        if (percent != lastProgress) { lastProgress = percent; progress?.Invoke(percent); }
                                    }
                                    output.Flush(true);
                                    if (written != file.size || !string.Equals(Convert.ToHexString(hash.GetHashAndReset()), file.sha256, StringComparison.OrdinalIgnoreCase))
                                        throw new InvalidDataException("Runtime extraction verification failed: " + file.path);
                                }
                            }
                        }
                        if (expected.Count != 0) throw new InvalidDataException("Runtime archive entries are missing.");
                        BrowserPermissions(Path.Combine(stage, "browser"));
                        File.WriteAllText(Path.Combine(stage, "complete.sha256"), manifest.archive_sha256);
                        cancellation.ThrowIfCancellationRequested();
                        Directory.Move(stage, destination);
                        progress?.Invoke(100); return destination;
                    }
                    finally { if (Directory.Exists(stage)) Directory.Delete(stage, true); }
                }
                finally { if (acquired) mutex.ReleaseMutex(); }
            }
        }

        internal static string Target(string root, string relative)
        {
            if (string.IsNullOrEmpty(relative) || relative.Contains('\\') || relative.Contains(':') || relative.StartsWith('/')
                || relative.Split('/').Any(part => part == ".." || part == "." || part == ""))
                throw new InvalidDataException("Invalid runtime archive path.");
            string prefix = Path.GetFullPath(root) + Path.DirectorySeparatorChar;
            string target = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            if (!target.StartsWith(prefix, OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal))
                throw new InvalidDataException("Runtime archive path escapes the cache.");
            return target;
        }

        internal static bool Ready(string directory, RuntimeManifest manifest, bool verifyAll, CancellationToken cancellation)
        {
            try
            {
                string complete = Path.Combine(directory, "complete.sha256");
                if (!File.Exists(complete) || File.ReadAllText(complete) != manifest.archive_sha256) return false;
                foreach (var item in manifest.files)
                {
                    cancellation.ThrowIfCancellationRequested();
                    string path = Target(directory, item.path); var file = new FileInfo(path);
                    if (!file.Exists || file.Length != item.size || (file.Attributes & FileAttributes.ReparsePoint) != 0) return false;
                    if (verifyAll)
                        using (var input = file.OpenRead())
                            if (!string.Equals(Convert.ToHexString(SHA256.HashData(input)), item.sha256, StringComparison.OrdinalIgnoreCase)) return false;
                }
                return true;
            }
            catch (IOException) { return false; }
            catch (UnauthorizedAccessException) { return false; }
        }

        static void BrowserPermissions(string directory)
        {
            // Microsoft requires these read/execute permissions for the sandboxed
            // Fixed Runtime renderer on Windows 10. They apply to browser binaries
            // only; project files and image folders are not changed.
            if (!OperatingSystem.IsWindows() || OperatingSystem.IsWindowsVersionAtLeast(10, 0, 22000) || !Directory.Exists(directory)) return;
            var folder = new DirectoryInfo(directory); var access = folder.GetAccessControl();
            foreach (string sid in new[] { "S-1-15-2-1", "S-1-15-2-2" })
                access.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(sid), FileSystemRights.ReadAndExecute,
                    InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
            folder.SetAccessControl(access);
        }
    }
}
