using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.NetworkInformation;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace Lenticulizer.Desktop
{
    internal sealed class UpdateService : IDisposable
    {
        const string ReleasesApi = "https://api.github.com/repos/TechSavage1989/Lenticulizer/releases?per_page=20";
        const string ManifestName = "update-manifest.json";
        const string PackageName = "Lenticulizer_Windows_Portable.zip";
        const string AppId = "techsavage1989.lenticulizer";
        const long MaximumDownloadBytes = 1610612736L; // 1.5 GiB hard ceiling for a self-contained portable package.

        readonly HttpClient http;
        readonly SemaphoreSlim singleFlight = new SemaphoreSlim(1, 1);
        readonly object sync = new object();
        readonly string root;
        readonly string statePath;
        readonly string downloadDirectory;
        readonly string stageDirectory;
        UpdateCacheState cache;
        Dictionary<string, object> status;
        ReleaseCandidate candidate;
        DateTimeOffset lastCompletedCheck = DateTimeOffset.MinValue;
        DateTimeOffset lastManualCheck = DateTimeOffset.MinValue;
        DateTimeOffset nextAllowedCheck = DateTimeOffset.MinValue;
        bool disposed;

        public event Action<Dictionary<string, object>> StatusChanged;

        public UpdateService()
        {
            root = Path.Combine(Program.LocalRoot, "Lenticulizer", "Updates");
            statePath = Path.Combine(root, "state.json");
            downloadDirectory = Path.Combine(root, "Downloads");
            stageDirectory = Path.Combine(root, "Staging");
            Directory.CreateDirectory(root);
            Directory.CreateDirectory(downloadDirectory);
            Directory.CreateDirectory(stageDirectory);
            cache = LoadState();
            if (DateTimeOffset.TryParse(cache.NextAllowedUtc, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind, out var persistedBackoff) && persistedBackoff > DateTimeOffset.UtcNow) nextAllowedCheck = persistedBackoff;
            status = BaseStatus("idle", "Update check has not run yet.");

            var handler = new HttpClientHandler { AllowAutoRedirect = true, AutomaticDecompression = DecompressionMethods.GZip | DecompressionMethods.Deflate };
            http = new HttpClient(handler) { Timeout = TimeSpan.FromSeconds(30) };
            http.DefaultRequestHeaders.UserAgent.ParseAdd("Lenticulizer/" + Program.Version + " (+https://github.com/TechSavage1989/Lenticulizer)");
            http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/vnd.github+json"));
            http.DefaultRequestHeaders.Add("X-GitHub-Api-Version", "2022-11-28");
        }

        public DateTimeOffset LastCompletedCheck { get { lock (sync) return lastCompletedCheck; } }
        public Dictionary<string, object> CurrentStatus { get { lock (sync) return CloneStatus(status); } }

        Dictionary<string, object> BaseStatus(string state, string message)
        {
            return new Dictionary<string, object>
            {
                { "state", state },
                { "message", message },
                { "installedVersion", Program.Version },
                { "latestVersion", "" },
                { "releaseName", "" },
                { "releaseUrl", "" },
                { "notes", new object[0] },
                { "readMoreUrl", "" },
                { "canDownload", false },
                { "canInstall", false },
                { "downloadedBytes", 0L },
                { "totalBytes", 0L },
                { "checkedUtc", "" }
            };
        }

        static Dictionary<string, object> CloneStatus(Dictionary<string, object> value)
        {
            return new Dictionary<string, object>(value);
        }

        void Publish(Dictionary<string, object> value)
        {
            lock (sync) status = value;
            try { StatusChanged?.Invoke(CloneStatus(value)); } catch { }
        }

        public bool ShouldCheckOnFocus(TimeSpan minimumAge)
        {
            var last = LastCompletedCheck;
            return last == DateTimeOffset.MinValue || DateTimeOffset.UtcNow - last >= minimumAge;
        }

        public async Task<Dictionary<string, object>> CheckAsync(bool manual, CancellationToken cancellation = default)
        {
            if (disposed) throw new ObjectDisposedException(nameof(UpdateService));
            var now = DateTimeOffset.UtcNow;
            lock (sync)
            {
                if (manual && now - lastManualCheck < TimeSpan.FromSeconds(10))
                    return CloneStatus(status);
                if (manual) lastManualCheck = now;
                if (now < nextAllowedCheck)
                {
                    var wait = nextAllowedCheck - now;
                    var blocked = BaseStatus("deferred", "Update checks are temporarily paused. Try again in " + Math.Max(1, (int)Math.Ceiling(wait.TotalSeconds)) + " seconds.");
                    blocked["checkedUtc"] = now.ToString("o");
                    return blocked;
                }
            }

            if (!await singleFlight.WaitAsync(0, cancellation).ConfigureAwait(false)) return CurrentStatus;
            try
            {
                if (!NetworkInterface.GetIsNetworkAvailable())
                {
                    candidate = null;
                    var offline = BaseStatus("offline", "Update check unavailable while the computer is offline.");
                    offline["checkedUtc"] = DateTimeOffset.UtcNow.ToString("o");
                    lock (sync) lastCompletedCheck = DateTimeOffset.UtcNow;
                    Publish(offline);
                    return CloneStatus(offline);
                }
                var checking = BaseStatus("checking", manual ? "Checking for updates..." : "Checking for updates in the background...");
                Publish(checking);
                Dictionary<string, object> result;
                try { result = await CheckCoreAsync(cancellation).ConfigureAwait(false); }
                catch (OperationCanceledException) when (cancellation.IsCancellationRequested) { throw; }
                catch (Exception error)
                {
                    candidate = null;
                    Program.Log("Update check: " + error);
                    result = BaseStatus("error", "Update check failed: " + Friendly(error));
                    result["checkedUtc"] = DateTimeOffset.UtcNow.ToString("o");
                }
                lock (sync) lastCompletedCheck = DateTimeOffset.UtcNow;
                Publish(result);
                return CloneStatus(result);
            }
            finally { singleFlight.Release(); }
        }

        async Task<Dictionary<string, object>> CheckCoreAsync(CancellationToken cancellation)
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, ReleasesApi);
            if (!string.IsNullOrWhiteSpace(cache.ReleasesEtag)) request.Headers.TryAddWithoutValidation("If-None-Match", cache.ReleasesEtag);
            using var response = await http.SendAsync(request, HttpCompletionOption.ResponseContentRead, cancellation).ConfigureAwait(false);
            ApplyBackoff(response);

            string releasesJson;
            if (response.StatusCode == HttpStatusCode.NotModified && !string.IsNullOrWhiteSpace(cache.ReleasesJson)) releasesJson = cache.ReleasesJson;
            else
            {
                if (!response.IsSuccessStatusCode) throw new HttpRequestException("GitHub returned HTTP " + (int)response.StatusCode + ".");
                releasesJson = await response.Content.ReadAsStringAsync(cancellation).ConfigureAwait(false);
                cache.ReleasesJson = releasesJson;
                cache.ReleasesEtag = response.Headers.ETag == null ? "" : response.Headers.ETag.ToString();
                SaveState();
            }

            ReleaseCandidate selected = await SelectCandidateAsync(releasesJson, cancellation).ConfigureAwait(false);
            if (selected == null)
            {
                candidate = null;
                var unavailable = BaseStatus("unavailable", "No compatible Lenticulizer release is published yet.");
                unavailable["checkedUtc"] = DateTimeOffset.UtcNow.ToString("o");
                return unavailable;
            }

            candidate = selected;
            var current = SemanticVersion.Parse(Program.Version);
            var latest = SemanticVersion.Parse(selected.Version);
            bool newer = latest.CompareTo(current) > 0;
            var result = BaseStatus(newer ? "available" : "up_to_date", newer ? "A newer Lenticulizer release is available." : "Lenticulizer is up to date.");
            result["latestVersion"] = selected.Version;
            result["releaseName"] = selected.ReleaseName;
            result["releaseUrl"] = selected.ReleaseUrl;
            result["notes"] = selected.Notes.Cast<object>().ToArray();
            result["readMoreUrl"] = selected.ReadMoreUrl;
            result["canDownload"] = newer;
            result["canInstall"] = newer && selected.DownloadedPath != "" && File.Exists(selected.DownloadedPath);
            result["checkedUtc"] = DateTimeOffset.UtcNow.ToString("o");
            return result;
        }

        async Task<ReleaseCandidate> SelectCandidateAsync(string releasesJson, CancellationToken cancellation)
        {
            using var document = JsonDocument.Parse(releasesJson);
            if (document.RootElement.ValueKind != JsonValueKind.Array) throw new InvalidDataException("GitHub release response is not an array.");
            var releases = new List<(SemanticVersion Version, JsonElement Element)>();
            foreach (var release in document.RootElement.EnumerateArray())
            {
                if (release.TryGetProperty("draft", out var draft) && draft.GetBoolean()) continue;
                string tag = Text(release, "tag_name");
                if (!SemanticVersion.TryParse(tag, out var version)) continue;
                releases.Add((version, release.Clone()));
            }
            foreach (var item in releases.OrderByDescending(r => r.Version))
            {
                var release = item.Element;
                if (!release.TryGetProperty("assets", out var assets) || assets.ValueKind != JsonValueKind.Array) continue;
                string manifestUrl = "";
                foreach (var asset in assets.EnumerateArray()) if (Text(asset, "name") == ManifestName) { manifestUrl = Text(asset, "browser_download_url"); break; }
                if (manifestUrl == "") continue;
                ValidateDownloadUri(manifestUrl, true);
                string manifestJson = await GetSmallTextAsync(manifestUrl, 1024 * 1024, cancellation).ConfigureAwait(false);
                var candidate = ParseManifest(manifestJson, release, assets);
                if (candidate != null && candidate.Version == item.Version.ToString()) return candidate;
            }
            return null;
        }

        ReleaseCandidate ParseManifest(string manifestJson, JsonElement release, JsonElement assets)
        {
            using var document = JsonDocument.Parse(manifestJson);
            var root = document.RootElement;
            if (Number(root, "schema", 0) != 1) return null;
            if (!string.Equals(Text(root, "app_id"), AppId, StringComparison.Ordinal)) return null;
            string version = Text(root, "version");
            if (!SemanticVersion.TryParse(version, out _)) return null;
            string exeName = Text(root, "exe_name");
            if (!string.Equals(exeName, "Lenticulizer.exe", StringComparison.OrdinalIgnoreCase)) return null;
            if (!root.TryGetProperty("package", out var package) || package.ValueKind != JsonValueKind.Object) return null;
            string packageName = Text(package, "name");
            if (!string.Equals(packageName, PackageName, StringComparison.Ordinal)) return null;
            string sha = Text(package, "sha256").ToLowerInvariant();
            long size = Long(package, "size", 0);
            if (packageName == "" || sha.Length != 64 || !sha.All(Uri.IsHexDigit) || size <= 0 || size > MaximumDownloadBytes) return null;
            string packageUrl = ""; long packageAssetSize = 0;
            foreach (var asset in assets.EnumerateArray()) if (Text(asset, "name") == packageName) { packageUrl = Text(asset, "browser_download_url"); packageAssetSize = Long(asset, "size", 0); break; }
            if (packageUrl == "" || packageAssetSize != size) return null;
            ValidateDownloadUri(packageUrl, true);
            var notes = new List<string>();
            if (root.TryGetProperty("notes", out var noteArray) && noteArray.ValueKind == JsonValueKind.Array)
                foreach (var note in noteArray.EnumerateArray()) if (note.ValueKind == JsonValueKind.String && notes.Count < 6) { var value = note.GetString()?.Trim(); if (!string.IsNullOrEmpty(value)) notes.Add(value); }
            string readMore = Text(root, "read_more_url");
            if (readMore != "")
            {
                try { ValidateReleasePageUri(readMore); } catch { readMore = ""; }
            }
            string downloaded = Path.Combine(downloadDirectory, "Lenticulizer-" + Sanitize(version) + ".zip");
            return new ReleaseCandidate
            {
                Version = version,
                ReleaseName = Text(release, "name") != "" ? Text(release, "name") : Text(release, "tag_name"),
                ReleaseUrl = Text(release, "html_url"),
                PackageName = packageName,
                PackageUrl = packageUrl,
                PackageSha256 = sha,
                PackageSize = size,
                Notes = notes.ToArray(),
                ReadMoreUrl = readMore,
                DownloadedPath = File.Exists(downloaded) && HashFile(downloaded) == sha ? downloaded : ""
            };
        }

        public async Task<Dictionary<string, object>> DownloadAsync(CancellationToken cancellation = default)
        {
            if (candidate == null) await CheckAsync(true, cancellation).ConfigureAwait(false);
            var selected = candidate;
            if (selected == null) throw new InvalidOperationException("No compatible update is available to download.");
            if (SemanticVersion.Parse(selected.Version).CompareTo(SemanticVersion.Parse(Program.Version)) <= 0) throw new InvalidOperationException("No newer release is available.");
            if (!await singleFlight.WaitAsync(0, cancellation).ConfigureAwait(false)) throw new InvalidOperationException("Another update action is already running.");
            try
            {
                Directory.CreateDirectory(downloadDirectory);
                string finalPath = Path.Combine(downloadDirectory, "Lenticulizer-" + Sanitize(selected.Version) + ".zip");
                string temporary = finalPath + ".part-" + Guid.NewGuid().ToString("N");
                try
                {
                    ValidateDownloadUri(selected.PackageUrl, true);
                    using var response = await http.GetAsync(selected.PackageUrl, HttpCompletionOption.ResponseHeadersRead, cancellation).ConfigureAwait(false);
                    if (response.RequestMessage?.RequestUri != null) ValidateDownloadUri(response.RequestMessage.RequestUri.AbsoluteUri, true);
                    ApplyBackoff(response);
                    if (!response.IsSuccessStatusCode) throw new HttpRequestException("Download returned HTTP " + (int)response.StatusCode + ".");
                    long total = response.Content.Headers.ContentLength ?? selected.PackageSize;
                    if (total <= 0 || total > MaximumDownloadBytes) throw new InvalidDataException("Update package size is not allowed.");
                    await using var input = await response.Content.ReadAsStreamAsync(cancellation).ConfigureAwait(false);
                    await using var output = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1024 * 128, true);
                    byte[] buffer = new byte[1024 * 128]; long written = 0, lastPublishedBytes = 0; int read;
                    var progressClock = Stopwatch.StartNew();
                    while ((read = await input.ReadAsync(buffer.AsMemory(0, buffer.Length), cancellation).ConfigureAwait(false)) > 0)
                    {
                        written += read;
                        if (written > MaximumDownloadBytes || written > selected.PackageSize + 1024 * 1024) throw new InvalidDataException("Update package exceeded the expected size.");
                        await output.WriteAsync(buffer.AsMemory(0, read), cancellation).ConfigureAwait(false);
                        if (written - lastPublishedBytes >= 4L * 1024 * 1024 || progressClock.ElapsedMilliseconds >= 250)
                        {
                            var progress = CurrentStatus;
                            progress["state"] = "downloading";
                            progress["message"] = "Downloading update...";
                            progress["downloadedBytes"] = written;
                            progress["totalBytes"] = total;
                            progress["canDownload"] = false;
                            progress["canInstall"] = false;
                            Publish(progress);
                            lastPublishedBytes = written;
                            progressClock.Restart();
                        }
                    }
                    await output.FlushAsync(cancellation).ConfigureAwait(false);
                    if (written != selected.PackageSize) throw new InvalidDataException("Downloaded update size does not match the release manifest.");
                    string hash = HashFile(temporary);
                    if (!string.Equals(hash, selected.PackageSha256, StringComparison.OrdinalIgnoreCase)) throw new CryptographicException("Downloaded update hash does not match the release manifest.");
                    File.Move(temporary, finalPath, true);
                    selected.DownloadedPath = finalPath;
                    candidate = selected;
                    var complete = CurrentStatus;
                    complete["state"] = "downloaded";
                    complete["message"] = "Update downloaded and verified.";
                    complete["downloadedBytes"] = selected.PackageSize;
                    complete["totalBytes"] = selected.PackageSize;
                    complete["canDownload"] = false;
                    complete["canInstall"] = true;
                    Publish(complete);
                    return complete;
                }
                finally { TryDelete(temporary); }
            }
            finally { singleFlight.Release(); }
        }

        public UpdateInstallPlan PrepareInstall()
        {
            var selected = candidate ?? throw new InvalidOperationException("No update has been selected.");
            if (selected.DownloadedPath == "" || !File.Exists(selected.DownloadedPath)) throw new InvalidOperationException("Download and verify the update first.");
            if (HashFile(selected.DownloadedPath) != selected.PackageSha256) throw new CryptographicException("The downloaded package no longer matches its release hash.");
            Directory.CreateDirectory(stageDirectory);
            string stage = Path.Combine(stageDirectory, "stage-" + Sanitize(selected.Version) + "-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(stage);
            string exePath = ExtractValidatedPackage(selected.DownloadedPath, stage, selected.Version);
            return new UpdateInstallPlan { Version = selected.Version, StagedExe = exePath, PackagePath = selected.DownloadedPath };
        }

        string ExtractValidatedPackage(string archivePath, string stage, string version)
        {
            using var archive = ZipFile.OpenRead(archivePath);
            if (archive.Entries.Count != 1) throw new InvalidDataException("Update package must contain exactly one file.");
            var entry = archive.Entries[0];
            if (!string.Equals(entry.FullName.Replace('\\', '/'), "Lenticulizer.exe", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Update package has an unexpected file layout.");
            if (entry.Length <= 0 || entry.Length > MaximumDownloadBytes) throw new InvalidDataException("Update executable size is not allowed.");
            if (entry.CompressedLength > 0 && entry.Length / Math.Max(1.0, entry.CompressedLength) > 200.0) throw new InvalidDataException("Update package compression ratio is not allowed.");
            string destination = Path.GetFullPath(Path.Combine(stage, "Lenticulizer.exe"));
            if (!destination.StartsWith(Path.GetFullPath(stage) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Update archive path escapes staging.");
            entry.ExtractToFile(destination, true);
            ValidatePortableExe(destination, version);
            return destination;
        }

        static void ValidatePortableExe(string path, string version)
        {
            using (var stream = File.OpenRead(path))
            {
                if (stream.Length < 1024 || stream.ReadByte() != 'M' || stream.ReadByte() != 'Z') throw new InvalidDataException("Update executable is not a Windows PE file.");
            }
            var info = FileVersionInfo.GetVersionInfo(path);
            if (!string.Equals(info.ProductName, "Lenticulizer", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Update executable has the wrong application identity.");
            if (string.IsNullOrWhiteSpace(info.ProductVersion) || info.ProductVersion.IndexOf(version, StringComparison.OrdinalIgnoreCase) < 0) throw new InvalidDataException("Update executable version does not match the release manifest.");
        }

        async Task<string> GetSmallTextAsync(string url, int maxBytes, CancellationToken cancellation)
        {
            ValidateDownloadUri(url, true);
            using var response = await http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, cancellation).ConfigureAwait(false);
            if (response.RequestMessage?.RequestUri != null) ValidateDownloadUri(response.RequestMessage.RequestUri.AbsoluteUri, true);
            ApplyBackoff(response);
            if (!response.IsSuccessStatusCode) throw new HttpRequestException("Release metadata returned HTTP " + (int)response.StatusCode + ".");
            long length = response.Content.Headers.ContentLength ?? 0;
            if (length > maxBytes) throw new InvalidDataException("Release metadata is too large.");
            byte[] bytes = await response.Content.ReadAsByteArrayAsync(cancellation).ConfigureAwait(false);
            if (bytes.Length > maxBytes) throw new InvalidDataException("Release metadata is too large.");
            return Encoding.UTF8.GetString(bytes);
        }

        void ApplyBackoff(HttpResponseMessage response)
        {
            var now = DateTimeOffset.UtcNow;
            DateTimeOffset until = DateTimeOffset.MinValue;
            if (response.Headers.RetryAfter != null)
            {
                if (response.Headers.RetryAfter.Delta.HasValue) until = now + response.Headers.RetryAfter.Delta.Value;
                else if (response.Headers.RetryAfter.Date.HasValue) until = response.Headers.RetryAfter.Date.Value;
            }
            if (response.Headers.TryGetValues("X-RateLimit-Remaining", out var remaining) && remaining.FirstOrDefault() == "0" && response.Headers.TryGetValues("X-RateLimit-Reset", out var reset) && long.TryParse(reset.FirstOrDefault(), out var seconds))
            {
                var resetAt = DateTimeOffset.FromUnixTimeSeconds(seconds).AddSeconds(2);
                if (resetAt > until) until = resetAt;
            }
            if ((int)response.StatusCode >= 500 && until < now.AddSeconds(30)) until = now.AddSeconds(30);
            if ((int)response.StatusCode == 403 && until < now.AddMinutes(1)) until = now.AddMinutes(1);
            if (until > now)
            {
                lock (sync) nextAllowedCheck = until;
                cache.NextAllowedUtc = until.ToString("o", CultureInfo.InvariantCulture);
                SaveState();
            }
        }

        static void ValidateReleasePageUri(string value)
        {
            if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps || !string.Equals(uri.Host, "github.com", StringComparison.OrdinalIgnoreCase) || !uri.AbsolutePath.StartsWith("/TechSavage1989/Lenticulizer/", StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Release notes URL is not an authorized Lenticulizer GitHub URL.");
        }

        static void ValidateDownloadUri(string value, bool allowReleaseCdn)
        {
            if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme != Uri.UriSchemeHttps) throw new InvalidDataException("Update URL must use HTTPS.");
            string host = uri.Host.ToLowerInvariant();
            bool allowed = host == "github.com" || host == "api.github.com" || host == "objects.githubusercontent.com" || host == "github-releases.githubusercontent.com" || host == "release-assets.githubusercontent.com";
            if (!allowed || (!allowReleaseCdn && host != "github.com" && host != "api.github.com")) throw new InvalidDataException("Update URL host is not allowed.");
        }

        static string Friendly(Exception error)
        {
            if (error is TaskCanceledException) return "the request timed out";
            if (error is HttpRequestException) return error.Message;
            if (error is IOException) return "network or disk I/O failed";
            return error.Message;
        }

        static string HashFile(string path)
        {
            using var stream = File.OpenRead(path);
            return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        }

        static string Sanitize(string value) => new string((value ?? "update").Select(ch => char.IsLetterOrDigit(ch) || ch == '.' || ch == '-' ? ch : '_').ToArray());
        static string Text(JsonElement value, string name) => value.TryGetProperty(name, out var item) && item.ValueKind == JsonValueKind.String ? item.GetString() ?? "" : "";
        static int Number(JsonElement value, string name, int fallback) => value.TryGetProperty(name, out var item) && item.TryGetInt32(out var result) ? result : fallback;
        static long Long(JsonElement value, string name, long fallback) => value.TryGetProperty(name, out var item) && item.TryGetInt64(out var result) ? result : fallback;
        static void TryDelete(string path) { try { if (!string.IsNullOrEmpty(path) && File.Exists(path)) File.Delete(path); } catch { } }

        UpdateCacheState LoadState()
        {
            try { return File.Exists(statePath) ? JsonSerializer.Deserialize<UpdateCacheState>(File.ReadAllText(statePath)) ?? new UpdateCacheState() : new UpdateCacheState(); }
            catch { return new UpdateCacheState(); }
        }
        void SaveState()
        {
            try
            {
                Directory.CreateDirectory(root);
                string temp = statePath + ".tmp";
                File.WriteAllText(temp, JsonSerializer.Serialize(cache));
                File.Move(temp, statePath, true);
            }
            catch { }
        }

        public void Dispose()
        {
            if (disposed) return;
            disposed = true;
            // HttpClient disposal cancels in-flight network I/O. Keep the semaphore
            // alive until process teardown so an already-running Check/Download can
            // safely execute its finally { singleFlight.Release(); } path.
            http.Dispose();
        }

        sealed class UpdateCacheState
        {
            public string ReleasesEtag { get; set; } = "";
            public string ReleasesJson { get; set; } = "";
            public string NextAllowedUtc { get; set; } = "";
        }
        sealed class ReleaseCandidate
        {
            public string Version = "";
            public string ReleaseName = "";
            public string ReleaseUrl = "";
            public string PackageName = "";
            public string PackageUrl = "";
            public string PackageSha256 = "";
            public long PackageSize;
            public string[] Notes = Array.Empty<string>();
            public string ReadMoreUrl = "";
            public string DownloadedPath = "";
        }

        readonly struct SemanticVersion : IComparable<SemanticVersion>
        {
            readonly int major, minor, patch;
            readonly string[] prerelease;
            SemanticVersion(int major, int minor, int patch, string[] prerelease) { this.major = major; this.minor = minor; this.patch = patch; this.prerelease = prerelease; }
            public static SemanticVersion Parse(string value) { if (!TryParse(value, out var result)) throw new FormatException("Invalid version: " + value); return result; }
            public static bool TryParse(string value, out SemanticVersion result)
            {
                result = default;
                string text = (value ?? "").Trim(); if (text.StartsWith("v", StringComparison.OrdinalIgnoreCase)) text = text.Substring(1);
                int plus = text.IndexOf('+'); if (plus >= 0) text = text.Substring(0, plus);
                string pre = ""; int dash = text.IndexOf('-'); if (dash >= 0) { pre = text.Substring(dash + 1); text = text.Substring(0, dash); }
                var core = text.Split('.'); if (core.Length != 3 || !int.TryParse(core[0], out var a) || !int.TryParse(core[1], out var b) || !int.TryParse(core[2], out var c)) return false;
                result = new SemanticVersion(a, b, c, string.IsNullOrEmpty(pre) ? Array.Empty<string>() : pre.Split('.')); return true;
            }
            public int CompareTo(SemanticVersion other)
            {
                int c = major.CompareTo(other.major); if (c != 0) return c;
                c = minor.CompareTo(other.minor); if (c != 0) return c;
                c = patch.CompareTo(other.patch); if (c != 0) return c;
                if (prerelease.Length == 0 && other.prerelease.Length == 0) return 0;
                if (prerelease.Length == 0) return 1; if (other.prerelease.Length == 0) return -1;
                for (int i = 0; i < Math.Max(prerelease.Length, other.prerelease.Length); i++)
                {
                    if (i >= prerelease.Length) return -1; if (i >= other.prerelease.Length) return 1;
                    bool an = int.TryParse(prerelease[i], NumberStyles.None, CultureInfo.InvariantCulture, out var ai);
                    bool bn = int.TryParse(other.prerelease[i], NumberStyles.None, CultureInfo.InvariantCulture, out var bi);
                    if (an && bn) { c = ai.CompareTo(bi); if (c != 0) return c; }
                    else if (an != bn) return an ? -1 : 1;
                    else { c = string.CompareOrdinal(prerelease[i], other.prerelease[i]); if (c != 0) return c; }
                }
                return 0;
            }
            public override string ToString()
            {
                string core = major + "." + minor + "." + patch;
                return prerelease.Length == 0 ? core : core + "-" + string.Join('.', prerelease);
            }
        }
    }

    internal sealed class UpdateInstallPlan
    {
        public string Version { get; set; } = "";
        public string StagedExe { get; set; } = "";
        public string PackagePath { get; set; } = "";
    }
}
