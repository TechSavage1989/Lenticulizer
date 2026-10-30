using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Text;

namespace Lenticulizer.Core
{
    public static class PngCodec
    {
        public static void WriteGray16Png(string path, int width, int height, ushort[] axis, bool vertical, bool writePhys, uint pixelsPerMeterX, uint pixelsPerMeterY)
        {
            using (var fs = new FileStream(path, FileMode.Create, FileAccess.Write))
            {
                fs.Write(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 }, 0, 8);
                byte[] ihdr = new byte[13];
                Put32(ihdr, 0, (uint)width);
                Put32(ihdr, 4, (uint)height);
                ihdr[8] = 16;
                ihdr[9] = 0;
                ihdr[10] = 0;
                ihdr[11] = 0;
                ihdr[12] = 0;
                WriteChunk(fs, "IHDR", ihdr);
                if (writePhys)
                {
                    byte[] phys = new byte[9];
                    Put32(phys, 0, pixelsPerMeterX);
                    Put32(phys, 4, pixelsPerMeterY);
                    phys[8] = 1;
                    WriteChunk(fs, "pHYs", phys);
                }
                using (var raw = new MemoryStream())
                {
                    for (int y = 0; y < height; y++)
                    {
                        raw.WriteByte(0);
                        for (int x = 0; x < width; x++)
                        {
                            ushort v = vertical ? axis[x] : axis[y];
                            raw.WriteByte((byte)(v >> 8));
                            raw.WriteByte((byte)(v & 255));
                        }
                    }
                    raw.Position = 0;
                    using (var comp = new MemoryStream())
                    {
                        comp.WriteByte(0x78);
                        comp.WriteByte(0x9C);
                        using (var ds = new DeflateStream(comp, CompressionMode.Compress, true)) raw.CopyTo(ds);
                        uint ad = Adler32(raw.ToArray());
                        comp.WriteByte((byte)(ad >> 24));
                        comp.WriteByte((byte)(ad >> 16));
                        comp.WriteByte((byte)(ad >> 8));
                        comp.WriteByte((byte)ad);
                        WriteChunk(fs, "IDAT", comp.ToArray());
                    }
                }
                WriteChunk(fs, "IEND", new byte[0]);
            }
        }

        public static uint DpiToPixelsPerMeter(double dpi)
        {
            return (uint)Math.Max(1, Math.Round(dpi / 0.0254));
        }

        public static uint Read32(byte[] b, int o)
        {
            return ((uint)b[o] << 24) | ((uint)b[o + 1] << 16) | ((uint)b[o + 2] << 8) | b[o + 3];
        }

        public static bool TryReadPngPhysicalResolution(string path, out uint ppmX, out uint ppmY)
        {
            ppmX = 0;
            ppmY = 0;
            if (string.IsNullOrEmpty(path) || !File.Exists(path) || Path.GetExtension(path).ToLowerInvariant() != ".png") return false;
            try
            {
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                using (var br = new BinaryReader(fs))
                {
                    byte[] sig = br.ReadBytes(8);
                    if (sig.Length != 8 || sig[0] != 137 || sig[1] != 80 || sig[2] != 78 || sig[3] != 71) return false;
                    while (fs.Position + 12 <= fs.Length)
                    {
                        byte[] lb = br.ReadBytes(4); if (lb.Length < 4) break;
                        uint len = Read32(lb, 0);
                        byte[] tb = br.ReadBytes(4); if (tb.Length < 4) break;
                        string type = Encoding.ASCII.GetString(tb);
                        if (len > int.MaxValue || fs.Position + len + 4 > fs.Length) break;
                        byte[] data = br.ReadBytes((int)len);
                        br.ReadBytes(4);
                        if (type == "pHYs" && data.Length == 9 && data[8] == 1)
                        {
                            ppmX = Read32(data, 0);
                            ppmY = Read32(data, 4);
                            return true;
                        }
                        if (type == "IEND") break;
                    }
                }
            }
            catch { }
            return false;
        }

        public static byte[] MakePngTextData(string keyword, string value)
        {
            byte[] key = Encoding.ASCII.GetBytes(keyword);
            byte[] val = Encoding.UTF8.GetBytes(value ?? "");
            byte[] data = new byte[key.Length + 1 + val.Length];
            Buffer.BlockCopy(key, 0, data, 0, key.Length);
            data[key.Length] = 0;
            Buffer.BlockCopy(val, 0, data, key.Length + 1, val.Length);
            return data;
        }

        public static void SetPngLenticularMetadata(string path, double lpi, int views, double widthInches, double heightInches, bool vertical, string outputMode, double prismHeightMm)
        {
            byte[] original = File.ReadAllBytes(path);
            using (var input = new MemoryStream(original, false))
            using (var br = new BinaryReader(input))
            using (var output = new MemoryStream())
            {
                byte[] sig = br.ReadBytes(8);
                output.Write(sig, 0, sig.Length);
                bool inserted = false;
                while (input.Position + 12 <= input.Length)
                {
                    byte[] lb = br.ReadBytes(4); if (lb.Length < 4) break;
                    uint len = Read32(lb, 0);
                    byte[] tb = br.ReadBytes(4); if (tb.Length < 4) break;
                    string type = Encoding.ASCII.GetString(tb);
                    if (len > int.MaxValue || input.Position + len + 4 > input.Length) throw new Exception("Generated PNG has an invalid chunk length.");
                    byte[] data = br.ReadBytes((int)len);
                    byte[] crc = br.ReadBytes(4);

                    bool isOurText = false;
                    if (type == "tEXt" && data.Length > 0)
                    {
                        int nul = Array.IndexOf(data, (byte)0);
                        if (nul > 0)
                        {
                            string key = Encoding.ASCII.GetString(data, 0, nul);
                            isOurText = key.StartsWith("Lenticular", StringComparison.Ordinal);
                        }
                    }
                    if (isOurText) continue;

                    output.Write(lb, 0, 4); output.Write(tb, 0, 4); if (data.Length > 0) output.Write(data, 0, data.Length); output.Write(crc, 0, 4);
                    if (type == "IHDR" && !inserted)
                    {
                        WriteChunk(output, "tEXt", MakePngTextData("LenticularLPI", lpi.ToString("0.######", CultureInfo.InvariantCulture)));
                        WriteChunk(output, "tEXt", MakePngTextData("LenticularViews", views.ToString(CultureInfo.InvariantCulture)));
                        WriteChunk(output, "tEXt", MakePngTextData("LenticularWidthIn", widthInches.ToString("0.######", CultureInfo.InvariantCulture)));
                        WriteChunk(output, "tEXt", MakePngTextData("LenticularHeightIn", heightInches.ToString("0.######", CultureInfo.InvariantCulture)));
                        WriteChunk(output, "tEXt", MakePngTextData("LenticularOrientation", vertical ? "Vertical" : "Horizontal"));
                        WriteChunk(output, "tEXt", MakePngTextData("LenticulizerOutputMode", outputMode));
                        if (outputMode == "Lens-Free Relief") WriteChunk(output, "tEXt", MakePngTextData("LenticulizerPrismHeightMm", prismHeightMm.ToString("0.######", CultureInfo.InvariantCulture)));
                        inserted = true;
                    }
                    if (type == "IEND") break;
                }
                File.WriteAllBytes(path, output.ToArray());
            }
        }

        public static bool TryReadPngLenticularMetadata(string path, out double lpi, out int views, out double widthInches, out double heightInches, out bool vertical)
        {
            lpi = 0; views = 0; widthInches = 0; heightInches = 0; vertical = true;
            if (string.IsNullOrEmpty(path) || !File.Exists(path) || Path.GetExtension(path).ToLowerInvariant() != ".png") return false;
            var values = new Dictionary<string, string>();
            try
            {
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                using (var br = new BinaryReader(fs))
                {
                    byte[] sig = br.ReadBytes(8);
                    if (sig.Length != 8 || sig[0] != 137 || sig[1] != 80 || sig[2] != 78 || sig[3] != 71) return false;
                    while (fs.Position + 12 <= fs.Length)
                    {
                        byte[] lb = br.ReadBytes(4); if (lb.Length < 4) break;
                        uint len = Read32(lb, 0);
                        byte[] tb = br.ReadBytes(4); if (tb.Length < 4) break;
                        string type = Encoding.ASCII.GetString(tb);
                        if (len > int.MaxValue || fs.Position + len + 4 > fs.Length) break;
                        byte[] data = br.ReadBytes((int)len);
                        br.ReadBytes(4);
                        if (type == "tEXt" && data.Length > 0)
                        {
                            int nul = Array.IndexOf(data, (byte)0);
                            if (nul > 0)
                            {
                                string key = Encoding.ASCII.GetString(data, 0, nul);
                                if (key.StartsWith("Lenticular", StringComparison.Ordinal))
                                {
                                    string value = Encoding.UTF8.GetString(data, nul + 1, data.Length - nul - 1);
                                    values[key] = value;
                                }
                            }
                        }
                        if (type == "IEND") break;
                    }
                }
                if (!values.ContainsKey("LenticularLPI") || !double.TryParse(values["LenticularLPI"], NumberStyles.Float, CultureInfo.InvariantCulture, out lpi) || lpi <= 0) return false;
                if (values.ContainsKey("LenticularViews")) int.TryParse(values["LenticularViews"], NumberStyles.Integer, CultureInfo.InvariantCulture, out views);
                if (values.ContainsKey("LenticularWidthIn")) double.TryParse(values["LenticularWidthIn"], NumberStyles.Float, CultureInfo.InvariantCulture, out widthInches);
                if (values.ContainsKey("LenticularHeightIn")) double.TryParse(values["LenticularHeightIn"], NumberStyles.Float, CultureInfo.InvariantCulture, out heightInches);
                if (values.ContainsKey("LenticularOrientation")) vertical = !string.Equals(values["LenticularOrientation"], "Horizontal", StringComparison.OrdinalIgnoreCase);
                return true;
            }
            catch { return false; }
        }

        public static void SetPngPhysicalResolution(string path, uint ppmX, uint ppmY)
        {
            byte[] original = File.ReadAllBytes(path);
            if (original.Length < 8) throw new Exception("Generated PNG is invalid.");
            using (var input = new MemoryStream(original, false))
            using (var br = new BinaryReader(input))
            using (var output = new MemoryStream())
            {
                byte[] sig = br.ReadBytes(8);
                output.Write(sig, 0, sig.Length);
                bool inserted = false;
                while (input.Position + 12 <= input.Length)
                {
                    byte[] lb = br.ReadBytes(4); if (lb.Length < 4) break;
                    uint len = Read32(lb, 0);
                    byte[] tb = br.ReadBytes(4); if (tb.Length < 4) break;
                    string type = Encoding.ASCII.GetString(tb);
                    if (len > int.MaxValue || input.Position + len + 4 > input.Length) throw new Exception("Generated PNG has an invalid chunk length.");
                    byte[] data = br.ReadBytes((int)len);
                    byte[] crc = br.ReadBytes(4);
                    if (type == "pHYs") continue;
                    output.Write(lb, 0, 4);
                    output.Write(tb, 0, 4);
                    if (data.Length > 0) output.Write(data, 0, data.Length);
                    output.Write(crc, 0, 4);
                    if (type == "IHDR" && !inserted)
                    {
                        byte[] phys = new byte[9];
                        Put32(phys, 0, ppmX);
                        Put32(phys, 4, ppmY);
                        phys[8] = 1;
                        WriteChunk(output, "pHYs", phys);
                        inserted = true;
                    }
                    if (type == "IEND") break;
                }
                File.WriteAllBytes(path, output.ToArray());
            }
        }

        public static bool TryReadPngDimensions(string path, out int width, out int height)
        {
            width = 0;
            height = 0;
            if (string.IsNullOrEmpty(path) || !File.Exists(path) || Path.GetExtension(path).ToLowerInvariant() != ".png") return false;
            try
            {
                byte[] h = new byte[24];
                using (var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read))
                {
                    if (fs.Read(h, 0, h.Length) != h.Length) return false;
                }
                if (h[0] != 137 || h[1] != 80 || h[2] != 78 || h[3] != 71) return false;
                width = (int)Read32(h, 16);
                height = (int)Read32(h, 20);
                return width > 0 && height > 0;
            }
            catch { return false; }
        }

        public static bool VerifyImagePair(string originalPath, string depthPath, out string message)
        {
            int ow, oh, dw, dh;
            bool od = TryReadPngDimensions(originalPath, out ow, out oh);
            bool dd = TryReadPngDimensions(depthPath, out dw, out dh);
            if (!od) { try { using (var b = new Bitmap(originalPath)) { ow = b.Width; oh = b.Height; od = true; } } catch { } }
            if (!dd) { try { using (var b = new Bitmap(depthPath)) { dw = b.Width; dh = b.Height; dd = true; } } catch { } }
            if (!od || !dd) { message = "Could not read dimensions from both images."; return false; }
            if (ow != dw || oh != dh) { message = "Pixel dimensions differ: original " + ow + " x " + oh + ", depth " + dw + " x " + dh + "."; return false; }

            uint opx, opy, dpx, dpy;
            bool oph = TryReadPngPhysicalResolution(originalPath, out opx, out opy);
            bool dph = TryReadPngPhysicalResolution(depthPath, out dpx, out dpy);
            if (oph != dph) { message = "PNG physical-resolution metadata differs between original and depth image."; return false; }
            if (oph && (opx != dpx || opy != dpy)) { message = "PNG pHYs values differ: original " + opx + " x " + opy + " ppm, depth " + dpx + " x " + dpy + " ppm."; return false; }

            message = ow + " x " + oh + " px, exact pixel dimensions" + (oph ? ", identical PNG pHYs metadata" : ", neither file uses PNG pHYs metadata") + ".";
            return true;
        }

        public static uint Adler32(byte[] data)
        {
            const uint MOD = 65521;
            uint a = 1, b = 0;
            foreach (byte x in data)
            {
                a = (a + x) % MOD;
                b = (b + a) % MOD;
            }
            return (b << 16) | a;
        }

        public static void Put32(byte[] b, int o, uint v)
        {
            b[o] = (byte)(v >> 24);
            b[o + 1] = (byte)(v >> 16);
            b[o + 2] = (byte)(v >> 8);
            b[o + 3] = (byte)v;
        }

        public static void WriteChunk(Stream s, string type, byte[] data)
        {
            byte[] t = Encoding.ASCII.GetBytes(type);
            byte[] len = new byte[4];
            Put32(len, 0, (uint)data.Length);
            s.Write(len, 0, 4);
            s.Write(t, 0, 4);
            if (data.Length > 0) s.Write(data, 0, data.Length);
            byte[] all = new byte[4 + data.Length];
            Buffer.BlockCopy(t, 0, all, 0, 4);
            if (data.Length > 0) Buffer.BlockCopy(data, 0, all, 4, data.Length);
            uint crc = Crc32(all);
            byte[] c = new byte[4];
            Put32(c, 0, crc);
            s.Write(c, 0, 4);
        }

        public static uint Crc32(byte[] data)
        {
            uint crc = 0xffffffff;
            foreach (byte b in data)
            {
                crc ^= b;
                for (int k = 0; k < 8; k++) crc = (crc & 1) != 0 ? (crc >> 1) ^ 0xedb88320 : crc >> 1;
            }
            return crc ^ 0xffffffff;
        }

    }
}
