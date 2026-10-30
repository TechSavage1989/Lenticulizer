using System;
using System.Collections.Generic;
using System.Drawing;
using System.Globalization;
using System.Text;

namespace Lenticulizer.Core
{
    // Established image-analysis algorithm, with explicit state and bitmap inputs.
    public static class ImageAnalysis
    {
        struct PeriodCandidate
        {
            public double PeriodPx;
            public double Score;
            public PeriodCandidate(double periodPx, double score)
            {
                PeriodPx = periodPx;
                Score = score;
            }
        }

        sealed class DetectionChoice
        {
            public string Mode;
            public double PrimaryPeriodPx;
            public double Lpi;
            public double Confidence;
        }

        public static void Analyze(ProjectState p, Bitmap source)
        {
            if (source == null) throw new ArgumentNullException("source");
            var optics = new OpticalEngine(p.Optics);
            try
            {
                double wi, hi; optics.GetSize(out wi, out hi);
                int views = 0;
                if (!string.IsNullOrWhiteSpace(p.Optics.ViewCountText) && (!int.TryParse(p.Optics.ViewCountText, out views) || views < 2)) throw new Exception("Views must be a whole number of 2 or more, or left blank.");
                bool vertical = p.Optics.OrientationSelection == "Vertical";
                int axisPx = vertical ? source.Width : source.Height;
                double axisIn = vertical ? wi : hi;
                double dpi = axisPx / axisIn;
                double manualLpi = 0;
                bool detectFromImage = p.LpiHelperMode == "Detect from image";
                bool hasManualLpi = !detectFromImage && optics.TryPositive(p.Optics.LpiText, out manualLpi);

                List<PeriodCandidate> candidates = EstimatePeriodCandidates(source, vertical);
                if (candidates.Count == 0)
                {
                    p.AnalysisText = hasManualLpi ? "Specified LPI is being used. Image analysis could not find a reliable periodic stripe pattern in the artwork." : "No reliable repeating lenticule period was detected. You can enter the known LPI by switching LPI helper to Manual.";
                    return;
                }

                if (hasManualLpi)
                {
                    double expectedFull = dpi / manualLpi;
                    double expectedSub = views >= 2 ? expectedFull / views : 0;
                    PeriodCandidate nearFull = FindBestNear(candidates, expectedFull, 0.40);
                    PeriodCandidate nearSub = views >= 2 ? FindBestNear(candidates, expectedSub, 0.40) : new PeriodCandidate(0, 0);

                    var sb = new StringBuilder();
                    sb.AppendFormat(CultureInfo.InvariantCulture, "Specified LPI: {0:0.###}. This value is authoritative.\r\n", manualLpi);
                    sb.AppendFormat(CultureInfo.InvariantCulture, "Expected full lenticule pitch: {0:0.00} px.", expectedFull);
                    if (views >= 2) sb.AppendFormat(CultureInfo.InvariantCulture, " Expected {0}-view sub-strip pitch: {1:0.00} px.", views, expectedSub);
                    if (nearFull.PeriodPx > 0) sb.AppendFormat(CultureInfo.InvariantCulture, "\r\nBest image-analysis match near full lenticule: {0:0.00} px, about {1:0.00} LPI, confidence {2:0}%.", nearFull.PeriodPx, dpi / nearFull.PeriodPx, ConfidencePercent(nearFull.Score));
                    else sb.Append("\r\nNo strong image-analysis candidate was found near the expected full lenticule pitch.");
                    if (views >= 2)
                    {
                        if (nearSub.PeriodPx > 0) sb.AppendFormat(CultureInfo.InvariantCulture, "\r\nBest image-analysis match near sub-strip: {0:0.00} px. Multiplied by {1} views, that implies {2:0.00} px/lenticule and about {3:0.00} LPI.", nearSub.PeriodPx, views, nearSub.PeriodPx * views, dpi / (nearSub.PeriodPx * views));
                        else sb.Append("\r\nNo strong image-analysis candidate was found near the expected sub-strip pitch.");
                    }
                    p.AnalysisText = sb.ToString();
                    return;
                }

                DetectionChoice choice = ChooseBestAutomaticLpi(candidates, views, dpi);
                if (choice.Lpi > 0)
                {
                    string recommendationReason;
                    double recommendedLpi = optics.RecommendWorkingLpi(choice.Lpi, out recommendationReason);
                    if (recommendedLpi <= 0) recommendedLpi = choice.Lpi;
                    p.Optics.LpiText = recommendedLpi.ToString("0.###", CultureInfo.InvariantCulture);

                    var sb = new StringBuilder();
                    sb.AppendFormat(CultureInfo.InvariantCulture, "Detected from image: likely complete lenticule pitch {0:0.00} px, measured {1:0.000} LPI. Confidence: {2:0}%.\r\n", choice.PrimaryPeriodPx, choice.Lpi, choice.Confidence * 100.0);
                    sb.AppendFormat(CultureInfo.InvariantCulture, "Recommended working LPI: {0:0.###}. {1}", recommendedLpi, recommendationReason);
                    if (views >= 2) sb.AppendFormat(CultureInfo.InvariantCulture, "\r\nWith {0} views, the expected individual view-strip width is about {1:0.00} px.", views, choice.PrimaryPeriodPx / views);
                    p.AnalysisText = sb.ToString();
                }
                else
                {
                    var top = candidates[0];
                    p.AnalysisText = string.Format(CultureInfo.InvariantCulture, "Top image-derived period candidate: {0:0.00} px, approximately {1:0.00} LPI if it is the full lenticule period. Switch to Manual if you know the exact LPI.", top.PeriodPx, dpi / top.PeriodPx);
                }
            }
            catch (Exception ex)
            {
                p.AnalysisText = "Image analysis: " + ex.Message;
            }
        }

        static DetectionChoice ChooseBestAutomaticLpi(List<PeriodCandidate> candidates, int views, double dpi)
        {
            DetectionChoice best = new DetectionChoice { Mode = "", PrimaryPeriodPx = 0, Lpi = 0, Confidence = 0 };
            double bestScore = -1;
            for (int i = 0; i < candidates.Count; i++)
            {
                PeriodCandidate full = candidates[i];
                double lpi = dpi / full.PeriodPx;
                if (lpi < 2 || lpi > 400) continue;
                double score = full.Score;

                // Prefer the smallest fundamental period when strong integer-multiple harmonics exist.
                for (int k = 2; k <= 8; k++)
                {
                    PeriodCandidate multiple = FindBestNear(candidates, full.PeriodPx * k, 0.08);
                    if (multiple.PeriodPx > 0) score += multiple.Score * (0.42 / Math.Sqrt(k));

                    PeriodCandidate divisor = FindBestNear(candidates, full.PeriodPx / k, 0.08);
                    if (divisor.PeriodPx > 0 && divisor.Score >= full.Score * 0.15) score -= divisor.Score * (0.32 / Math.Sqrt(k));
                }

                if (views >= 2)
                {
                    PeriodCandidate viewMultiple = FindBestNear(candidates, full.PeriodPx * views, 0.08);
                    if (viewMultiple.PeriodPx > 0) score += viewMultiple.Score * 0.55;

                    PeriodCandidate viewDivisor = FindBestNear(candidates, full.PeriodPx / views, 0.08);
                    if (viewDivisor.PeriodPx > 0 && viewDivisor.Score >= full.Score * 0.10) score -= viewDivisor.Score * 0.45;
                }

                double shortPenalty = full.PeriodPx < 4.0 ? 0.50 : (full.PeriodPx < 8.0 ? 0.80 : 1.0);
                score *= shortPenalty;
                if (score > bestScore)
                {
                    bestScore = score;
                    best.Mode = "full";
                    best.PrimaryPeriodPx = full.PeriodPx;
                    best.Lpi = lpi;
                    best.Confidence = NormalizeConfidence(score);
                }
            }
            return best;
        }

        static int ConfidencePercent(double rawScore)
        {
            return (int)Math.Round(NormalizeConfidence(rawScore) * 100.0);
        }

        static double NormalizeConfidence(double rawScore)
        {
            double v = rawScore;
            if (v < 0) v = 0;
            if (v > 1) v = 1;
            return v;
        }

        static PeriodCandidate FindBestNear(List<PeriodCandidate> candidates, double targetPx, double toleranceFraction)
        {
            PeriodCandidate best = new PeriodCandidate(0, 0);
            if (targetPx <= 0) return best;
            double tolerance = Math.Max(1.5, targetPx * toleranceFraction);
            double bestWeighted = -1;
            for (int i = 0; i < candidates.Count; i++)
            {
                double dist = Math.Abs(candidates[i].PeriodPx - targetPx);
                if (dist > tolerance) continue;
                double closeness = 1.0 - (dist / tolerance);
                double weighted = candidates[i].Score * (0.55 + 0.45 * closeness);
                if (weighted > bestWeighted)
                {
                    bestWeighted = weighted;
                    best = candidates[i];
                }
            }
            return best;
        }

        static List<PeriodCandidate> EstimatePeriodCandidates(Bitmap bmp, bool vertical)
        {
            int axisStep;
            double[] e = BuildEdgeSignal(bmp, vertical, out axisStep);
            var candidates = new List<PeriodCandidate>();
            if (e == null || e.Length < 32) return candidates;
            int maxLag = Math.Min(Math.Max(16, e.Length / 2), 240);
            double[] scores = new double[maxLag + 1];
            for (int lag = 2; lag <= maxLag; lag++)
            {
                double s = 0, a2 = 0, b2 = 0;
                int count = e.Length - lag;
                for (int i = 0; i < count; i++)
                {
                    double x = e[i], y = e[i + lag];
                    s += x * y;
                    a2 += x * x;
                    b2 += y * y;
                }
                double corr = (a2 > 0 && b2 > 0) ? s / Math.Sqrt(a2 * b2) : 0;
                double weight = 1.0;
                if (lag > 100) weight = 0.90;
                if (lag > 160) weight = 0.80;
                if (lag > 220) weight = 0.70;
                scores[lag] = corr * weight;
            }
            var strongLags = new List<int>();
            for (int lag = 3; lag < maxLag; lag++)
            {
                if (scores[lag] > scores[lag - 1] && scores[lag] >= scores[lag + 1] && scores[lag] >= 0.05)
                {
                    candidates.Add(new PeriodCandidate(lag * axisStep, scores[lag]));
                    strongLags.Add(lag);
                }
            }

            // A strong autocorrelation peak may be an integer harmonic of the real lenticule pitch.
            // Add supported divisors even when they are not local maxima so the selector can recover the fundamental.
            for (int si = 0; si < strongLags.Count; si++)
            {
                int strongLag = strongLags[si];
                for (int k = 2; k <= 8; k++)
                {
                    double rawDiv = (double)strongLag / k;
                    int divLag = (int)Math.Round(rawDiv);
                    if (divLag < 2 || divLag >= scores.Length) continue;
                    if (Math.Abs(rawDiv - divLag) > 0.20) continue;
                    if (scores[divLag] < 0.012) continue;
                    double periodPx = divLag * axisStep;
                    bool exists = false;
                    for (int ci = 0; ci < candidates.Count; ci++)
                    {
                        if (Math.Abs(candidates[ci].PeriodPx - periodPx) <= axisStep * 0.5) { exists = true; break; }
                    }
                    if (!exists) candidates.Add(new PeriodCandidate(periodPx, scores[divLag]));
                }
            }

            candidates.Sort(delegate(PeriodCandidate a, PeriodCandidate b) { return b.Score.CompareTo(a.Score); });
            if (candidates.Count > 24) candidates.RemoveRange(24, candidates.Count - 24);
            return candidates;
        }

        static double[] BuildEdgeSignal(Bitmap bmp, bool vertical, out int axisStep)
        {
            int axis = vertical ? bmp.Width : bmp.Height;
            int cross = vertical ? bmp.Height : bmp.Width;
            axisStep = Math.Max(1, axis / 2000);
            int crossStep = Math.Max(1, cross / 220);
            int n = (axis - 1) / axisStep;
            if (n < 32) return null;
            double[] e = new double[n];
            for (int i = 0; i < n; i++)
            {
                int a = i * axisStep;
                int b = Math.Min(axis - 1, a + axisStep);
                double sum = 0;
                int cnt = 0;
                for (int c = 0; c < cross; c += crossStep)
                {
                    Color c1 = vertical ? bmp.GetPixel(a, c) : bmp.GetPixel(c, a);
                    Color c2 = vertical ? bmp.GetPixel(b, c) : bmp.GetPixel(c, b);
                    double g1 = .299 * c1.R + .587 * c1.G + .114 * c1.B;
                    double g2 = .299 * c2.R + .587 * c2.G + .114 * c2.B;
                    sum += Math.Abs(g2 - g1);
                    cnt++;
                }
                e[i] = cnt > 0 ? sum / cnt : 0;
            }
            double mean = 0;
            for (int i = 0; i < e.Length; i++) mean += e[i];
            mean /= e.Length;
            for (int i = 0; i < e.Length; i++) e[i] -= mean;
            return e;
        }

    }
}
