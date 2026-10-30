using System;
using System.IO;
using System.Text;
using System.Globalization;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.Drawing.Drawing2D;
namespace Lenticulizer.Core
{
    public sealed class CalibrationVariant
    {
        public string Name, Profile, Note;
        public double PeakMm, ValleyMm, PhasePitch, ViewingAngleDeg;
    }
    public sealed class CalibrationService
    {
        readonly ProjectState state;
        readonly OpticalEngine optics;
        readonly Bitmap source;
        public CalibrationService(ProjectState state, Bitmap source)
        { this.state = state; this.source = source; optics = new OpticalEngine(state.Optics); }
        double CalibrationCouponSizeMm()
        {
            string text = state.CalibrationSize;
            string[] parts = text.Split(' ');
            double mm;
            if (parts.Length == 0 || !double.TryParse(parts[0], NumberStyles.Float, CultureInfo.InvariantCulture, out mm) || mm <= 0) mm = 20.0;
            return mm;
        }

        Bitmap CreateCalibrationCouponBitmap(int cropX, int cropY, int cropW, int cropH)
        {
            Bitmap coupon = new Bitmap(cropW, cropH, PixelFormat.Format24bppRgb);
            using (Graphics g = Graphics.FromImage(coupon))
            {
                g.Clear(Color.White);
                g.InterpolationMode = InterpolationMode.NearestNeighbor;
                g.PixelOffsetMode = PixelOffsetMode.Half;
                g.SmoothingMode = SmoothingMode.None;
                Rectangle srcRect = new Rectangle(cropX, cropY, cropW, cropH);
                g.DrawImage(source, new Rectangle(0, 0, cropW, cropH), srcRect, GraphicsUnit.Pixel);
            }
            return coupon;
        }

        public static string SafeCalibrationName(string value)
        {
            if (string.IsNullOrEmpty(value)) return "variant";
            StringBuilder sb = new StringBuilder();
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                if (char.IsLetterOrDigit(c)) sb.Append(c);
                else if (c == '.' || c == '-') sb.Append(c == '.' ? 'p' : 'm');
                else if (c == '_' || c == ' ') sb.Append('_');
            }
            return sb.ToString().Trim('_');
        }

        void AddCalibrationVariant(List<CalibrationVariant> list, string name, double peakMm, double valleyMm, double phasePitch, string profile, double angleDeg, string note)
        {
            if (peakMm <= 0 || peakMm > optics.MaximumTopHeightMm() + 0.0001) return;
            if (valleyMm < 0 || valleyMm > peakMm) return;
            if (valleyMm > 0 && valleyMm < optics.MinimumValleyHeightMm()) return;
            CalibrationVariant v = new CalibrationVariant();
            v.Name = name;
            v.PeakMm = peakMm;
            v.ValleyMm = valleyMm;
            v.PhasePitch = phasePitch;
            v.Profile = profile;
            v.ViewingAngleDeg = angleDeg;
            v.Note = note;
            list.Add(v);
        }

        public List<CalibrationVariant> BuildCalibrationVariants(double lpi)
        {
            List<CalibrationVariant> list = new List<CalibrationVariant>();
            string mode = state.CalibrationMode;
            string currentProfile = optics.SelectedLensProfileKind();
            double currentPhase = state.PhasePitch;
            double currentPeak = optics.PeakHeightForSelectionMm(lpi);
            double currentValley = optics.BaseHeightForSelectionMm(lpi);

            if (mode == "Thickness Test")
            {
                double[] deltas = { -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15 };
                for (int i = 0; i < deltas.Length; i++)
                {
                    double peak = currentPeak + deltas[i];
                    if (peak <= 0 || peak > optics.MaximumTopHeightMm() + 0.0001) continue;
                    double valley = optics.CalibrationValleyForPeakMm(lpi, peak);
                    if (valley < 0) continue;
                    if (valley > 0 && valley < optics.MinimumValleyHeightMm()) continue;
                    string name = "focus_" + peak.ToString("0.00", CultureInfo.InvariantCulture) + "mm";
                    AddCalibrationVariant(list, name, peak, valley, currentPhase, currentProfile, optics.ViewingAngleForPeakMm(lpi, peak), "Focused thickness sweep");
                }
            }
            else if (mode == "Viewing Test")
            {
                double[] angles = { 32.0, 35.0, 38.0, 41.0, 44.0 };
                for (int i = 0; i < angles.Length; i++)
                {
                    double peak = optics.CalibrationRawPeakForViewingAngleMm(lpi, angles[i]);
                    if (peak <= 0 || peak > optics.MaximumTopHeightMm() + 0.0001) continue;
                    double valley = optics.CalibrationValleyForPeakMm(lpi, peak);
                    if (valley < 0) continue;
                    if (valley > 0 && valley < optics.MinimumValleyHeightMm()) continue;
                    string name = "angle_" + angles[i].ToString("0", CultureInfo.InvariantCulture) + "deg";
                    AddCalibrationVariant(list, name, peak, valley, currentPhase, currentProfile, optics.ViewingAngleForPeakMm(lpi, peak), "Viewing-angle sweep");
                }
            }
            else if (mode == "Alignment Test")
            {
                double[] phases = { -0.06, -0.03, 0.0, 0.03, 0.06 };
                for (int i = 0; i < phases.Length; i++)
                {
                    string name = "phase_" + phases[i].ToString("+0.00;-0.00;0.00", CultureInfo.InvariantCulture);
                    AddCalibrationVariant(list, name, currentPeak, currentValley, currentPhase + phases[i], currentProfile, optics.ViewingAngleForPeakMm(lpi, currentPeak), "Phase sweep");
                }
            }
            else
            {
                string[] profiles = { "Mathematically Optimal Aspheric", "Aspheric", "Rounded / Circular", "Multi-facet / Prismatic", "Cosine", "Linear / Triangular (experimental)" };
                for (int i = 0; i < profiles.Length; i++)
                {
                    string name = "profile_" + SafeCalibrationName(profiles[i]);
                    AddCalibrationVariant(list, name, currentPeak, currentValley, currentPhase, profiles[i], optics.ViewingAngleForPeakMm(lpi, currentPeak), "Lens-shape comparison");
                }
            }
            return list;
        }

        public int Generate(string folder, Func<bool> cancelled)
        {
                double wi, hi; optics.GetSize(out wi, out hi);
                double lpi = optics.Positive(state.Optics.LpiText, "LPI");
                bool vertical = state.Optics.OrientationSelection == "Vertical";
                double dpiX = source.Width / wi;
                double dpiY = source.Height / hi;
                double couponMm = CalibrationCouponSizeMm();
                double fullWidthMm = wi * 25.4;
                double fullHeightMm = hi * 25.4;
                double couponWidthMm = Math.Min(couponMm, fullWidthMm);
                double couponHeightMm = Math.Min(couponMm, fullHeightMm);
                int cropW = Math.Max(8, (int)Math.Round((couponWidthMm / 25.4) * dpiX));
                int cropH = Math.Max(8, (int)Math.Round((couponHeightMm / 25.4) * dpiY));
                if (cropW > source.Width) cropW = source.Width;
                if (cropH > source.Height) cropH = source.Height;
                int cropX = Math.Max(0, (source.Width - cropW) / 2);
                int cropY = Math.Max(0, (source.Height - cropH) / 2);

                List<CalibrationVariant> variants = BuildCalibrationVariants(lpi);
                if (variants.Count == 0) throw new Exception("No calibration variants fit the current 0.30 to " + optics.MaximumTopHeightMm().ToString("0.00", CultureInfo.InvariantCulture) + " mm printer limits.");

                Directory.CreateDirectory(folder);
                    uint ppmX = PngCodec.DpiToPixelsPerMeter(dpiX);
                    uint ppmY = PngCodec.DpiToPixelsPerMeter(dpiY);
                    string sourceFile = Path.Combine(folder, "calibration_source_" + couponWidthMm.ToString("0.##", CultureInfo.InvariantCulture).Replace('.', 'p') + "x" + couponHeightMm.ToString("0.##", CultureInfo.InvariantCulture).Replace('.', 'p') + "mm.png");
                    using (Bitmap coupon = CreateCalibrationCouponBitmap(cropX, cropY, cropW, cropH))
                    {
                        coupon.SetResolution((float)dpiX, (float)dpiY);
                        coupon.Save(sourceFile, ImageFormat.Png);
                    }
                    PngCodec.SetPngPhysicalResolution(sourceFile, ppmX, ppmY);

                    string csv = Path.Combine(folder, "calibration_index.csv");
                    using (var sw = new StreamWriter(csv, false, new UTF8Encoding(false)))
                    {
                        sw.WriteLine("Variant,Source Image,Heightmap,Peak mm,Valley mm,Lens Rise mm,Viewing Angle deg,Phase pitch,Lens Shape,Note");
                        int axisPxFull = vertical ? source.Width : source.Height;
                        double axisIn = vertical ? wi : hi;
                        double axisDpi = axisPxFull / axisIn;
                        double pitchPx = axisDpi / lpi;
                        int axisCropStart = vertical ? cropX : cropY;
                        int couponAxisPx = vertical ? cropW : cropH;
                        double baseCropPhase = axisCropStart / pitchPx;

                        for (int i = 0; i < variants.Count; i++)
                        {
                            if (cancelled()) throw new OperationCanceledException();
                            CalibrationVariant v = variants[i];
                            double riseMm = Math.Max(0, v.PeakMm - v.ValleyMm);
                            double ratio = riseMm / (25.4 / lpi);
                            double baseFraction = v.PeakMm > 0 ? v.ValleyMm / v.PeakMm : 0;
                            double couponPhase = v.PhasePitch + baseCropPhase;
                            ushort[] axisVals = optics.BuildAxis(couponAxisPx, pitchPx, ratio, couponPhase, v.Profile, baseFraction);
                            string heightmapName = (i + 1).ToString("00", CultureInfo.InvariantCulture) + "_" + SafeCalibrationName(v.Name) + "_heightmap16.png";
                            string heightmapPath = Path.Combine(folder, heightmapName);
                            PngCodec.WriteGray16Png(heightmapPath, cropW, cropH, axisVals, vertical, true, ppmX, ppmY);
                            sw.WriteLine("\"" + v.Name.Replace("\"", "\"\"") + "\",\"" + Path.GetFileName(sourceFile) + "\",\"" + heightmapName + "\"," +
                                v.PeakMm.ToString("0.######", CultureInfo.InvariantCulture) + "," +
                                v.ValleyMm.ToString("0.######", CultureInfo.InvariantCulture) + "," +
                                riseMm.ToString("0.######", CultureInfo.InvariantCulture) + "," +
                                v.ViewingAngleDeg.ToString("0.######", CultureInfo.InvariantCulture) + "," +
                                v.PhasePitch.ToString("0.######", CultureInfo.InvariantCulture) + ",\"" +
                                v.Profile.Replace("\"", "\"\"") + "\",\"" + (v.Note ?? "").Replace("\"", "\"\"") + "\"");
                        }
                    }

            return variants.Count;
        }
    }
}
