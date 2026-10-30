using System;
using System.Collections.Generic;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace Lenticulizer.Core
{
    public static class HeightmapWorkflow
    {
        static readonly CultureInfo Inv=CultureInfo.InvariantCulture;
        static double Positive(Dictionary<string,object> s,string name,double fallback) { double n=ProjectJson.Number(s,name,fallback);return n>0&&n<=100000?n:fallback; }
        public static void Read(ProjectState p,Dictionary<string,object> s,Dictionary<string,object> root)
        {
            p.ReferenceWidthMm=Positive(s,"reference_heightmap_width_mm",p.ReferenceWidthMm);
            p.ReferenceHeightMm=Positive(s,"reference_heightmap_height_mm",p.ReferenceHeightMm);
            double scale=Positive(s,"reference_heightmap_thickness_mm",p.ReferenceScaleMm);if(scale<=5)p.ReferenceScaleMm=scale;
            p.ReferenceOrientation=ProjectJson.Text(s,"reference_heightmap_orientation",p.ReferenceOrientation).StartsWith("H",StringComparison.OrdinalIgnoreCase)?"Horizontal":"Vertical";
            string style=ProjectJson.Text(s,"reference_heightmap_display_style",p.ReferenceStyle);p.ReferenceStyle=new[]{"OPAQUE","TINTED","CLEAR"}.Contains(style)?style:"OPAQUE";
            p.ReferenceDetection=ProjectJson.Text(s,"reference_heightmap_detection",p.ReferenceDetection)=="Manual"?"Manual":"Automatic";
            p.ReferencePitchPx=Positive(s,"reference_heightmap_pitch_px",p.ReferencePitchPx);
            p.ReferencePhasePitch=Math.Clamp(ProjectJson.Number(s,"reference_heightmap_phase_pitch",p.ReferencePhasePitch),-.5,.5);
            object visible;if(s.TryGetValue("reference_heightmap_show",out visible))p.ReferenceShow=object.Equals(visible,true);
            if(root.ContainsKey("reference_heightmap_info"))p.ReferenceInfoJson=ProjectJson.Stringify(ProjectJson.Object(root,"reference_heightmap_info"));
        }
        public static void Write(ProjectState p,Dictionary<string,object> s)
        {
            s["reference_heightmap_width_mm"]=p.ReferenceWidthMm;s["reference_heightmap_height_mm"]=p.ReferenceHeightMm;
            s["reference_heightmap_thickness_mm"]=p.ReferenceScaleMm;s["reference_heightmap_orientation"]=p.ReferenceOrientation;
            s["reference_heightmap_display_style"]=p.ReferenceStyle;s["reference_heightmap_detection"]=p.ReferenceDetection;
            s["reference_heightmap_pitch_px"]=p.ReferencePitchPx;s["reference_heightmap_phase_pitch"]=p.ReferencePhasePitch;s["reference_heightmap_show"]=p.ReferenceShow;
        }
        public static void Refresh(ProjectState p)
        {
            if(string.IsNullOrEmpty(p.ReferencePath)){p.ReferenceInfoJson="{}";return;}
            try
            {
                var info=HeightmapEngine.Analyze(p.ReferencePath);p.ReferenceInfoJson=ProjectJson.Stringify(info);
                if(p.ReferenceDetection=="Automatic"&&object.Equals(info["ok"],true))
                {p.ReferenceOrientation=(string)info["orientation"];p.ReferencePitchPx=ProjectJson.Number(info,"pitch_px",0);p.ReferencePhasePitch=ProjectJson.Number(info,"phase_pitch",0);}
                if(p.BuildsFromHeightmap)Normalize(p);
            }
            catch(Exception e){p.ReferenceInfoJson=ProjectJson.Stringify(new Dictionary<string,object>{{"ok",false},{"message",e.Message}});if(p.BuildsFromHeightmap)throw;}
        }
        public static void Normalize(ProjectState p)
        {
            var info=ProjectJson.Parse(p.ReferenceInfoJson);var o=p.Optics;
            o.WidthText=p.ReferenceWidthMm.ToString("0.######",Inv);o.HeightText=p.ReferenceHeightMm.ToString("0.######",Inv);o.SizeUnitSelection="mm";
            o.OrientationSelection=p.ReferenceOrientation;
            double pixels=ProjectJson.Number(info,p.ReferenceOrientation=="Vertical"?"width_px":"height_px",0);
            if(p.ReferencePitchPx>0&&pixels>0)o.LpiText=(pixels*25.4/((p.ReferenceOrientation=="Vertical"?p.ReferenceWidthMm:p.ReferenceHeightMm)*p.ReferencePitchPx)).ToString("0.#########",Inv);
            if(p.SourceFrames.Length>0)o.ViewCountText=p.SourceFrames.Length.ToString(Inv);
            p.LpiHelperMode="Manual";p.BuildDetailMode="Custom";o.PixelsPerLenticuleText=Math.Max(2,Math.Round(p.ReferencePitchPx)).ToString(Inv);
        }
        public static string Key(ProjectState p)
        { return string.Join("|",p.ReferenceWidthMm.ToString("R",Inv),p.ReferenceHeightMm.ToString("R",Inv),p.ReferenceScaleMm.ToString("R",Inv),p.ReferenceOrientation,p.ReferenceDetection,p.ReferencePitchPx.ToString("R",Inv),p.ReferencePhasePitch.ToString("R",Inv),p.PhasePitch.ToString("R",Inv)); }
        public static string Solve(ProjectState p)
        {
            Normalize(p);var s=ProjectJson.Object(ProjectJson.Parse(p.InputJson),"settings");var i=ProjectJson.Parse(p.ReferenceInfoJson);
            double maximum=ProjectJson.Number(i,"maximum",1),minimum=ProjectJson.Number(i,"minimum",0);
            s["mode"]=p.Optics.SettingsModeSelection;s["workflow"]=p.Workflow;s["output_mode"]=p.Optics.OutputModeSelection;
            s["width_mm"]=p.ReferenceWidthMm;s["height_mm"]=p.ReferenceHeightMm;s["orientation"]=p.ReferenceOrientation;
            s["lpi"]=double.Parse(p.Optics.LpiText,Inv);s["lpi_helper_mode"]="Manual";s["build_detail_mode"]="Custom";
            s["views"]=int.Parse(p.Optics.ViewCountText,Inv);s["pixels_per_lenticule"]=Math.Max(2,Math.Round(p.ReferencePitchPx));
            s["thickness_mm"]=maximum*p.ReferenceScaleMm;s["base_mm"]=minimum*p.ReferenceScaleMm;s["rise_mm"]=(maximum-minimum)*p.ReferenceScaleMm;
            s["manual_thickness_mm"]=maximum*p.ReferenceScaleMm;s["manual_base_mm"]=minimum*p.ReferenceScaleMm;
            s["print_profile"]="Manual Thickness";s["base_mode"]="Manual base height";
            s["phase_pitch"]=p.PhasePitch;s["ior"]=double.Parse(p.Optics.RefractiveIndexText,Inv);s["backing_mm"]=p.BackingMm;
            // An imported profile does not encode a measured optical viewing angle.
            s["imported_heightmap_geometry"]=true;Write(p,s);
            return ProjectJson.Stringify(new Dictionary<string,object>{{"ok",true},{"settings",s},{"analysis_text",p.AnalysisText}});
        }
        public static BuildResult Build(ProjectState p,BuildResult result,BuildRequest request,string workingRoot,RasterEngine rasters,Func<bool> canceled)
        {
            if(!request.Interlace&&!request.Heightmap)return result;
            if(string.IsNullOrEmpty(p.ReferencePath)) {result.Status="waiting-for-heightmap";return result;}
            var info=ProjectJson.Parse(p.ReferenceInfoJson);
            if(p.ReferenceDetection=="Automatic"&&!object.Equals(info.GetValueOrDefault("ok"),true))
            {result.Status="heightmap-needs-review";p.AnalysisText=ProjectJson.Text(info,"message","Heightmap detection needs review.");return result;}
            var data=HeightmapEngine.Load(p.ReferencePath);
            if(!data.Grayscale)throw new InvalidOperationException("Use a grayscale heightmap for lens geometry.");
            if(p.ReferencePitchPx<2)throw new InvalidOperationException("Enter a pitch of at least 2 pixels per lens.");
            if(p.SourceFrames.Length<2){result.Status="waiting-for-sources";return result;}
            if(p.ReferencePitchPx<p.SourceFrames.Length)throw new InvalidOperationException("The heightmap has fewer than one pixel per source view within each lens. Use fewer source images or a higher-resolution heightmap.");
            bool relief=p.Optics.OutputModeSelection=="Lens-Free Relief";if(relief&&p.SourceFrames.Length!=2)throw new InvalidOperationException("Lens-Free Relief requires two source images.");
            if(canceled())throw new OperationCanceledException();
            result.DirectoryPath=Path.Combine(workingRoot,ProjectBuild.Hash(p.ProjectPath).Substring(0,20),"revisions",Guid.NewGuid().ToString("N"));Directory.CreateDirectory(result.DirectoryPath);
            string image=Path.Combine(result.DirectoryPath,"interlaced_from_heightmap.png"),map=Path.Combine(result.DirectoryPath,"heightmap_imported"+Path.GetExtension(p.ReferencePath).ToLowerInvariant());
            bool vertical=p.ReferenceOrientation=="Vertical";
            using(var bitmap=rasters.BuildInterlacedBitmap(data.Width,data.Height,p.ReferencePitchPx,vertical,p.SourceFrames,relief,p.ReferencePhasePitch+p.PhasePitch,true,p.ReferenceWidthMm/p.ReferenceHeightMm))
            { bitmap.SetResolution((float)(data.Width*25.4/p.ReferenceWidthMm),(float)(data.Height*25.4/p.ReferenceHeightMm));bitmap.Save(image,ImageFormat.Png); }
            PngCodec.SetPngPhysicalResolution(image,PngCodec.DpiToPixelsPerMeter(data.Width*25.4/p.ReferenceWidthMm),PngCodec.DpiToPixelsPerMeter(data.Height*25.4/p.ReferenceHeightMm));
            PngCodec.SetPngLenticularMetadata(image,double.Parse(p.Optics.LpiText,Inv),p.SourceFrames.Length,p.ReferenceWidthMm/25.4,p.ReferenceHeightMm/25.4,vertical,p.Optics.OutputModeSelection,0);
            if(canceled())throw new OperationCanceledException();
            File.Copy(p.ReferencePath,map,false);
            if(Path.GetExtension(map)==".png")
            {
                PngCodec.SetPngPhysicalResolution(map,PngCodec.DpiToPixelsPerMeter(data.Width*25.4/p.ReferenceWidthMm),PngCodec.DpiToPixelsPerMeter(data.Height*25.4/p.ReferenceHeightMm));
                AnnotateScale(map,p.ReferenceScaleMm);
            }
            else if(Path.GetExtension(map)==".tif"||Path.GetExtension(map)==".tiff")TiffHeightmapMetadata.Annotate(map,data.Width,data.Height,p.ReferenceWidthMm,p.ReferenceHeightMm,p.ReferenceScaleMm);
            p.InterlacedPath=image;p.HeightmapPath=map;
            p.AnalysisText=string.Format(Inv,"Built from imported heightmap: {0} x {1} pixels; {2:0.######} pixels/lens; {3:0.######} LPI; {4}; registration {5:+0.000000;-0.000000;0}. Imported height samples are preserved.",data.Width,data.Height,p.ReferencePitchPx,double.Parse(p.Optics.LpiText,Inv),p.ReferenceOrientation,p.ReferencePhasePitch+p.PhasePitch);
            if(canceled())throw new OperationCanceledException();return result;
        }
        public static void AnnotateScale(string path,double scale)
        {
            byte[] bytes=File.ReadAllBytes(path);
            using(var output=new MemoryStream())
            {
                output.Write(bytes,0,8);
                for(int offset=8;offset<bytes.Length;)
                {
                    int size=checked((int)PngCodec.Read32(bytes,offset));string type=Encoding.ASCII.GetString(bytes,offset+4,4);bool old=false;
                    if(type=="tEXt") {int end=Array.IndexOf(bytes,(byte)0,offset+8,size);old=end>offset+8&&Encoding.ASCII.GetString(bytes,offset+8,end-offset-8)=="LenticulizerHeightScaleMm";}
                    if(type=="IEND")PngCodec.WriteChunk(output,"tEXt",PngCodec.MakePngTextData("LenticulizerHeightScaleMm",scale.ToString("0.######",Inv)));
                    if(!old)output.Write(bytes,offset,size+12);offset+=size+12;
                }
                File.WriteAllBytes(path,output.ToArray());
            }
        }
    }
}
