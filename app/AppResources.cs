using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;

namespace Lenticulizer.Desktop
{
    internal sealed class AppResource
    {
        public readonly byte[] Bytes;
        public readonly int Status;
        public readonly string Reason, Headers;

        public AppResource(byte[] bytes, int status, string reason, string type, bool head)
        {
            Status = status; Reason = reason;
            Headers = "Content-Type: " + type + "\r\nContent-Length: " + bytes.Length.ToString(CultureInfo.InvariantCulture)
                + "\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n";
            Bytes = head ? new byte[0] : bytes;
        }
    }

    // Serve both the embedded interface and project images through the same
    // request handler. A folder mapping for this host would bypass the handler,
    // leaving /local-image unavailable. Keeping one origin also preserves canvas
    // and WebGL access without weakening the page's content-security policy.
    internal static class AppResources
    {
        public const string Origin = "https://lenticulizer.app";
        public const string Filter = Origin + "/*";
        static readonly Dictionary<string, string> Types = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            { "/src/index.html", "text/html; charset=utf-8" },
            { "/src/app.css", "text/css; charset=utf-8" },
            { "/src/bridge.js", "application/javascript; charset=utf-8" },
            { "/src/renderer.js", "application/javascript; charset=utf-8" },
            { "/src/test-output.js", "application/javascript; charset=utf-8" },
            { "/assets/Lenticulizer_Icon_Source.svg", "image/svg+xml" },
            { "/assets/Lenticulizer.ico", "image/x-icon" }
        };

        public static Stream OpenEmbedded(string path)
        {
            if (!Types.ContainsKey(path)) throw new FileNotFoundException("Unknown interface resource.");
            var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("Lenticulizer.UI." + path.Substring(1).Replace('/', '.'));
            if (stream == null) throw new FileNotFoundException("The application is missing an embedded interface resource.");
            return stream;
        }

        public static AppResource Error(int status, string reason, bool head = false)
        {
            return new AppResource(Encoding.UTF8.GetBytes(reason), status, reason, "text/plain; charset=utf-8", head);
        }

        public static AppResource Read(string address, string method, Func<string, byte[]> readImage)
        {
            Uri uri;
            if (!Uri.TryCreate(address, UriKind.Absolute, out uri) || uri.Scheme != "https" || uri.Host != "lenticulizer.app"
                || uri.Port != 443 || uri.UserInfo != "") return Error(404, "Not Found");
            bool head = method == "HEAD";
            if (method != "GET" && !head) return Error(405, "Method Not Allowed");
            byte[] bytes; string type;
            if (uri.AbsolutePath == "/local-image")
            {
                var query = System.Web.HttpUtility.ParseQueryString(uri.Query);
                var paths = query.GetValues("path");
                if (paths == null || paths.Length != 1 || string.IsNullOrWhiteSpace(paths[0])) return Error(400, "Bad Request", head);
                if (readImage == null) return Error(503, "Service Unavailable", head);
                bytes = readImage(paths[0]);
                string extension = Path.GetExtension(paths[0]).ToLowerInvariant();
                type = extension == ".jpg" || extension == ".jpeg" ? "image/jpeg" : extension == ".bmp" ? "image/bmp" : extension == ".gif" ? "image/gif" : "image/png";
            }
            else
            {
                if (!Types.TryGetValue(uri.AbsolutePath, out type)) return Error(404, "Not Found", head);
                using (var input = OpenEmbedded(uri.AbsolutePath))
                using (var output = new MemoryStream()) { input.CopyTo(output); bytes = output.ToArray(); }
            }
            return new AppResource(bytes, 200, "OK", type, head);
        }
    }
}
