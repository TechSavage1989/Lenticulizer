using System;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Lenticulizer.Desktop
{
    internal static class ReleasePackager
    {
        internal static readonly string[] Notes = new[]
        {
            "Alpha 33 is a small version and Help/Updates text change to test updating from Alpha 32.",
            "The stable Lenticulizer.exe name, project workflows, settings storage, and Blender add-on v1.18.43 are retained.",
            "Update checks are automatic; downloading and installing the verified update remain user-initiated."
        };

        internal static int Build(string destination)
        {
            try
            {
                destination = Path.GetFullPath(destination);
                Directory.CreateDirectory(destination);
                string source = Environment.ProcessPath ?? throw new InvalidOperationException("The running executable path is unavailable.");
                if (!string.Equals(Path.GetFileName(source), "Lenticulizer.exe", StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("Release packaging must run from the stable Lenticulizer.exe build output.");
                string packagePath = Path.Combine(destination, "Lenticulizer_Windows_Portable.zip");
                string manifestPath = Path.Combine(destination, "update-manifest.json");
                string sumsPath = Path.Combine(destination, "SHA256SUMS.txt");
                if (File.Exists(packagePath)) File.Delete(packagePath);
                using (var archive = ZipFile.Open(packagePath, ZipArchiveMode.Create))
                {
                    var entry = archive.CreateEntry("Lenticulizer.exe", CompressionLevel.NoCompression);
                    using var input = File.OpenRead(source);
                    using var output = entry.Open();
                    input.CopyTo(output);
                }
                long size = new FileInfo(packagePath).Length;
                string packageHash = Hash(packagePath);
                string exeHash = Hash(source);
                var manifest = new
                {
                    schema = 1,
                    app_id = "techsavage1989.lenticulizer",
                    version = Program.Version,
                    exe_name = "Lenticulizer.exe",
                    package = new { name = "Lenticulizer_Windows_Portable.zip", sha256 = packageHash, size },
                    notes = Notes,
                    read_more_url = "https://github.com/TechSavage1989/Lenticulizer/releases/tag/v" + Program.Version
                };
                File.WriteAllText(manifestPath, JsonSerializer.Serialize(manifest, new JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine, new UTF8Encoding(false));
                File.WriteAllText(sumsPath,
                    packageHash + "  Lenticulizer_Windows_Portable.zip" + Environment.NewLine +
                    exeHash + "  Lenticulizer.exe" + Environment.NewLine +
                    Hash(manifestPath) + "  update-manifest.json" + Environment.NewLine,
                    new UTF8Encoding(false));
                Console.WriteLine("Release package created: " + packagePath);
                Console.WriteLine("SHA-256: " + packageHash);
                return 0;
            }
            catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        }

        static string Hash(string path)
        {
            using var stream = File.OpenRead(path);
            return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        }
    }
}
