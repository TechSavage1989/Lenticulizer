using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using Lenticulizer.Core;
using Lenticulizer.Desktop;

class DropImportTests
{
    static int checks;
    static void Check(bool value, string message) { checks++; if (!value) throw new Exception(message); }
    static void Reject(Action action, string message)
    {
        bool rejected = false;
        try { action(); } catch (ArgumentException) { rejected = true; } catch (IOException) { rejected = true; } catch (InvalidDataException) { rejected = true; }
        Check(rejected, message);
    }
    static string Hash(string path) { using var s=File.OpenRead(path); return Convert.ToHexString(SHA256.HashData(s)); }
    static int Main(string[] args)
    {
        try
        {
            string root=Path.GetFullPath(args[0]), folder=Path.Combine(root,"validation","heightmap-fixtures"), extra=Path.Combine(root,"validation","drop-fixtures");
            string Map(string name)=>Path.Combine(folder,name);
            string File(string name)=>Path.Combine(extra,name);
            var before=Directory.GetFiles(folder,"*.png").Concat(Directory.GetFiles(extra)).ToDictionary(p=>p,Hash);
            foreach (string path in Directory.GetFiles(folder,"*.png").Where(p=>!Path.GetFileName(p).StartsWith("copy_")))
            {
                var info=HeightmapEngine.Analyze(path); var plan=DroppedImageImport.Analyze(new[]{path},"auto");
                Check((plan.HeightmapPath!="")==object.Equals(info["ok"],true),"fixture recognition: "+Path.GetFileName(path));
            }
            foreach(string name in new[]{"heightmap_color.png","grayscale_art.png","grayscale_interlace.png","tiny.png","source.jpg","source.bmp"})
            {
                var plan=DroppedImageImport.Analyze(new[]{File(name)},"auto");
                Check(plan.HeightmapPath=="" && plan.Sources.Single()==File(name),"artwork stays a source: "+name);
            }
            var tagged=DroppedImageImport.Analyze(new[]{File("tagged_flat.png")},"auto");
            Check(tagged.HeightmapPath!="" && !object.Equals(tagged.HeightmapInfo["ok"],true),"metadata map recognized without inventing spacing");
            var explicitMap=DroppedImageImport.Analyze(new[]{Map("grid.png")},"heightmap");
            Check(explicitMap.HeightmapPath!="" && explicitMap.Sources.Length==0,"ambiguous explicit map import");
            Reject(()=>DroppedImageImport.Analyze(new[]{File("heightmap_color.png")},"heightmap"),"reject color in reference target");
            Reject(()=>DroppedImageImport.Analyze(new[]{File("source.jpg")},"heightmap"),"reference format restriction");
            Reject(()=>DroppedImageImport.Analyze(new[]{Map("filter_8_0.png"),Map("filter_16_0.png")},"auto"),"reject two maps before applying");
            Reject(()=>DroppedImageImport.Analyze(new[]{Map("filter_8_0.png"),File("source.jpg")},"heightmap"),"dedicated map target is single file");
            Reject(()=>DroppedImageImport.Analyze(new[]{File("corrupt.png")},"auto"),"corrupt image reports an error");
            Reject(()=>DroppedImageImport.Analyze(new[]{File("missing.png")},"auto"),"missing file reports an error");
            Reject(()=>DroppedImageImport.Analyze(Array.Empty<string>(),"auto"),"empty native drop rejected");
            Reject(()=>DroppedImageImport.Analyze(new[]{File("source.jpg")},"unknown"),"unknown target rejected");
            var repeated=DroppedImageImport.Analyze(new[]{Map("filter_8_0.png"),Map("filter_8_0.png")},"auto");
            Check(repeated.HeightmapPath!="","duplicate native map paths treated as one file");
            var mixed=DroppedImageImport.Analyze(new[]{File("heightmap_color.png"),Map("filter_16_0.png"),File("source.jpg")},"auto");
            Check(mixed.Sources.SequenceEqual(new[]{File("heightmap_color.png"),File("source.jpg")}),"mixed drop preserves artwork order");
            Check(mixed.HeightmapPath==Map("filter_16_0.png"),"mixed drop separates the map");
            var current=ProjectJson.Parse("{\"settings\":{\"workflow\":\"Build from source frames\",\"mode\":\"Semi-Automatic\",\"width_mm\":140,\"height_mm\":90,\"thickness_mm\":2.2,\"ior\":1.5},\"assets\":{\"source_frames\":[],\"reference_heightmap\":\"\"},\"custom\":\"keep\"}");
            string currentJson=ProjectJson.Stringify(current);
            var update=DroppedImageImport.BuildUpdate(mixed,current); var merged=IntegratedProject.Merge(current,update.Patch);
            Check(update.HeightmapImported && update.SourcesAdded==2 && update.Priority=="rebuild-pair","one mixed transaction requests generation");
            var settings=ProjectJson.Object(merged,"settings"); var assets=ProjectJson.Object(merged,"assets");
            Check(ProjectJson.Number(settings,"reference_heightmap_width_mm",0)==140 && ProjectJson.Number(settings,"reference_heightmap_height_mm",0)==90,"missing physical metadata uses current dimensions");
            Check(ProjectJson.Number(settings,"reference_heightmap_thickness_mm",0)==2.2,"missing height metadata uses current thickness");
            Check(ProjectJson.Text(settings,"mode","")=="Semi-Automatic" && ProjectJson.Number(settings,"ior",0)==1.5 && ProjectJson.Text(merged,"custom","")=="keep","unrelated settings preserved");
            Check(ProjectJson.Text(settings,"workflow","")=="Build from source frames","import previews before explicit build choice");
            Check(ProjectJson.Number(settings,"views",0)==2 && ((string[])assets["source_frames"]).SequenceEqual(mixed.Sources),"map excluded from source count and order");
            Check(object.Equals(settings["reference_heightmap_show"],true),"import shows reference preview");
            Check(ProjectJson.Text(settings,"reference_heightmap_detection","")=="Automatic" && ProjectJson.Number(settings,"reference_heightmap_pitch_px",0)>0,"automatic spacing saved");
            Check(ProjectJson.Stringify(current)==currentJson,"planning does not mutate current project");
            var mapOnly=DroppedImageImport.BuildUpdate(repeated,current);
            Check(mapOnly.Priority=="reference" && mapOnly.SourcesAdded==0 && mapOnly.HasChanges,"reference-only import does not regenerate procedural outputs");
            var metadata=DroppedImageImport.BuildUpdate(DroppedImageImport.Analyze(new[]{Map("Horizontal_13_0.123_cosine.png")},"auto"),current);
            settings=ProjectJson.Object(metadata.Patch,"settings");
            Check(ProjectJson.Text(settings,"reference_heightmap_orientation","")=="Horizontal","horizontal direction detected");
            Check(Math.Abs(ProjectJson.Number(settings,"reference_heightmap_phase_pitch",0)-.123)<.015,"detected registration retained");
            Check(ProjectJson.Number(settings,"reference_heightmap_thickness_mm",0)==1.72,"metadata height scale retained");
            Check(ProjectJson.Number(settings,"reference_heightmap_width_mm",0)>0 && ProjectJson.Number(settings,"reference_heightmap_width_mm",0)!=140,"metadata physical size retained");
            var active=IntegratedProject.Merge(current,new Dictionary<string,object>{{"settings",new Dictionary<string,object>{{"workflow","Build from heightmap"}}}});
            var activeDrop=DroppedImageImport.BuildUpdate(mixed,active);
            Check(activeDrop.Priority=="rebuild-pair" && !ProjectJson.Object(activeDrop.Patch,"settings").ContainsKey("workflow"),"active imported-map workflow preserved");
            var addOnly=DroppedImageImport.BuildUpdate(DroppedImageImport.Analyze(new[]{File("source.jpg")},"auto"),active);
            Check(addOnly.Priority=="rebuild-pair" && !ProjectJson.Object(addOnly.Patch,"settings").ContainsKey("workflow"),"new sources retain imported lens geometry");
            var duplicates=DroppedImageImport.BuildUpdate(new ImageDropPlan{Sources=mixed.Sources},merged);
            Check(!duplicates.HasChanges && duplicates.SourcesAdded==0,"source duplicates do not regenerate");
            var full=IntegratedProject.Merge(current,new Dictionary<string,object>{{"assets",new Dictionary<string,object>{{"source_frames",Enumerable.Range(0,8).Select(i=>"existing"+i+".png").ToArray()}}}});
            var capped=DroppedImageImport.BuildUpdate(mixed,full);
            Check(capped.SourcesAdded==0 && capped.SourcesSkipped==2 && capped.HeightmapImported,"source limit does not swallow a dropped map");
            Check(!ProjectJson.Object(capped.Patch,"assets").ContainsKey("source_frames"),"existing eight sources preserved");
            var ambiguous=DroppedImageImport.BuildUpdate(explicitMap,current);
            Check(ProjectJson.Number(ProjectJson.Object(ambiguous.Patch,"settings"),"reference_heightmap_pitch_px",99)==0 && ambiguous.Message.Contains("Manual"),"ambiguous map requires review without guessed pitch");
            foreach(var item in before)Check(Hash(item.Key)==item.Value,"original file untouched: "+Path.GetFileName(item.Key));
            Console.WriteLine("PASS: "+checks+" drop-import checks using the actual application assembly: map recognition, grayscale-artwork rejection, mixed order, metadata, settings, rebuild intent, limits, immutable inputs and explicit fallback.");
            return 0;
        }
        catch(Exception error){Console.Error.WriteLine(error);return 1;}
    }
}
