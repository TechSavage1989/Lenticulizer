using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;

namespace Lenticulizer.Core
{
    // One owner per processing host. Calls are serialized by the host.
    public sealed class RasterEngine : IDisposable
    {
        Dictionary<string, Bitmap> fittedFrameCache = new Dictionary<string, Bitmap>(StringComparer.OrdinalIgnoreCase);
        Queue<string> fittedFrameCacheOrder = new Queue<string>();
        long fittedFrameCacheBytes = 0;
        const int FittedFrameCacheLimit = 12;
        const long FittedFrameCacheByteLimit = 192L * 1024L * 1024L;
        const long FittedFrameSingleCacheLimit = 64L * 1024L * 1024L;

        public void ClearFittedFrameCache()
        {
            foreach (Bitmap bmp in fittedFrameCache.Values)
            {
                try { bmp.Dispose(); } catch { }
            }
            fittedFrameCache.Clear();
            fittedFrameCacheOrder.Clear();
            fittedFrameCacheBytes = 0;
        }

        public Bitmap LoadAndFitBitmapCached(string path, int outWidth, int outHeight, double physicalAspect = 0)
        {
            long ticks = 0;
            try { if (File.Exists(path)) ticks = File.GetLastWriteTimeUtc(path).Ticks; } catch { }
            string key = (path ?? "") + "|" + ticks.ToString(CultureInfo.InvariantCulture) + "|" + outWidth.ToString(CultureInfo.InvariantCulture) + "x" + outHeight.ToString(CultureInfo.InvariantCulture) + "|" + physicalAspect.ToString("R",CultureInfo.InvariantCulture);
            Bitmap cached;
            if (fittedFrameCache.TryGetValue(key, out cached) && cached != null)
                return cached.Clone(new Rectangle(0, 0, cached.Width, cached.Height), PixelFormat.Format24bppRgb);

            Bitmap fitted = LoadAndFitBitmap(path, outWidth, outHeight, physicalAspect);
            long estimatedBytes = Math.Max(1L, (long)outWidth * (long)outHeight * 3L);
            if (estimatedBytes > FittedFrameSingleCacheLimit)
                return fitted;

            fittedFrameCache[key] = fitted;
            fittedFrameCacheOrder.Enqueue(key);
            fittedFrameCacheBytes += estimatedBytes;
            while (fittedFrameCacheOrder.Count > FittedFrameCacheLimit || fittedFrameCacheBytes > FittedFrameCacheByteLimit)
            {
                string old = fittedFrameCacheOrder.Dequeue();
                Bitmap oldBmp;
                if (fittedFrameCache.TryGetValue(old, out oldBmp))
                {
                    fittedFrameCache.Remove(old);
                    fittedFrameCacheBytes -= Math.Max(1L, (long)oldBmp.Width * (long)oldBmp.Height * 3L);
                    try { oldBmp.Dispose(); } catch { }
                }
            }
            return fitted.Clone(new Rectangle(0, 0, fitted.Width, fitted.Height), PixelFormat.Format24bppRgb);
        }

        public static int[] StripeIndices(int count, double pitch, double phaseOffset, int views, bool lensFree, bool snapBoundaries = false)
        {
            var result = new int[count];
            for (int i=0;i<count;i++)
            {
                double phase=i/pitch+phaseOffset;phase-=Math.Floor(phase);
                int index=Math.Clamp((int)Math.Floor(phase*views+(snapBoundaries?1e-7:0)),0,views-1);
                result[i]=lensFree?index:views-1-index;
            }
            return result;
        }
        public Bitmap BuildInterlacedBitmap(int outWidth, int outHeight, double pitchPx, bool vertical, string[] sourceFrames, bool lensFree, double phaseOffset = 0, bool snapBoundaries = false, double physicalAspect = 0)
        {
            int views = sourceFrames.Length;
            Bitmap[] prepared = new Bitmap[views];
            Bitmap output = null;
            try
            {
                for (int i = 0; i < views; i++) prepared[i] = LoadAndFitBitmapCached(sourceFrames[i], outWidth, outHeight, physicalAspect);
                output = new Bitmap(outWidth, outHeight, PixelFormat.Format24bppRgb);
                byte[][] srcBytes = new byte[views][];
                BitmapData[] srcData = new BitmapData[views];
                int[] srcStride = new int[views];
                for (int i = 0; i < views; i++)
                {
                    Rectangle rect = new Rectangle(0, 0, prepared[i].Width, prepared[i].Height);
                    srcData[i] = prepared[i].LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format24bppRgb);
                    srcStride[i] = srcData[i].Stride;
                    srcBytes[i] = new byte[srcStride[i] * outHeight];
                    System.Runtime.InteropServices.Marshal.Copy(srcData[i].Scan0, srcBytes[i], 0, srcBytes[i].Length);
                }
                Rectangle outRect = new Rectangle(0, 0, output.Width, output.Height);
                BitmapData outData = output.LockBits(outRect, ImageLockMode.WriteOnly, PixelFormat.Format24bppRgb);
                int outStride = outData.Stride;
                byte[] outBytes = new byte[outStride * outHeight];

                int axisCount = vertical ? outWidth : outHeight;
                int[] stripeMap = StripeIndices(axisCount,pitchPx,phaseOffset,views,lensFree,snapBoundaries);

                for (int y = 0; y < outHeight; y++)
                {
                    int outRow = y * outStride;
                    for (int x = 0; x < outWidth; x++)
                    {
                        int imgIdx = vertical ? stripeMap[x] : stripeMap[y];
                        int pOut = outRow + x * 3;
                        int pSrc = y * srcStride[imgIdx] + x * 3;
                        byte[] src = srcBytes[imgIdx];
                        outBytes[pOut] = src[pSrc];
                        outBytes[pOut + 1] = src[pSrc + 1];
                        outBytes[pOut + 2] = src[pSrc + 2];
                    }
                }

                System.Runtime.InteropServices.Marshal.Copy(outBytes, 0, outData.Scan0, outBytes.Length);
                output.UnlockBits(outData);
                for (int i = 0; i < views; i++) prepared[i].UnlockBits(srcData[i]);
                return output;
            }
            catch
            {
                if (output != null) output.Dispose();
                throw;
            }
            finally
            {
                for (int i = 0; i < views; i++) if (prepared[i] != null) prepared[i].Dispose();
            }
        }

        public Bitmap LoadAndFitBitmap(string path, int outWidth, int outHeight, double physicalAspect = 0)
        {
            using (var srcBmp = new Bitmap(path))
            {
                Bitmap fitted = new Bitmap(outWidth, outHeight, PixelFormat.Format24bppRgb);
                fitted.SetResolution(srcBmp.HorizontalResolution, srcBmp.VerticalResolution);
                using (Graphics g = Graphics.FromImage(fitted))
                {
                    g.Clear(Color.White);
                    g.InterpolationMode = InterpolationMode.NearestNeighbor;
                    g.PixelOffsetMode = PixelOffsetMode.Half;
                    g.SmoothingMode = SmoothingMode.None;
                    if(physicalAspect>0)
                        g.DrawImage(srcBmp,new Rectangle(0,0,outWidth,outHeight),SourceCropForAspect(srcBmp.Width,srcBmp.Height,physicalAspect),GraphicsUnit.Pixel);
                    else
                    {
                    float scale = Math.Max((float)outWidth / (float)srcBmp.Width, (float)outHeight / (float)srcBmp.Height);
                    int drawW = (int)Math.Round(srcBmp.Width * scale);
                    int drawH = (int)Math.Round(srcBmp.Height * scale);
                    int drawX = (outWidth - drawW) / 2;
                    int drawY = (outHeight - drawH) / 2;
                    g.DrawImage(srcBmp, new Rectangle(drawX, drawY, drawW, drawH));
                    }
                }
                return fitted;
            }
        }

        public static RectangleF SourceCropForAspect(int width,int height,double aspect)
        {
            if(width/(double)height>aspect){double w=height*aspect;return new RectangleF((float)((width-w)/2),0,(float)w,height);}
            double h=width/aspect;return new RectangleF(0,(float)((height-h)/2),width,(float)h);
        }

        public static void GetBuildTargetCanvasSize(double widthInches, double heightInches, double lpi, bool vertical, out int w, out int h, double ppl)
        {
            double axisIn = vertical ? widthInches : heightInches;
            double crossIn = vertical ? heightInches : widthInches;
            int axisPx = Math.Max(1, (int)Math.Round(axisIn * lpi * ppl));
            int crossPx = Math.Max(1, (int)Math.Round(axisPx * (crossIn / axisIn)));
            if (vertical)
            {
                w = axisPx;
                h = crossPx;
            }
            else
            {
                h = axisPx;
                w = crossPx;
            }
        }

        public void Dispose()
        {
            ClearFittedFrameCache();
        }
    }
}
