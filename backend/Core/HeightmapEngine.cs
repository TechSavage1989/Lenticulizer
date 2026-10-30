using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Text;

namespace Lenticulizer.Core
{
    public sealed class HeightmapData
    {
        public int Width, Height, BitDepth;
        public double WidthMm, HeightMm, ScaleMm;
        public double[] X, Y;
        public double Minimum = 1, Maximum;
        public bool Grayscale = true;
    }

    // Data samples are linear height values, never display-gamma corrected.
    public static class HeightmapEngine
    {
        public static Func<string, HeightmapData> OtherImageReader;
        static readonly object gate = new object();
        static string cacheKey;
        static HeightmapData cached;
        static Dictionary<string,object> cachedAnalysis;
        public static HeightmapData Load(string path)
        {
            string key = ProjectBuild.Stamp(path);
            lock(gate)
            {
                if(key==cacheKey && cached!=null) return cached;
                if(!File.Exists(path)) throw new FileNotFoundException("The imported heightmap is not available.",path);
                HeightmapData data;
                if(Path.GetExtension(path).Equals(".png",StringComparison.OrdinalIgnoreCase))
                {
                    try { data=ReadPng(path); }
                    catch(NotSupportedException) { if(OtherImageReader==null)throw; data=OtherImageReader(path); OverlayPngMetadata(data,path); }
                }
                else { if(OtherImageReader==null) throw new NotSupportedException("Use a grayscale PNG heightmap on this platform."); data=OtherImageReader(path); }
                cached=data; cacheKey=key; cachedAnalysis=null; return data;
            }
        }
        static void OverlayPngMetadata(HeightmapData data,string path)
        {
            using(var stream=File.OpenRead(path))using(var reader=new BinaryReader(stream))
            {
                stream.Position=8;
                while(stream.Position+12<=stream.Length)
                {
                    uint length=PngCodec.Read32(reader.ReadBytes(4),0);string name=Encoding.ASCII.GetString(reader.ReadBytes(4));
                    if(stream.Position+length+4>stream.Length)break;
                    if(name=="pHYs"&&length==9){var v=reader.ReadBytes(9);uint x=PngCodec.Read32(v,0),y=PngCodec.Read32(v,4);if(v[8]==1&&x>0&&y>0){data.WidthMm=data.Width*1000.0/x;data.HeightMm=data.Height*1000.0/y;}}
                    else if(name=="tEXt"&&length<=1048576){var v=reader.ReadBytes((int)length);int nul=Array.IndexOf(v,(byte)0);if(nul>0&&Encoding.ASCII.GetString(v,0,nul)=="LenticulizerHeightScaleMm")double.TryParse(Encoding.UTF8.GetString(v,nul+1,v.Length-nul-1),NumberStyles.Float,CultureInfo.InvariantCulture,out data.ScaleMm);}
                    else stream.Position+=length;
                    stream.Position+=4;if(name=="IEND")break;
                }
            }
        }
        public static void ValidateSize(int width,int height)
        {
            if(width<2 || height<2 || width>100000 || height>100000 || (long)width*height>100000000)
                throw new InvalidDataException("Heightmaps must have at least 2 pixels per side and at most 100 million pixels.");
        }
        static int Paeth(int a,int b,int c) { int p=a+b-c,pa=Math.Abs(p-a),pb=Math.Abs(p-b),pc=Math.Abs(p-c);return pa<=pb&&pa<=pc?a:pb<=pc?b:c; }
        static HeightmapData ReadPng(string path)
        {
            var data=new HeightmapData(); int color=0,interlace=0;byte[] palette=null;
            using(var compressed=new MemoryStream())
            {
                using(var input=File.OpenRead(path)) using(var reader=new BinaryReader(input))
                {
                    if(!reader.ReadBytes(8).SequenceEqual(new byte[]{137,80,78,71,13,10,26,10}))throw new InvalidDataException("Invalid PNG signature.");
                    while(input.Position+12<=input.Length)
                    {
                        int length=checked((int)PngCodec.Read32(reader.ReadBytes(4),0));string name=Encoding.ASCII.GetString(reader.ReadBytes(4));
                        if(length<0 || length>268435456 || input.Position+length+4>input.Length)throw new InvalidDataException("Invalid PNG chunk.");
                        byte[] value=reader.ReadBytes(length);reader.ReadBytes(4);
                        if(name=="IHDR") { data.Width=checked((int)PngCodec.Read32(value,0));data.Height=checked((int)PngCodec.Read32(value,4));data.BitDepth=value[8];color=value[9];interlace=value[12];ValidateSize(data.Width,data.Height); }
                        else if(name=="IDAT")compressed.Write(value,0,value.Length);
                        else if(name=="PLTE")palette=value;
                        else if(name=="pHYs" && value.Length==9 && value[8]==1)
                        { uint x=PngCodec.Read32(value,0),y=PngCodec.Read32(value,4);if(x>0&&y>0){data.WidthMm=data.Width*1000.0/x;data.HeightMm=data.Height*1000.0/y;} }
                        else if(name=="tEXt")
                        { int nul=Array.IndexOf(value,(byte)0);if(nul>0 && Encoding.ASCII.GetString(value,0,nul)=="LenticulizerHeightScaleMm")double.TryParse(Encoding.UTF8.GetString(value,nul+1,value.Length-nul-1),NumberStyles.Float,CultureInfo.InvariantCulture,out data.ScaleMm); }
                        if(name=="IEND")break;
                    }
                }
                if(interlace!=0)throw new NotSupportedException("This PNG needs the Windows image decoder.");
                int channels=color==0?1:color==2?3:color==3?1:color==4?2:color==6?4:0;
                if(channels==0 || !(data.BitDepth==8 || data.BitDepth==16 || ((color==0||color==3) && (data.BitDepth==1||data.BitDepth==2||data.BitDepth==4))))throw new NotSupportedException("Unsupported heightmap PNG format.");
                ValidateSize(data.Width,data.Height);
                int rowBytes=checked((data.Width*channels*data.BitDepth+7)/8),bpp=Math.Max(1,(channels*data.BitDepth+7)/8);
                byte[] previous=new byte[rowBytes],row=new byte[rowBytes];data.X=new double[data.Width];data.Y=new double[data.Height];
                compressed.Position=0;
                using(var raw=new ZLibStream(compressed,CompressionMode.Decompress,true))
                    for(int y=0;y<data.Height;y++)
                    {
                        int filter=raw.ReadByte();if(filter<0||filter>4)throw new InvalidDataException("Invalid PNG scanline.");
                        raw.ReadExactly(row);
                        for(int i=0;i<rowBytes;i++)
                        { int a=i>=bpp?row[i-bpp]:0,b=previous[i],c=i>=bpp?previous[i-bpp]:0;int predict=filter==0?0:filter==1?a:filter==2?b:filter==3?(a+b)/2:Paeth(a,b,c);row[i]=(byte)(row[i]+predict); }
                        for(int x=0;x<data.Width;x++)
                        {
                            int offset=x*channels*(data.BitDepth==16?2:1);double v;
                            if(color==3)
                            { int idx=data.BitDepth==8?row[x]:(row[x*data.BitDepth/8]>>(8-data.BitDepth-x*data.BitDepth%8))&((1<<data.BitDepth)-1);if(palette==null||idx*3+2>=palette.Length)throw new InvalidDataException("Invalid PNG palette.");v=palette[idx*3]/255.0;if(palette[idx*3]!=palette[idx*3+1]||palette[idx*3]!=palette[idx*3+2])data.Grayscale=false; }
                            else if(data.BitDepth<8) v=((row[x*data.BitDepth/8]>>(8-data.BitDepth-x*data.BitDepth%8))&((1<<data.BitDepth)-1))/(double)((1<<data.BitDepth)-1);
                            else
                            {
                                v=data.BitDepth==16?((row[offset]<<8)|row[offset+1])/65535.0:row[offset]/255.0;
                                if(color==2||color==6)
                                { int step=data.BitDepth/8;for(int c=1;c<3;c++){double other=step==2?((row[offset+c*step]<<8)|row[offset+c*step+1])/65535.0:row[offset+c]/255.0;if(Math.Abs(v-other)>1.0/255)data.Grayscale=false;} }
                            }
                            if(y==data.Height/2)data.X[x]=v;if(x==data.Width/2)data.Y[y]=v;
                            data.Minimum=Math.Min(data.Minimum,v);data.Maximum=Math.Max(data.Maximum,v);
                        }
                        var swap=previous;previous=row;row=swap;
                    }
                return data;
            }
        }
        static double Variance(double[] a) { double mean=a.Average();return a.Sum(x=>(x-mean)*(x-mean))/a.Length; }
        static double Wrap(double x) { return x-Math.Floor(x); }
        static double[] Preview(double[] a)
        {
            int count=Math.Min(8192,a.Length);var p=new double[count];for(int i=0;i<count;i++)p[i]=a[(int)Math.Round(i*(a.Length-1.0)/(count-1))];return p;
        }
        static double[] DetectPeriod(double[] full, bool coarse=false)
        {
            int step=coarse?Math.Max(1,(int)Math.Ceiling(full.Length/4096.0)):1;int n=Math.Min(4096,(full.Length+step-1)/step);
            var a=new double[n];for(int i=0;i<n;i++){int end=Math.Min(full.Length,(i+1)*step);for(int j=i*step;j<end;j++)a[i]+=full[j];a[i]/=end-i*step;}
            double mean=a.Average();for(int i=0;i<n;i++)a[i]-=mean;
            int limit=Math.Min(n/3,2048);if(limit<4)return new double[]{0,0,0};
            var square=new double[n+1];for(int i=0;i<n;i++)square[i+1]=square[i]+a[i]*a[i];
            var corr=new double[limit+1];
            for(int lag=1;lag<=limit;lag++){double sum=0;for(int i=0;i<n-lag;i++)sum+=a[i]*a[i+lag];corr[lag]=sum/Math.Max(1e-20,Math.Sqrt(square[n-lag]*(square[n]-square[lag])));}
            double best=0;for(int k=3;k<limit;k++)if(corr[k]>=corr[k-1]&&corr[k]>corr[k+1])best=Math.Max(best,corr[k]);
            int chosen=0;for(int k=3;k<limit;k++)if(corr[k]>=Math.Max(.86,best-.045)&&corr[k]>=corr[k-1]&&corr[k]>corr[k+1]){chosen=k;break;}
            if(chosen==0)return !coarse&&full.Length>4096?DetectPeriod(full,true):new double[]{0,0,0};
            double denom=corr[chosen-1]-2*corr[chosen]+corr[chosen+1];
            double pitch=(chosen+(Math.Abs(denom)>1e-12?.5*(corr[chosen-1]-corr[chosen+1])/denom:0))*step;
            double min=full.Min(),max=full.Max();var peaks=new List<double>();var heights=new List<double>();
            for(int i=1;i<full.Length-1;i++)
            {
                if(full[i]<min+.85*(max-min)||full[i]<=full[i-1])continue;
                int end=i;while(end+1<full.Length&&Math.Abs(full[end+1]-full[i])<1e-12)end++;
                if(end>=full.Length-1||full[end]<=full[end+1])continue;
                double center=(i+end)*.5;
                if(end==i){double d=full[i-1]-2*full[i]+full[i+1];if(Math.Abs(d)>1e-12)center+=Math.Clamp(.5*(full[i-1]-full[i+1])/d,-.5,.5);}
                if(peaks.Count>0&&center-peaks[peaks.Count-1]<pitch*.55)
                { if(full[i]>heights[heights.Count-1]){peaks[peaks.Count-1]=center;heights[heights.Count-1]=full[i];} }
                else{peaks.Add(center);heights.Add(full[i]);}
                i=end;
            }
            if(peaks.Count<3)return new double[]{pitch,0,0};
            double previousPeak=peaks[0],cycle=0,sx=0,sy=0,sxx=0,sxy=0;var ids=new List<double>();
            foreach(double p in peaks){cycle+=Math.Round((p-previousPeak)/pitch);previousPeak=p;double k=cycle;ids.Add(k);sx+=k;sy+=p;sxx+=k*k;sxy+=k*p;}
            double div=peaks.Count*sxx-sx*sx;if(div<=0)return new double[]{pitch,0,0};
            double fitted=(peaks.Count*sxy-sx*sy)/div,origin=(sy-fitted*sx)/peaks.Count;
            if(Math.Abs(fitted-pitch)>pitch*.12)return new double[]{pitch,0,0};
            double error=0;for(int i=0;i<peaks.Count;i++)error+=Math.Pow(peaks[i]-(origin+ids[i]*fitted),2);
            double confidence=Math.Clamp(corr[chosen]*(1-Math.Sqrt(error/peaks.Count)/Math.Max(1,fitted)*5),0,1);
            // Preserve the production raster convention: sample i has phase i/pitch.
            double phase=Wrap(.5-origin/fitted+.5)-.5;
            return new[]{fitted,phase,confidence};
        }
        public static Dictionary<string,object> Analyze(string path)
        {
            lock(gate)
            {
                var d=Load(path);if(cachedAnalysis!=null)return ProjectJson.Parse(ProjectJson.Stringify(cachedAnalysis));
                double vx=Variance(d.X),vy=Variance(d.Y);if(vx<1e-14)vx=0;if(vy<1e-14)vy=0;bool vertical=vx>=vy;double ratio=Math.Max(vx,vy)/Math.Max(1e-14,Math.Min(vx,vy));
                double[] result=DetectPeriod(vertical?d.X:d.Y);bool ok=d.Grayscale && d.Maximum-d.Minimum>.0001 && ratio>=9 && result[0]>=3 && result[2]>=.80;
                string message=ok?"Detected repeating lens profiles. Verify physical size and white-level height before printing.":!d.Grayscale?"The image contains color. Import a grayscale lens heightmap.":d.Maximum-d.Minimum<=.0001?"The heightmap is flat. Lens spacing cannot be detected.":ratio<9?"Both axes vary. Automatic lens direction is ambiguous; choose Manual and verify direction, pitch and registration.":"A reliable repeating lens profile was not found. Choose Manual and verify direction, pitch and registration.";
                cachedAnalysis=new Dictionary<string,object>{{"algorithm","lens-profile-v1"},{"ok",ok},{"width_px",d.Width},{"height_px",d.Height},{"bit_depth",d.BitDepth},{"width_mm",d.WidthMm},{"height_mm",d.HeightMm},{"scale_mm",d.ScaleMm},{"minimum",d.Minimum},{"maximum",d.Maximum},{"orientation",vertical?"Vertical":"Horizontal"},{"pitch_px",result[0]},{"phase_pitch",result[1]},{"confidence",ok?result[2]:Math.Min(.49,result[2])},{"message",message},{"profile_x",Preview(d.X)},{"profile_y",Preview(d.Y)},{"grayscale",d.Grayscale}};
                return ProjectJson.Parse(ProjectJson.Stringify(cachedAnalysis));
            }
        }
    }
}
