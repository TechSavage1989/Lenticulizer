using System;
using System.Globalization;

namespace Lenticulizer.Core
{
    // Form-independent extraction of the accepted Alpha 16/17 algorithms.
    // Each engine has an immutable snapshot for the duration of a calculation.
    public sealed class OpticalEngine
    {
        readonly OpticalSettings settings;

        public OpticalEngine(OpticalSettings settings)
        {
            if (settings == null) throw new ArgumentNullException("settings");
            this.settings = settings.Snapshot();
        }

        public int ReliefBaselineViewCount()
        {
            return 2;
        }

        public void ValidateLensFreeViewConfigurationForBuild()
        {
            if (!IsLensFreeMode()) return;
            if (settings.FrameCount != ReliefBaselineViewCount())
                throw new Exception("Lens-Free Relief currently supports exactly 2 source images using the eufyMake-style naked-eye prism baseline. Add one left-view image and one right-view image.");
        }

        public void ValidateLensFreeViewConfigurationForGeneration()
        {
            if (!IsLensFreeMode()) return;
            int views = GetEffectiveViewCount();
            if (views != ReliefBaselineViewCount())
                throw new Exception("Lens-Free Relief currently supports exactly 2 views in this corrected baseline mode. Use a 2-view color map or rebuild from 2 source images.");
        }

        public int GetEffectiveViewCount()
        {
            int views;
            if (int.TryParse(settings.ViewCountText, out views) && views >= 2) return views;
            if (settings.FrameCount >= 2) return settings.FrameCount;
            return 3;
        }

        public int GetSelectedPrinterDpi()
        {
            int dpi;
            if (!int.TryParse(settings.PrinterDpiSelection, NumberStyles.Integer, CultureInfo.InvariantCulture, out dpi) || dpi <= 0) dpi = 1440;
            return dpi;
        }

        public int SnapPixelsPerLenticule(double value, int views)
        {
            if (double.IsNaN(value) || double.IsInfinity(value) || value <= 0) value = 48;
            int step = Math.Max(1, views);
            int rounded = (int)Math.Round(value / step) * step;
            if (rounded < step * 4) rounded = step * 4;
            if (rounded < 24) rounded = 24;
            if (rounded > 256) rounded = 256;
            return rounded;
        }

        public int[] GetCommonLpiOptions()
        {
            return new[] { 10, 15, 20, 25, 30, 35, 40, 50, 60, 75, 100 };
        }

        public int FindNearestCommonLpi(double target, int[] options)
        {
            int best = options[0];
            double bestDist = Math.Abs(best - target);
            for (int i = 1; i < options.Length; i++)
            {
                double d = Math.Abs(options[i] - target);
                if (d < bestDist)
                {
                    best = options[i];
                    bestDist = d;
                }
            }
            return best;
        }

        public double RoundToIncrement(double value, double increment)
        {
            if (increment <= 0) return value;
            return Math.Round(value / increment, MidpointRounding.AwayFromZero) * increment;
        }

        public double RecommendWorkingLpi(double detectedLpi, out string recommendationReason)
        {
            recommendationReason = "";
            if (detectedLpi <= 0) return 0;

            int[] standards = GetCommonLpiOptions();
            int nearestStandard = FindNearestCommonLpi(detectedLpi, standards);
            double absDelta = Math.Abs(detectedLpi - nearestStandard);
            double relDelta = absDelta / detectedLpi;

            if (absDelta <= 0.35 || relDelta <= 0.0075)
            {
                recommendationReason = "Likely nominal standard LPI: " + nearestStandard.ToString(CultureInfo.InvariantCulture) + ".";
                return nearestStandard;
            }

            double halfStep = RoundToIncrement(detectedLpi, 0.5);
            if (Math.Abs(detectedLpi - halfStep) <= 0.05)
            {
                recommendationReason = "No close common standard was found. Using the nearest half-step working LPI.";
                return halfStep;
            }

            double tenthStep = RoundToIncrement(detectedLpi, 0.1);
            if (Math.Abs(detectedLpi - tenthStep) <= 0.025)
            {
                recommendationReason = "No close common standard was found. Using the nearest tenth-step working LPI.";
                return tenthStep;
            }

            recommendationReason = "No close nominal standard was found. Using the detected exact LPI.";
            return Math.Round(detectedLpi, 3, MidpointRounding.AwayFromZero);
        }

        public int SnapPplToViewMultiple(int value, int views)
        {
            int step = Math.Max(1, views);
            int rounded = (int)Math.Round(value / (double)step, MidpointRounding.AwayFromZero) * step;
            if (rounded < step * 4) rounded = step * 4;
            if (rounded < 24) rounded = 24;
            if (rounded > 256) rounded = 256;
            return rounded;
        }

        public double ExactLpiForPixelsPerLenticule(int printerDpi, int ppl)
        {
            if (printerDpi <= 0 || ppl <= 0) return 0;
            return printerDpi / (double)ppl;
        }

        public void GetRecommendedLpiTargets(int printerDpi, int views, out double easierLpi, out int easierPpl, out double balancedLpi, out int balancedPpl, out double finerLpi, out int finerPpl)
        {
            if (IsLensFreeMode())
            {
                int reliefViews = ReliefBaselineViewCount();
                easierPpl = SnapPplToViewMultiple(112, reliefViews);
                balancedPpl = SnapPplToViewMultiple(84, reliefViews);
                finerPpl = SnapPplToViewMultiple(56, reliefViews);
            }
            else
            {
                easierPpl = SnapPplToViewMultiple(60, views);
                balancedPpl = SnapPplToViewMultiple(40, views);
                finerPpl = SnapPplToViewMultiple(24, views);
            }
            easierLpi = ExactLpiForPixelsPerLenticule(printerDpi, easierPpl);
            balancedLpi = ExactLpiForPixelsPerLenticule(printerDpi, balancedPpl);
            finerLpi = ExactLpiForPixelsPerLenticule(printerDpi, finerPpl);
        }

        public string CurrentSettingsMode()
        {
            return settings.SettingsModeSelection;
        }

        public bool IsAutomaticSettingsMode()
        {
            return CurrentSettingsMode() == "Automatic";
        }

        public bool IsSemiAutomaticSettingsMode()
        {
            return CurrentSettingsMode() == "Semi-Automatic";
        }

        public bool IsManualSettingsMode()
        {
            return CurrentSettingsMode() == "Manual";
        }

        public string CurrentPrintProfileKind()
        {
            string text = settings.PrintProfileSelection;
            if (text.StartsWith("Lower Thickness", StringComparison.OrdinalIgnoreCase)) return "LOWER";
            if (text.StartsWith("Mathematically Optimal", StringComparison.OrdinalIgnoreCase)) return "THEORETICAL";
            if (text.StartsWith("Higher Thickness", StringComparison.OrdinalIgnoreCase)) return "HIGHER";
            if (text.StartsWith("Manual Thickness", StringComparison.OrdinalIgnoreCase)) return "MANUAL";
            return "REFERENCE";
        }

        public string CurrentBaseModeKind()
        {
            string text = settings.BaseModeSelection;
            if (text.StartsWith("Mathematically Optimal", StringComparison.OrdinalIgnoreCase)) return "THEORETICAL";
            if (text.StartsWith("No base", StringComparison.OrdinalIgnoreCase)) return "NONE";
            if (text.StartsWith("Printer minimum", StringComparison.OrdinalIgnoreCase)) return "MINIMUM";
            if (text.StartsWith("Raised base", StringComparison.OrdinalIgnoreCase)) return "RAISED";
            if (text.StartsWith("Manual base height", StringComparison.OrdinalIgnoreCase)) return "MANUAL";
            return "REFERENCE";
        }

        public bool LensSelectionRequestsMathematicalOptics()
        {
            if (IsLensFreeMode()) return false;
            string text = settings.LensProfileSelection;
            return text.StartsWith("Auto Mathematically Optimal", StringComparison.OrdinalIgnoreCase) ||
                   text.StartsWith("Mathematically Optimal Aspheric", StringComparison.OrdinalIgnoreCase);
        }

        public bool UseMathematicallyOptimalOptics()
        {
            // Lens Type is the authoritative optical basis. Print/Base selectors can
            // still be overridden in Semi-Automatic or Manual mode without silently
            // changing the selected lens surface family.
            return LensSelectionRequestsMathematicalOptics();
        }

        public string ViewingAngleSelectionKind()
        {
            string value = settings.ViewingAngleSelection;
            if (string.IsNullOrWhiteSpace(value)) return "STANDARD";
            value = value.Trim();
            if (value.StartsWith("Custom", StringComparison.OrdinalIgnoreCase)) return "CUSTOM";
            if (value.StartsWith("Narrow", StringComparison.OrdinalIgnoreCase)) return "NARROW";
            if (value.StartsWith("Extra Wide", StringComparison.OrdinalIgnoreCase)) return "EXTRA_WIDE";
            if (value.StartsWith("Wide", StringComparison.OrdinalIgnoreCase)) return "WIDE";
            if (value.StartsWith("Recommended", StringComparison.OrdinalIgnoreCase)) return "STANDARD";
            return "STANDARD";
        }

        public string ViewingAngleSelectionLabel()
        {
            string kind = ViewingAngleSelectionKind();
            if (kind == "NARROW") return "Narrow";
            if (kind == "WIDE") return "Wide";
            if (kind == "EXTRA_WIDE") return "Extra Wide";
            if (kind == "CUSTOM") return "Custom";
            return "Standard";
        }

        public bool IsCustomViewingAngleMode()
        {
            return ViewingAngleSelectionKind() == "CUSTOM";
        }

        public double CustomViewingAngleDeg()
        {
            double angle;
            string value = settings.CustomViewingAngleText.Trim();
            if (!double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out angle) || double.IsNaN(angle) || double.IsInfinity(angle) || angle <= 0.0 || angle >= 179.0)
                throw new Exception("Custom viewing angle must be greater than 0 and less than 179 degrees.");
            return angle;
        }

        public double ViewingAnglePresetFactor()
        {
            string kind = ViewingAngleSelectionKind();
            if (UseMathematicallyOptimalOptics())
            {
                if (kind == "NARROW") return 0.70;
                if (kind == "STANDARD") return 0.82;
                if (kind == "WIDE") return 0.92;
                if (kind == "EXTRA_WIDE") return 0.98;
                return 1.00;
            }
            if (kind == "NARROW") return 0.85;
            if (kind == "WIDE") return 1.10;
            if (kind == "EXTRA_WIDE") return 1.18;
            return 1.00;
        }

        public double ProfileValueNormalized(string profile, double phase, double lpi, double peakMm, double baseMm)
        {
            phase -= Math.Floor(phase);
            double pitchMm = 25.4 / Math.Max(0.001, lpi);
            double a = pitchMm / 2.0;
            double x = (phase - 0.5) * pitchMm;
            double rise = Math.Max(0.000001, peakMm - baseMm);
            double R = (a * a + rise * rise) / (2.0 * rise);
            if (profile == "Reference Calibrated")
            {
                double u = 1.0 - Math.Min(1.0, Math.Abs(x) / a);
                return ReferenceProfileZ(u);
            }
            if (profile == "Lens-Free Relief")
            {
                return ReliefProfileNormalized(phase);
            }
            if (profile == "Cosine")
                return 0.5 * (1.0 + Math.Cos(Math.PI * Math.Max(-1.0, Math.Min(1.0, x / a))));
            if (profile == "Linear / Triangular (experimental)")
                return 1.0 - Math.Min(1.0, Math.Abs(x) / a);
            if (profile == "Aspheric")
            {
                double nIndex = RefractiveIndex();
                double k = -1.0 / (nIndex * nIndex);
                double edgeSag = ConicSag(a, R, k);
                double xSag = ConicSag(Math.Abs(x), R, k);
                if (edgeSag <= 0.0000001) return CircularProfileZ(x, R, rise);
                return 1.0 - Math.Max(0.0, Math.Min(1.0, xSag / edgeSag));
            }
            if (profile == "Multi-facet / Prismatic")
            {
                double u = Math.Min(1.0, Math.Abs(x) / a);
                int facets = Math.Max(4, GetEffectiveViewCount() * 2);
                double fp = u * facets;
                int fi = (int)Math.Floor(fp);
                if (fi >= facets) fi = facets - 1;
                double local = fp - fi;
                double x0 = ((double)fi / facets) * a;
                double x1 = ((double)(fi + 1) / facets) * a;
                double z0 = CircularProfileZ(x0, R, rise);
                double z1 = CircularProfileZ(x1, R, rise);
                return z0 + (z1 - z0) * local;
            }
            return CircularProfileZ(x, R, rise);
        }

        public double ProfileRmsSurfaceSlope(string profile, double lpi, double peakMm, double baseMm)
        {
            double pitchMm = 25.4 / Math.Max(0.001, lpi);
            double riseMm = Math.Max(0.000000001, peakMm - baseMm);
            const int samples = 64;
            double lastPhase = 0.02;
            double lastZ = ProfileValueNormalized(profile, lastPhase, lpi, peakMm, baseMm);
            double sumSq = 0.0;
            int count = 0;
            for (int i = 1; i <= samples; i++)
            {
                double phase = 0.02 + 0.96 * i / samples;
                double z = ProfileValueNormalized(profile, phase, lpi, peakMm, baseMm);
                double dphase = Math.Max(0.000000001, phase - lastPhase);
                double slope = ((z - lastZ) * riseMm) / (dphase * pitchMm);
                sumSq += slope * slope;
                count++;
                lastPhase = phase;
                lastZ = z;
            }
            return Math.Sqrt(sumSq / Math.Max(1, count));
        }

        public double ProfileGeometryFactor(double lpi)
        {
            string profile = SelectedLensProfileKind();
            if (profile == "Reference Calibrated" || profile == "Mathematically Optimal Aspheric" || profile == "Lens-Free Relief") return 1.0;
            double referencePeak = Math.Min(MaximumTopHeightMm(), Math.Max(MinimumValleyHeightMm(), ReferenceScaledPeakMm(lpi)));
            double referenceBase = ReferenceRecommendedBaseHeightMm(lpi, referencePeak);
            double referenceSlope = ProfileRmsSurfaceSlope("Reference Calibrated", lpi, referencePeak, referenceBase);
            double profileSlope = ProfileRmsSurfaceSlope(profile, lpi, referencePeak, referenceBase);
            if (referenceSlope <= 0.000000001 || profileSlope <= 0.000000001) return 1.0;
            return Math.Max(0.65, Math.Min(1.60, referenceSlope / profileSlope));
        }

        public double PeakForViewingAngleMm(double lpi, double angleDeg)
        {
            double n = RefractiveIndex();
            double a = (25.4 / Math.Max(0.001, lpi)) / 2.0;
            double halfRadians = angleDeg * Math.PI / 360.0;
            if (IsLensFreeMode())
                return ReliefPeakForViewingAngleMm(lpi, angleDeg);
            if (UseMathematicallyOptimalOptics())
            {
                double s = Math.Sin(halfRadians) / n;
                if (s <= 0.000000000001) return MaximumTopHeightMm() + 1.0;
                if (s >= 1.0) s = 0.999999999;
                return a * Math.Sqrt(Math.Max(0.0, 1.0 - s * s)) / s;
            }
            double tangent = Math.Tan(halfRadians);
            if (Math.Abs(tangent) < 0.000000000001) return MaximumTopHeightMm() + 1.0;
            return (n * a / tangent) * ProfileGeometryFactor(lpi);
        }

        public double ReferenceViewingAngleForPeakMm(double lpi, double peakMm)
        {
            double n = RefractiveIndex();
            double a = (25.4 / Math.Max(0.001, lpi)) / 2.0;
            if (peakMm <= 0) return 0;
            return 2.0 * Math.Atan((n * a) / peakMm) * 180.0 / Math.PI;
        }

        public double MathematicalMaximumFeasibleViewingAngleDeg(double lpi)
        {
            double peak = TheoreticalOptimalPeakMm(lpi);
            if (peak > MaximumTopHeightMm()) peak = MaximumTopHeightMm();
            if (peak <= 0) peak = MaximumTopHeightMm();
            return TheoreticalViewingAngleForPeakMm(lpi, peak);
        }

        public double MathematicalMinimumFeasibleViewingAngleDeg(double lpi)
        {
            return TheoreticalViewingAngleForPeakMm(lpi, MaximumTopHeightMm());
        }

        public double ReferenceStandardViewingAngleDeg(double lpi)
        {
            double peak = PeakTargetWithoutViewingAngleMm(lpi);
            if (peak < MinimumValleyHeightMm()) peak = MinimumValleyHeightMm();
            if (peak > MaximumTopHeightMm()) peak = MaximumTopHeightMm();
            return ReferenceViewingAngleForPeakMm(lpi, peak);
        }

        public double ReferenceMaximumRecommendedViewingAngleDeg(double lpi)
        {
            double standardPeak = PeakTargetWithoutViewingAngleMm(lpi);
            if (standardPeak < MinimumValleyHeightMm()) standardPeak = MinimumValleyHeightMm();
            double widePeak = Math.Max(MinimumValleyHeightMm(), standardPeak * 0.75);
            return ReferenceViewingAngleForPeakMm(lpi, widePeak);
        }

        public double BaseRecommendedViewingAngleDeg(double lpi)
        {
            if (UseMathematicallyOptimalOptics())
                return MathematicalMaximumFeasibleViewingAngleDeg(lpi) * 0.82;
            return ReferenceStandardViewingAngleDeg(lpi);
        }

        public double RecommendedViewingAngleDeg(double lpi)
        {
            return BaseRecommendedViewingAngleDeg(lpi);
        }

        public double TargetViewingAngleDegForSelection(double lpi)
        {
            if (IsLensFreeMode()) return ReliefViewingSpreadDeg(lpi, ReliefPrismHeightMm());
            if (IsCustomViewingAngleMode()) return CustomViewingAngleDeg();
            string kind = ViewingAngleSelectionKind();
            double target;
            if (UseMathematicallyOptimalOptics())
            {
                double maximum = MathematicalMaximumFeasibleViewingAngleDeg(lpi);
                double minimum = MathematicalMinimumFeasibleViewingAngleDeg(lpi);
                target = maximum * ViewingAnglePresetFactor();
                if (target < minimum) target = minimum;
                if (target > maximum) target = maximum;
            }
            else
            {
                double standard = ReferenceStandardViewingAngleDeg(lpi);
                double maximum = ReferenceMaximumRecommendedViewingAngleDeg(lpi);
                target = standard * ViewingAnglePresetFactor();
                if (target > maximum) target = maximum;
                double minimum = ReferenceViewingAngleForPeakMm(lpi, MaximumTopHeightMm());
                if (target < minimum) target = minimum;
            }
            if (target <= 1.0) target = 1.0;
            if (target >= 178.9) target = 178.9;
            return target;
        }

        public string RecommendLensProfileKind(out string reason)
        {
            if (UseMathematicallyOptimalOptics())
            {
                double lpiValue;
                if (!TryPositive(settings.LpiText, out lpiValue)) lpiValue = 35.0;
                reason = "Using a first-principles aplanatic aspheric surface calculated from physical lenticule pitch and clear-resin IOR. No empirical reference-calibration dimensions are used.";
                return "Mathematically Optimal Aspheric";
            }
            double calibrationLpi;
            if (UseKnownGoodReferenceCalibration() && TryPositive(settings.LpiText, out calibrationLpi) && GetEffectiveViewCount() == 3 && calibrationLpi >= 12 && calibrationLpi <= 40)
            {
                reason = "Using the measured cross-section from the known-good 15 LPI / 1.86 mm / 3-view UV print and scaling it by physical lens pitch. " + ReferenceCalibrationConfidence(calibrationLpi);
                return "Reference Calibrated";
            }
            int views = GetEffectiveViewCount();
            double lpi;
            if (!TryPositive(settings.LpiText, out lpi)) lpi = 35.0;

            double pixelsPerLens;
            if (!TryPositive(settings.PixelsPerLenticuleText, out pixelsPerLens))
                pixelsPerLens = Math.Max(8.0, (double)GetSelectedPrinterDpi() / lpi);

            double axisMm = 60.0;
            double lensCount = 0.0;
            try
            {
                double wi, hi; GetSize(out wi, out hi);
                bool vertical = settings.OrientationSelection == "Vertical";
                axisMm = (vertical ? wi : hi) * 25.4;
                lensCount = (axisMm / 25.4) * lpi;
            }
            catch
            {
                lensCount = (axisMm / 25.4) * lpi;
            }

            string result;
            if (views <= 2)
            {
                if (pixelsPerLens >= 40 && lpi <= 75)
                {
                    result = "Multi-facet / Prismatic";
                    reason = "Two views can benefit from directional facets, and the current raster has enough samples per lens.";
                }
                else
                {
                    result = "Rounded / Circular";
                    reason = "Two-view project with limited raster detail; the conventional circular profile is the more robust starting point.";
                }
            }
            else if (views <= 5)
            {
                if (pixelsPerLens >= 22)
                {
                    result = "Aspheric";
                    reason = "Three to five views need better off-axis control; aspheric is preferred to reduce edge aberration and crosstalk.";
                }
                else
                {
                    result = "Rounded / Circular";
                    reason = "The raster has relatively few pixels per lens, so the simpler circular profile is safer than a more complex surface.";
                }
            }
            else
            {
                if (pixelsPerLens >= Math.Max(32, views * 5))
                {
                    result = "Aspheric";
                    reason = "High view count needs improved off-axis control and the current raster has enough lens samples for an aspheric surface.";
                }
                else
                {
                    result = "Rounded / Circular";
                    reason = "High view count but limited pixels per lens; a simpler profile is less likely to be lost to raster sampling.";
                }
            }

            if (lpi >= 100 && pixelsPerLens < 20)
            {
                result = "Rounded / Circular";
                reason = "High LPI with low pixels per lens favors the simplest reliably printable curved profile.";
            }

            if (lensCount > 0 && lensCount < 12 && views <= 2 && pixelsPerLens >= 40)
            {
                result = "Multi-facet / Prismatic";
                reason = "This small print has relatively few physical lenses and only two views, making a directional faceted profile a reasonable starting point.";
            }

            reason += " Project: " + views.ToString(CultureInfo.InvariantCulture) + " views, " + lpi.ToString("0.###", CultureInfo.InvariantCulture) + " LPI, about " + pixelsPerLens.ToString("0", CultureInfo.InvariantCulture) + " px/lens" + (lensCount > 0 ? ", about " + lensCount.ToString("0", CultureInfo.InvariantCulture) + " lenses across the viewing axis." : ".");
            return result;
        }

        public string SelectedLensProfileKind()
        {
            if (IsLensFreeMode()) return "Lens-Free Relief";
            if (!settings.HasLensProfile) return "Reference Calibrated";
            int index = settings.LensProfileIndex;
            if (index <= 0)
            {
                string reason;
                return RecommendLensProfileKind(out reason);
            }
            if (index == 1) return "Mathematically Optimal Aspheric";
            if (index == 2) return "Reference Calibrated";
            if (index == 3) return "Mathematically Optimal Aspheric";
            if (index == 4) return "Aspheric";
            if (index == 5) return "Rounded / Circular";
            if (index == 6) return "Multi-facet / Prismatic";
            if (index == 7) return "Linear / Triangular (experimental)";
            return "Cosine";
        }

        public double Positive(string s, string name)
        {
            double v;
            if (!double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out v) || v <= 0 || double.IsNaN(v) || double.IsInfinity(v)) throw new Exception(name + " must be a number greater than zero.");
            return v;
        }

        public double NonNegative(string s, string name)
        {
            double v;
            if (!double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out v) || v < 0 || double.IsNaN(v) || double.IsInfinity(v)) throw new Exception(name + " must be zero or greater.");
            return v;
        }

        public bool TryPositive(string s, out double v)
        {
            return double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out v) && v > 0 && !double.IsNaN(v) && !double.IsInfinity(v);
        }

        public void GetSize(out double wi, out double hi)
        {
            wi = Positive(settings.WidthText, "Width");
            hi = Positive(settings.HeightText, "Height");
            if (settings.SizeUnitSelection == "mm")
            {
                wi /= 25.4;
                hi /= 25.4;
            }
        }

        public double MinimumValleyHeightMm()
        {
            return 0.30;
        }

        public double MaximumTopHeightMm()
        {
            return 5.00;
        }

        public bool IsLensFreeMode()
        {
            return string.Equals(settings.OutputModeSelection, "Lens-Free Relief", StringComparison.OrdinalIgnoreCase);
        }

        public string CurrentOutputModeLabel()
        {
            return IsLensFreeMode() ? "Lens-Free Relief" : "Lenticular Lens";
        }

        public double ReliefPrismHeightMm()
        {
            double value = Positive(settings.ReliefPrismHeightText, "Prism Height");
            if (value < MinimumValleyHeightMm() - 0.000001)
                throw new Exception("Prism Height must be at least " + MinimumValleyHeightMm().ToString("0.00", CultureInfo.InvariantCulture) + " mm.");
            if (value > MaximumTopHeightMm() + 0.000001)
                throw new Exception("Prism Height cannot exceed the printer maximum of " + MaximumTopHeightMm().ToString("0.00", CultureInfo.InvariantCulture) + " mm.");
            return value;
        }

        public double RecommendedReliefPrismHeightMm(double lpi)
        {
            double pitchMm = 25.4 / Math.Max(0.001, lpi);
            double halfPitchMm = pitchMm * 0.5;
            double height = halfPitchMm * Math.Tan(30.0 * Math.PI / 180.0);
            if (height < MinimumValleyHeightMm()) height = MinimumValleyHeightMm();
            if (height > MaximumTopHeightMm()) height = MaximumTopHeightMm();
            return height;
        }

        public double[] ReliefNormalizedBoundaries()
        {
            int views = Math.Max(2, GetEffectiveViewCount());
            double center = (views - 1) * 0.5;
            double[] heights = new double[views + 1];
            heights[0] = 0.0;
            for (int i = 0; i < views; i++)
                heights[i + 1] = heights[i] + (center - i);
            double drift = heights[views] - heights[0];
            if (Math.Abs(drift) > 0.000000000001)
                for (int i = 0; i <= views; i++) heights[i] -= drift * i / Math.Max(1.0, views);
            double lo = heights[0], hi = heights[0];
            for (int i = 1; i < heights.Length; i++) { if (heights[i] < lo) lo = heights[i]; if (heights[i] > hi) hi = heights[i]; }
            double span = hi - lo;
            if (span <= 0.000000000001) return heights;
            for (int i = 0; i < heights.Length; i++) heights[i] = (heights[i] - lo) / span;
            return heights;
        }

        public double ReliefProfileNormalized(double phase)
        {
            phase -= Math.Floor(phase);
            int views = Math.Max(2, GetEffectiveViewCount());
            double[] boundaries = ReliefNormalizedBoundaries();
            double fp = phase * views;
            int facet = (int)Math.Floor(fp);
            if (facet >= views) facet = views - 1;
            double local = fp - facet;
            return boundaries[facet] + (boundaries[facet + 1] - boundaries[facet]) * local;
        }

        public double[] ReliefFacetAnglesDeg(double lpi, double prismHeightMm)
        {
            int views = Math.Max(2, GetEffectiveViewCount());
            double pitchMm = 25.4 / Math.Max(0.001, lpi);
            double facetWidthMm = pitchMm / views;
            double[] b = ReliefNormalizedBoundaries();
            double[] angles = new double[views];
            for (int i = 0; i < views; i++)
            {
                double dz = (b[i + 1] - b[i]) * prismHeightMm;
                double slope = dz / Math.Max(0.000000000001, facetWidthMm);
                angles[i] = -Math.Atan(slope) * 180.0 / Math.PI;
            }
            return angles;
        }

        public double ReliefViewingSpreadDeg(double lpi, double prismHeightMm)
        {
            double[] a = ReliefFacetAnglesDeg(lpi, prismHeightMm);
            double lo = a[0], hi = a[0];
            for (int i = 1; i < a.Length; i++) { if (a[i] < lo) lo = a[i]; if (a[i] > hi) hi = a[i]; }
            return hi - lo;
        }

        public double ReliefAverageAdjacentAngleDeg(double lpi, double prismHeightMm)
        {
            double[] a = ReliefFacetAnglesDeg(lpi, prismHeightMm);
            Array.Sort(a);
            if (a.Length < 2) return 0.0;
            double total = 0.0;
            for (int i = 0; i < a.Length - 1; i++) total += a[i + 1] - a[i];
            return total / (a.Length - 1);
        }

        public double ReliefViewingAngleForPeakMm(double lpi, double peakMm)
        {
            return ReliefViewingSpreadDeg(lpi, peakMm);
        }

        public double ReliefPeakForViewingAngleMm(double lpi, double angleDeg)
        {
            double target = Math.Max(0.0, Math.Min(179.0, angleDeg));
            double low = MinimumValleyHeightMm();
            double high = MaximumTopHeightMm();
            if (ReliefViewingSpreadDeg(lpi, low) >= target) return low;
            if (ReliefViewingSpreadDeg(lpi, high) < target) return high + 1.0;
            for (int i = 0; i < 60; i++)
            {
                double mid = (low + high) / 2.0;
                if (ReliefViewingSpreadDeg(lpi, mid) >= target) high = mid; else low = mid;
            }
            return high;
        }

        public bool UseKnownGoodReferenceCalibration()
        {
            return !IsLensFreeMode() && !UseMathematicallyOptimalOptics();
        }

        public double ReferenceCalibrationLpi()
        {
            return 15.0;
        }

        public double ReferenceCalibrationPeakMm()
        {
            return 1.86;
        }

        public double ReferenceCalibrationValleyMm()
        {
            return 1.18;
        }

        public double ReferenceCalibrationRiseMm()
        {
            return ReferenceCalibrationPeakMm() - ReferenceCalibrationValleyMm();
        }

        public double ReferenceScaleForLpi(double lpi)
        {
            if (lpi <= 0) return 1.0;
            return ReferenceCalibrationLpi() / lpi;
        }

        public double ReferenceScaledPeakMm(double lpi)
        {
            return ReferenceCalibrationPeakMm() * ReferenceScaleForLpi(lpi);
        }

        public double ReferenceScaledValleyMm(double lpi)
        {
            return ReferenceCalibrationValleyMm() * ReferenceScaleForLpi(lpi);
        }

        public double ReferenceScaledRiseMm(double lpi)
        {
            return ReferenceCalibrationRiseMm() * ReferenceScaleForLpi(lpi);
        }

        public string ReferenceCalibrationConfidence(double lpi)
        {
            int views = GetEffectiveViewCount();
            double delta = Math.Abs(lpi - ReferenceCalibrationLpi());
            if (views == 3 && delta <= 1.0) return "Matches the working calibration reference closely.";
            if (views == 3 && lpi >= 12 && lpi <= 25) return "Recommended settings based on the working 15 LPI reference.";
            if (views == 3 && lpi > 25 && lpi <= 40) return "Recommended settings calculated from the working reference. Calibration coupon recommended.";
            return "Recommended starting settings calculated from the working reference. Calibration coupon recommended.";
        }

        public double ReferenceProfileZ(double u)
        {
            // Normalized cross-section measured from the supplied known-good heightmap.
            // u = 0 at valley/edge and 1 at the lens center/peak.
            double[] samples = { 0.0000, 0.1700, 0.4200, 0.5400, 0.6300, 0.7000, 0.7500, 0.8000, 0.8400, 0.8800, 0.9100, 0.9300, 0.9500, 0.9650, 0.9800, 0.9900, 1.0000 };
            if (u <= 0) return samples[0];
            if (u >= 1) return samples[samples.Length - 1];
            double fp = u * (samples.Length - 1);
            int i = (int)Math.Floor(fp);
            if (i >= samples.Length - 1) return samples[samples.Length - 1];
            double t = fp - i;
            return samples[i] + (samples[i + 1] - samples[i]) * t;
        }

        public double RefractiveIndex()
        {
            double n;
            string value = settings.RefractiveIndexText.Trim();
            if (!double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out n) || double.IsNaN(n) || double.IsInfinity(n) || n <= 1.0 || n > 3.0) n = 1.55;
            return n;
        }

        public double Wrap01(double value)
        {
            if (double.IsNaN(value) || double.IsInfinity(value)) return 0.0;
            value = value - Math.Floor(value);
            if (value < 0.0) value += 1.0;
            if (value >= 1.0) value -= Math.Floor(value);
            return value;
        }

        public double ReverseInterlacePhase(double phase)
        {
            return Wrap01(1.0 - 1e-9 - phase);
        }

        public void GetPhysicalViewBlend(double phase, int views, out int frameAIndex, out int frameBIndex, out double viewBlend)
        {
            double mappedPhase = Wrap01(phase);
            double fp = mappedPhase * views - 0.5;
            int baseIndex = (int)Math.Floor(fp);
            viewBlend = fp - Math.Floor(fp);
            frameAIndex = ((baseIndex % views) + views) % views;
            frameBIndex = (((baseIndex + 1) % views) + views) % views;
        }

        public double TheoreticalMinimumPeakMm(double lpi)
        {
            double n = RefractiveIndex();
            double a = (25.4 / Math.Max(0.001, lpi)) / 2.0;
            return a * Math.Sqrt((n + 1.0) / (n - 1.0));
        }

        public double TheoreticalSurfaceHeightMm(double lpi, double peakMm, double xMm)
        {
            double n = RefractiveIndex();
            double c = (n - 1.0) * peakMm;
            double n2m1 = n * n - 1.0;
            double disc = c * c - n2m1 * xMm * xMm;
            if (disc < -0.000000001) return -1.0;
            if (disc < 0) disc = 0;
            return (c + n * Math.Sqrt(disc)) / n2m1;
        }

        public double TheoreticalBaseForPeakMm(double lpi, double peakMm)
        {
            double a = (25.4 / Math.Max(0.001, lpi)) / 2.0;
            return TheoreticalSurfaceHeightMm(lpi, peakMm, a);
        }

        public double TheoreticalOptimalPeakMm(double lpi)
        {
            double minimum = TheoreticalMinimumPeakMm(lpi);
            if (minimum > MaximumTopHeightMm() + 0.0000001) return minimum;

            double valley = TheoreticalBaseForPeakMm(lpi, minimum);
            if (valley < 0) return minimum;
            if (valley >= MinimumValleyHeightMm()) return minimum;

            double high = MaximumTopHeightMm();
            double highValley = TheoreticalBaseForPeakMm(lpi, high);
            if (highValley < MinimumValleyHeightMm()) return high + 1.0;

            double low = minimum;
            for (int i = 0; i < 60; i++)
            {
                double mid = (low + high) / 2.0;
                if (TheoreticalBaseForPeakMm(lpi, mid) >= MinimumValleyHeightMm()) high = mid;
                else low = mid;
            }
            return high;
        }

        public double TheoreticalOptimalBaseMm(double lpi, double peakMm)
        {
            double baseMm = TheoreticalBaseForPeakMm(lpi, peakMm);
            if (baseMm < 0) return -1.0;
            if (baseMm > 0 && baseMm < MinimumValleyHeightMm()) return MinimumValleyHeightMm();
            return Math.Min(peakMm, Math.Max(0.0, baseMm));
        }

        public double TheoreticalViewingAngleForPeakMm(double lpi, double peakMm)
        {
            double n = RefractiveIndex();
            double a = (25.4 / Math.Max(0.001, lpi)) / 2.0;
            if (peakMm <= 0) return 0;
            double sinInside = a / Math.Sqrt(a * a + peakMm * peakMm);
            double sinOutside = n * sinInside;
            if (sinOutside >= 1.0) sinOutside = 0.999999999;
            if (sinOutside <= -1.0) sinOutside = -0.999999999;
            return 2.0 * Math.Asin(sinOutside) * 180.0 / Math.PI;
        }

        public string TheoreticalOpticsSummary(double lpi)
        {
            double ideal = TheoreticalMinimumPeakMm(lpi);
            double printable = TheoreticalOptimalPeakMm(lpi);
            if (printable > MaximumTopHeightMm() + 0.0001)
                return "Theoretical full-aperture optimum is " + printable.ToString("0.00", CultureInfo.InvariantCulture) + " mm and exceeds the 5.00 mm print-height limit.";
            double valley = TheoreticalOptimalBaseMm(lpi, printable);
            string constraint = printable > ideal + 0.0005 ? " Printer minimum valley increased the optical minimum from " + ideal.ToString("0.00", CultureInfo.InvariantCulture) + " mm." : " Uses the full-aperture optical minimum.";
            return "Mathematical optimum: " + printable.ToString("0.00", CultureInfo.InvariantCulture) + " mm peak, " + valley.ToString("0.00", CultureInfo.InvariantCulture) + " mm valley." + constraint;
        }

        public void ValidateTheoreticalProfileGeometry(double lpi, double peakMm)
        {
            if (!string.Equals(SelectedLensProfileKind(), "Mathematically Optimal Aspheric", StringComparison.Ordinal)) return;
            double minimum = TheoreticalMinimumPeakMm(lpi);
            if (minimum > MaximumTopHeightMm() + 0.0001)
                throw new Exception("The mathematically optimal full-aperture lens requires " + minimum.ToString("0.00", CultureInfo.InvariantCulture) + " mm peak height at this LPI and IOR, which exceeds the 5.00 mm printer limit. Choose a higher LPI, a different optical mode, or change the material IOR.");
            if (peakMm + 0.000001 < minimum)
                throw new Exception("The selected Thickness is below the full-aperture mathematical minimum of " + minimum.ToString("0.00", CultureInfo.InvariantCulture) + " mm for this LPI and IOR.");
            if (IsCustomViewingAngleMode())
            {
                double exactValley = TheoreticalBaseForPeakMm(lpi, peakMm);
                if (exactValley > 0.0 && exactValley < MinimumValleyHeightMm() - 0.000001)
                    throw new Exception("The custom viewing angle requires a theoretical valley of " + exactValley.ToString("0.00", CultureInfo.InvariantCulture) + " mm, below the printer minimum of " + MinimumValleyHeightMm().ToString("0.00", CultureInfo.InvariantCulture) + " mm.");
            }
        }

        public double MinimumFocusedPeakMm(double lpi)
        {
            double n = RefractiveIndex();
            double a = (25.4 / lpi) / 2.0;
            return n * a / (n - 1.0);
        }

        public double RawPeakForViewingAngleMm(double lpi, double angleDeg)
        {
            double n = RefractiveIndex();
            double a = (25.4 / lpi) / 2.0;
            double halfRadians = angleDeg * Math.PI / 360.0;
            double t = n * a / Math.Tan(halfRadians);
            double minPeak = MinimumFocusedPeakMm(lpi);
            if (t < minPeak) t = minPeak;
            return t;
        }

        public double FocusedValleyForPeakMm(double lpi, double peakMm)
        {
            double n = RefractiveIndex();
            double a = (25.4 / lpi) / 2.0;
            double R = peakMm * (n - 1.0) / n;
            if (R < a) return -1.0;
            double inside = R * R - a * a;
            if (inside < 0) inside = 0;
            double sag = R - Math.Sqrt(inside);
            return peakMm - sag;
        }

        public double ViewingAngleForPeakMm(double lpi, double peakMm)
        {
            if (IsLensFreeMode())
                return ReliefViewingSpreadDeg(lpi, peakMm);
            if (UseMathematicallyOptimalOptics())
                return TheoreticalViewingAngleForPeakMm(lpi, peakMm);
            double factor = ProfileGeometryFactor(lpi);
            double effectiveReferencePeak = peakMm / Math.Max(0.000000001, factor);
            return ReferenceViewingAngleForPeakMm(lpi, effectiveReferencePeak);
        }

        public double AdjustPeakForPrinterValleyMm(double lpi, double peakMm)
        {
            double valley = FocusedValleyForPeakMm(lpi, peakMm);
            if (valley < 0) peakMm = MinimumFocusedPeakMm(lpi);
            valley = FocusedValleyForPeakMm(lpi, peakMm);
            if (valley <= 0 || valley >= MinimumValleyHeightMm()) return peakMm;
            double low = peakMm;
            double high = MaximumTopHeightMm();
            if (FocusedValleyForPeakMm(lpi, high) < MinimumValleyHeightMm()) return high + 1.0;
            for (int i = 0; i < 50; i++)
            {
                double mid = (low + high) / 2.0;
                if (FocusedValleyForPeakMm(lpi, mid) >= MinimumValleyHeightMm()) high = mid;
                else low = mid;
            }
            return high;
        }

        public double ReferenceRecommendedTotalThicknessMm(double lpi)
        {
            return Math.Min(MaximumTopHeightMm(), ReferenceScaledPeakMm(lpi));
        }

        public double UncappedRecommendedTotalThicknessMm(double lpi)
        {
            if (UseMathematicallyOptimalOptics()) return TheoreticalOptimalPeakMm(lpi);
            return ReferenceScaledPeakMm(lpi);
        }

        public double RecommendedTotalThicknessMm(double lpi)
        {
            double value = UncappedRecommendedTotalThicknessMm(lpi);
            return UseMathematicallyOptimalOptics() ? value : Math.Min(MaximumTopHeightMm(), value);
        }

        public bool LpiFitsPrinterThickness(double lpi)
        {
            return lpi > 0;
        }

        public double HeightPresetScaleFactor()
        {
            string kind = CurrentPrintProfileKind();
            if (kind == "LOWER") return 0.90;
            if (kind == "HIGHER") return 1.10;
            return 1.00;
        }

        public double ReferenceRecommendedBaseHeightMm(double lpi, double peakMm)
        {
            double referencePeak = ReferenceScaledPeakMm(lpi);
            if (referencePeak <= 0) return 0;
            double scaleFromReferenceProfile = peakMm / referencePeak;
            double valley = ReferenceScaledValleyMm(lpi) * scaleFromReferenceProfile;
            if (valley > 0 && valley < MinimumValleyHeightMm()) valley = MinimumValleyHeightMm();
            if (valley > peakMm) valley = peakMm;
            return Math.Max(0, valley);
        }

        public double RecommendedBaseHeightMm(double lpi, double peakMm)
        {
            if (UseMathematicallyOptimalOptics())
            {
                double theoretical = TheoreticalOptimalBaseMm(lpi, peakMm);
                if (theoretical < 0) return 0;
                return theoretical;
            }
            return ReferenceRecommendedBaseHeightMm(lpi, peakMm);
        }

        public double RecommendedRiseForSelectionMm(double lpi)
        {
            string kind = CurrentPrintProfileKind();
            double peak;
            if (kind == "MANUAL")
            {
                peak = Positive(settings.ManualHeightText, "Manual Thickness");
                if (settings.ManualHeightUnitSelection == "um") peak /= 1000.0;
                if (peak > MaximumTopHeightMm()) peak = MaximumTopHeightMm();
            }
            else if (kind == "THEORETICAL")
            {
                peak = TheoreticalOptimalPeakMm(lpi);
            }
            else
            {
                double factor = kind == "LOWER" ? 0.90 : (kind == "HIGHER" ? 1.10 : 1.00);
                peak = Math.Min(MaximumTopHeightMm(), ReferenceScaledPeakMm(lpi) * factor);
            }

            double valley;
            if (kind == "THEORETICAL" || LensSelectionRequestsMathematicalOptics())
            {
                valley = TheoreticalOptimalBaseMm(lpi, peak);
                if (valley < 0) valley = 0;
            }
            else
            {
                valley = ReferenceRecommendedBaseHeightMm(lpi, peak);
            }
            if (valley > peak) valley = peak;
            return Math.Max(0, peak - valley);
        }

        public double PeakTargetWithoutViewingAngleMm(double lpi)
        {
            string kind = CurrentPrintProfileKind();

            if (!IsManualSettingsMode() && CurrentBaseModeKind() == "MANUAL")
            {
                double manualBase = NonNegative(settings.ManualBaseText, "Manual base height");
                if (manualBase > 0 && manualBase < MinimumValleyHeightMm())
                    throw new Exception("A non-zero manual base height must be at least " + MinimumValleyHeightMm().ToString("0.00", CultureInfo.InvariantCulture) + " mm, or exactly 0.00 mm for no base.");
                double recommendedRise = RecommendedRiseForSelectionMm(lpi);
                double peakFromBase = manualBase + recommendedRise;
                if (peakFromBase > MaximumTopHeightMm()) peakFromBase = MaximumTopHeightMm();
                if (peakFromBase < manualBase) peakFromBase = manualBase;
                return peakFromBase;
            }

            if (kind == "THEORETICAL")
                return TheoreticalOptimalPeakMm(lpi);

            if (kind == "LOWER" || kind == "REFERENCE" || kind == "HIGHER")
            {
                double factor = kind == "LOWER" ? 0.90 : (kind == "HIGHER" ? 1.10 : 1.00);
                double peak = ReferenceScaledPeakMm(lpi) * factor;
                if (peak > MaximumTopHeightMm()) peak = MaximumTopHeightMm();
                return peak;
            }

            double manual = Positive(settings.ManualHeightText, "Manual Thickness");
            if (settings.ManualHeightUnitSelection == "um") manual /= 1000.0;
            if (manual > MaximumTopHeightMm()) throw new Exception("Manual Thickness cannot exceed the printer maximum of " + MaximumTopHeightMm().ToString("0.00", CultureInfo.InvariantCulture) + " mm.");
            return manual;
        }

        public double PeakTargetForSelectionMm(double lpi)
        {
            if (IsLensFreeMode()) return ReliefPrismHeightMm();
            return PeakForViewingAngleMm(lpi, TargetViewingAngleDegForSelection(lpi));
        }

        public double SurfaceRiseMm(double lpi, double peakMm)
        {
            if (UseMathematicallyOptimalOptics())
            {
                double valley = TheoreticalOptimalBaseMm(lpi, peakMm);
                if (valley < 0) return peakMm;
                return Math.Max(0, peakMm - valley);
            }
            double focusedValley = FocusedValleyForPeakMm(lpi, peakMm);
            if (focusedValley < 0) return peakMm;
            return Math.Max(0, peakMm - focusedValley);
        }

        public double CurveRiseForSelectionMm(double lpi)
        {
            double peak = PeakTargetForSelectionMm(lpi);
            return Math.Max(0, peak - BaseHeightForSelectionMm(lpi));
        }

        public double BaseHeightForSelectionMm(double lpi)
        {
            if (IsLensFreeMode()) return 0.0;
            double peak = PeakTargetForSelectionMm(lpi);
            string kind = CurrentBaseModeKind();
            double recommended = RecommendedBaseHeightMm(lpi, peak);
            double minimumValley = MinimumValleyHeightMm();

            if (kind == "REFERENCE") return ReferenceRecommendedBaseHeightMm(lpi, peak);
            if (kind == "THEORETICAL")
            {
                double theoretical = TheoreticalOptimalBaseMm(lpi, peak);
                if (theoretical < 0)
                    throw new Exception("The selected Thickness is too low for a real full-aperture mathematically optimal aspheric surface at this LPI and IOR.");
                return theoretical;
            }
            if (kind == "NONE") return 0.0;
            if (kind == "MINIMUM") return Math.Min(peak, minimumValley);
            if (kind == "RAISED")
            {
                double raised = recommended + Math.Max(0.10, (peak - recommended) * 0.25);
                if (raised < minimumValley) raised = minimumValley;
                if (raised > peak) raised = peak;
                return raised;
            }
            double manual = NonNegative(settings.ManualBaseText, "Manual base height");
            if (manual > 0 && manual < minimumValley)
                throw new Exception("A non-zero manual base height must be at least " + minimumValley.ToString("0.00", CultureInfo.InvariantCulture) + " mm, or exactly 0.00 mm for no base.");
            if (manual > peak) throw new Exception("Base height cannot be greater than the selected Thickness of " + peak.ToString("0.00", CultureInfo.InvariantCulture) + " mm.");
            return manual;
        }

        public double PeakHeightForSelectionMm(double lpi)
        {
            return PeakTargetForSelectionMm(lpi);
        }

        public double HeightUm(double lpi)
        {
            return PeakHeightForSelectionMm(lpi) * 1000.0;
        }

        public double CalibrationRawPeakForViewingAngleMm(double lpi, double angleDeg)
        {
            double n = RefractiveIndex();
            double a = (25.4 / Math.Max(0.001, lpi)) / 2.0;
            double halfRadians = angleDeg * Math.PI / 360.0;
            if (UseMathematicallyOptimalOptics())
            {
                double s = Math.Sin(halfRadians) / n;
                if (s <= 0.000000000001) return MaximumTopHeightMm() + 1.0;
                if (s >= 1.0) s = 0.999999999;
                return a * Math.Sqrt(Math.Max(0.0, 1.0 - s * s)) / s;
            }
            double tangent = Math.Tan(halfRadians);
            if (Math.Abs(tangent) < 0.000000000001) return MaximumTopHeightMm() + 1.0;
            return Math.Max(MinimumValleyHeightMm(), n * a / tangent);
        }

        public double CalibrationValleyForPeakMm(double lpi, double peakMm)
        {
            if (peakMm <= 0 || peakMm > MaximumTopHeightMm() + 0.0001) return -1.0;
            if (UseMathematicallyOptimalOptics())
            {
                double minimum = TheoreticalMinimumPeakMm(lpi);
                if (peakMm + 0.000001 < minimum) return -1.0;
                return TheoreticalOptimalBaseMm(lpi, peakMm);
            }
            double referencePeak = ReferenceCalibrationPeakMm();
            if (referencePeak <= 0) return -1.0;
            double valley = peakMm * (ReferenceCalibrationValleyMm() / referencePeak);
            if (valley > 0 && valley < MinimumValleyHeightMm())
                valley = peakMm >= MinimumValleyHeightMm() ? MinimumValleyHeightMm() : 0.0;
            if (valley > peakMm) valley = peakMm;
            return Math.Max(0.0, valley);
        }

        public double ConicSag(double x, double radius, double conicK)
        {
            if (radius <= 0) return 0;
            double term = 1.0 - (1.0 + conicK) * x * x / (radius * radius);
            if (term < 0) term = 0;
            double denom = radius * (1.0 + Math.Sqrt(term));
            if (Math.Abs(denom) < 0.0000001) return 0;
            return x * x / denom;
        }

        public double CircularProfileZ(double x, double radius, double hshape)
        {
            double inside = Math.Max(0, radius * radius - x * x);
            double z = (Math.Sqrt(inside) - (radius - hshape)) / hshape;
            return Math.Max(0, Math.Min(1, z));
        }

        public double TheoreticalProfileZ(double xPx, double pitchPx, double ratio, double baseFraction)
        {
            if (pitchPx <= 0) return 0;
            double n = RefractiveIndex();
            double oneMinusBase = 1.0 - Math.Max(0.0, Math.Min(0.999999, baseFraction));
            if (oneMinusBase <= 0.0000001) return 0;

            // Convert the selected physical geometry into pitch-normalized units.
            // ratio = lens rise / pitch, and baseFraction = valley / peak.
            double peakOverPitch = ratio / oneMinusBase;
            double minimumPeakOverPitch = 0.5 * Math.Sqrt((n + 1.0) / (n - 1.0));
            if (peakOverPitch < minimumPeakOverPitch) peakOverPitch = minimumPeakOverPitch;

            double x = xPx / pitchPx;
            double a = 0.5;
            double c = (n - 1.0) * peakOverPitch;
            double n2m1 = n * n - 1.0;
            double disc = c * c - n2m1 * x * x;
            if (disc < 0) disc = 0;
            double z = (c + n * Math.Sqrt(disc)) / n2m1;

            double edgeDisc = c * c - n2m1 * a * a;
            if (edgeDisc < 0) edgeDisc = 0;
            double edge = (c + n * Math.Sqrt(edgeDisc)) / n2m1;
            double denom = peakOverPitch - edge;
            if (denom <= 0.0000001) return 0;
            return Math.Max(0.0, Math.Min(1.0, (z - edge) / denom));
        }

        public ushort[] BuildAxis(int n, double pitchPx, double ratio, double offset, string profile, double baseFraction)
        {
            double[] norm = new double[n];
            double min = 1e99;
            double max = -1e99;
            double a = pitchPx / 2.0;
            double hshape = Math.Max(pitchPx * ratio, pitchPx * .001);
            double R = (a * a + hshape * hshape) / (2 * hshape);
            for (int i = 0; i < n; i++)
            {
                double phase = i / pitchPx + offset;
                phase -= Math.Floor(phase);
                double x = (phase - .5) * pitchPx;
                double z;
                if (profile == "Reference Calibrated")
                {
                    double u = 1.0 - Math.Min(1.0, Math.Abs(x) / a);
                    z = ReferenceProfileZ(u);
                }
                else if (profile == "Mathematically Optimal Aspheric")
                {
                    z = TheoreticalProfileZ(x, pitchPx, ratio, baseFraction);
                }
                else if (profile == "Lens-Free Relief")
                {
                    z = ReliefProfileNormalized(phase);
                }
                else if (profile == "Cosine")
                {
                    z = .5 * (1 + Math.Cos(Math.PI * Math.Max(-1, Math.Min(1, x / a))));
                }
                else if (profile == "Linear / Triangular (experimental)")
                {
                    double u = Math.Min(1.0, Math.Abs(x) / a);
                    z = 1.0 - u;
                }
                else if (profile == "Aspheric")
                {
                    double nIndex = RefractiveIndex();
                    double k = -1.0 / (nIndex * nIndex);
                    double edgeSag = ConicSag(a, R, k);
                    double xSag = ConicSag(Math.Abs(x), R, k);
                    if (edgeSag <= 0.0000001) z = CircularProfileZ(x, R, hshape);
                    else z = 1.0 - Math.Max(0, Math.Min(1, xSag / edgeSag));
                }
                else if (profile == "Multi-facet / Prismatic")
                {
                    double u = Math.Min(1.0, Math.Abs(x) / a);
                    int facets = Math.Max(4, GetEffectiveViewCount() * 2);
                    double fp = u * facets;
                    int fi = (int)Math.Floor(fp);
                    if (fi >= facets) fi = facets - 1;
                    double local = fp - fi;
                    double u0 = (double)fi / facets;
                    double u1 = (double)(fi + 1) / facets;
                    double x0 = u0 * a;
                    double x1 = u1 * a;
                    double z0 = CircularProfileZ(x0, R, hshape);
                    double z1 = CircularProfileZ(x1, R, hshape);
                    z = z0 + (z1 - z0) * local;
                }
                else
                {
                    z = CircularProfileZ(x, R, hshape);
                }
                norm[i] = z;
                if (z < min) min = z;
                if (z > max) max = z;
            }
            var vals = new ushort[n];
            double range = max - min;
            if (range <= 0) range = 1;
            if (baseFraction < 0) baseFraction = 0;
            if (baseFraction > 0.9999) baseFraction = 0.9999;
            for (int i = 0; i < n; i++)
            {
                double surface = (norm[i] - min) / range;
                double absoluteHeight = baseFraction + surface * (1.0 - baseFraction);
                vals[i] = (ushort)Math.Round(absoluteHeight * 65535.0);
            }
            return vals;
        }

    }
}
