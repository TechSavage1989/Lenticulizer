using System;

namespace Lenticulizer.Core
{
    // Input values only. Text is retained where the legacy parser distinguishes
    // an incomplete edit from a valid numeric value. No controls or callbacks.
    public sealed class OpticalSettings
    {
        public string SettingsModeSelection = "Automatic";
        public string OutputModeSelection = "Lenticular Lens";
        public string PrintProfileSelection = "Recommended (Reference Calibrated)";
        public string BaseModeSelection = "Recommended (Reference Calibrated)";
        public string LensProfileSelection = "Auto Recommended";
        public int LensProfileIndex = 0;
        public bool HasLensProfile = true;
        public string ViewingAngleSelection = "Standard";
        public string CustomViewingAngleText = "44";
        public string RefractiveIndexText = "1.55";
        public string ReliefPrismHeightText = "0.80";
        public string ManualHeightText = "1.0";
        public string ManualHeightUnitSelection = "mm";
        public string ManualBaseText = "0.30";
        public string LpiText = "24";
        public string PixelsPerLenticuleText = "60";
        public string PrinterDpiSelection = "1440";
        public string ViewCountText = "2";
        public int FrameCount = 0;
        public string WidthText = "100";
        public string HeightText = "100";
        public string SizeUnitSelection = "mm";
        public string OrientationSelection = "Vertical";

        internal OpticalSettings Snapshot()
        {
            return (OpticalSettings)MemberwiseClone();
        }
    }
}
