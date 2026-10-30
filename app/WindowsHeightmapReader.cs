using System;
using System.IO;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Lenticulizer.Core;

namespace Lenticulizer.Desktop
{
    internal static class WindowsHeightmapReader
    {
        public static HeightmapData Read(string path)
        {
            using(var stream=File.OpenRead(path))
            {
                var decoder=BitmapDecoder.Create(stream,BitmapCreateOptions.PreservePixelFormat,BitmapCacheOption.OnLoad);
                var frame=decoder.Frames[0];int w=frame.PixelWidth,h=frame.PixelHeight;HeightmapEngine.ValidateSize(w,h);
                bool gray16=frame.Format==PixelFormats.Gray16,gray8=frame.Format==PixelFormats.Gray8;
                bool wide=gray16||frame.Format.BitsPerPixel>=48;
                PixelFormat target=gray16?PixelFormats.Gray16:gray8?PixelFormats.Gray8:wide?PixelFormats.Rgb48:PixelFormats.Bgra32;
                BitmapSource bitmap=frame.Format==target?frame:new FormatConvertedBitmap(frame,target,null,0);
                int channels=gray16||gray8?1:wide?3:4,step=wide?2:1,stride=checked(w*channels*step);
                byte[] pixels=new byte[checked(stride*h)];bitmap.CopyPixels(pixels,stride,0);
                var data=new HeightmapData{Width=w,Height=h,BitDepth=wide?16:8,X=new double[w],Y=new double[h]};
                // Require real TIFF resolution tags, never WIC's default 96 DPI.
                var metadata=frame.Metadata as BitmapMetadata;
                if(metadata!=null&&Path.GetExtension(path).StartsWith(".tif",StringComparison.OrdinalIgnoreCase)&&metadata.ContainsQuery("/ifd/{ushort=282}")&&metadata.ContainsQuery("/ifd/{ushort=283}"))
                {
                    object unit=metadata.GetQuery("/ifd/{ushort=296}");
                    if(unit==null||Convert.ToInt32(unit)!=1){data.WidthMm=w*25.4/frame.DpiX;data.HeightMm=h*25.4/frame.DpiY;}
                }
                if(Path.GetExtension(path).StartsWith(".tif",StringComparison.OrdinalIgnoreCase) && metadata!=null && metadata.ContainsQuery("/ifd/{ushort=270}"))
                {
                    string description=Convert.ToString(metadata.GetQuery("/ifd/{ushort=270}"));
                    foreach(string line in description.Split('\n'))if(line.StartsWith("LenticulizerHeightScaleMm="))
                        double.TryParse(line.Substring("LenticulizerHeightScaleMm=".Length).TrimEnd('\0'),System.Globalization.NumberStyles.Float,System.Globalization.CultureInfo.InvariantCulture,out data.ScaleMm);
                }
                double Sample(int pos)=>wide?(pixels[pos]|(pixels[pos+1]<<8))/65535.0:pixels[pos]/255.0;
                for(int y=0;y<h;y++)for(int x=0;x<w;x++)
                {
                    int p=y*stride+x*channels*step;double value=Sample(p);
                    if(channels>1)for(int c=1;c<3;c++)if(Math.Abs(value-Sample(p+c*step))>1.0/255)data.Grayscale=false;
                    if(y==h/2)data.X[x]=value;if(x==w/2)data.Y[y]=value;
                    data.Minimum=Math.Min(data.Minimum,value);data.Maximum=Math.Max(data.Maximum,value);
                }
                return data;
            }
        }
    }
}
