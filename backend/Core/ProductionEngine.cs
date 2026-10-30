using System;

namespace Lenticulizer.Core
{
    public static class ProductionEngine
    {
        public static void WriteHeightmapForPath(string outputPath, double wi, double hi, double lpi, bool vertical, double totalThicknessMm, double baseThicknessMm, int sourceWidth, int sourceHeight, string sourcePath, double offset, OpticalSettings settings)
        {
            OpticalEngine optics = new OpticalEngine(settings);
            optics.ValidateTheoreticalProfileGeometry(lpi, totalThicknessMm);
            double axisIn = vertical ? wi : hi;
            int axisPx = vertical ? sourceWidth : sourceHeight;
            double dpi = axisPx / axisIn;
            double pitchPx = dpi / lpi;
            double ratio = totalThicknessMm > 0 ? Math.Max(0, totalThicknessMm - baseThicknessMm) / (25.4 / lpi) : 0;
            double baseFraction = totalThicknessMm > 0 ? baseThicknessMm / totalThicknessMm : 0;
            uint sourcePpmX, sourcePpmY;
            bool sourceHasPhys = PngCodec.TryReadPngPhysicalResolution(sourcePath, out sourcePpmX, out sourcePpmY);
            ushort[] axisVals = optics.BuildAxis(axisPx, pitchPx, ratio, offset, optics.SelectedLensProfileKind(), baseFraction);
            PngCodec.WriteGray16Png(outputPath, sourceWidth, sourceHeight, axisVals, vertical, sourceHasPhys, sourcePpmX, sourcePpmY);
            HeightmapWorkflow.AnnotateScale(outputPath, totalThicknessMm);
        }
    }
}
