using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using Lenticulizer.Core;

internal static class HeightmapWorkflowChecks
{
    static int checks;
    static void Check(bool ok,string message){checks++;if(!ok)throw new Exception("Heightmap: "+message);}
    static void Compare(object a,object b,string path)
    {
        if(a is Dictionary<string,object> map)
        {
            var other=(Dictionary<string,object>)b;
            foreach(var item in map)Compare(item.Value,other[item.Key],path+"."+item.Key);
        }
        else if(a is object[] array)
        {
            var other=(object[])b;Check(array.Length==other.Length,path+" length");
            for(int i=0;i<array.Length;i++)Compare(array[i],other[i],path+"["+i+"]");
        }
        else if(a is bool||a is string)Check(a.Equals(b),path+": "+a+" vs "+b);
        else Check(Math.Abs(Convert.ToDouble(a)-Convert.ToDouble(b))<=1e-9*Math.Max(1,Math.Abs(Convert.ToDouble(a))),path+": "+a+" vs "+b);
    }
    public static void Run(string root)
    {
        string folder=Path.Combine(root,"validation","heightmap-fixtures");
        var cases=(object[])System.Text.Json.JsonSerializer.Deserialize<object[]>(File.ReadAllText(Path.Combine(folder,"cases.json"))).Select(x=>ProjectJson.Parse(x.ToString())).Cast<object>().ToArray();
        foreach(Dictionary<string,object> test in cases)
        {
            string path=Path.Combine(folder,(string)test["file"]);
            var info=HeightmapEngine.Analyze(path);
            Compare(test["expected"],info,(string)test["file"]);
            string hash=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
            if(test.ContainsKey("sha256"))Check(hash==(string)test["sha256"],"analysis preserves original bytes");
            if(test.ContainsKey("stripes"))foreach(var item in (Dictionary<string,object>)test["stripes"])
            {
                int[] expected=((object[])item.Value).Select(Convert.ToInt32).ToArray();
                int[] actual=RasterEngine.StripeIndices(expected.Length,Convert.ToDouble(test["true_pitch"]),Convert.ToDouble(test["true_phase"]),int.Parse(item.Key),false,true);
                Check(expected.SequenceEqual(actual),"Python/C# stripe assignment "+test["file"]+" views="+item.Key);
                Check(RasterEngine.StripeIndices(expected.Length,Convert.ToDouble(test["true_pitch"]),Convert.ToDouble(test["true_phase"]),int.Parse(item.Key),true,true).SequenceEqual(actual.Select(x=>int.Parse(item.Key)-1-x)),"relief polarity");
            }
            if(!object.Equals(info["ok"],true))continue;
            var doc=new Dictionary<string,object>{{"schema",1},{"settings",new Dictionary<string,object>{{"workflow","Build from heightmap"},{"mode","Automatic"},{"reference_heightmap_width_mm",80.0},{"reference_heightmap_height_mm",50.0},{"reference_heightmap_thickness_mm",2.0},{"reference_heightmap_detection","Automatic"},{"reference_heightmap_display_style","TINTED"},{"reference_heightmap_show",true}}},{"assets",new Dictionary<string,object>{{"reference_heightmap",path},{"source_frames",new[]{path,path,path}}}},{"reference_heightmap_info",info}};
            var state=SettingsRules.Read(ProjectJson.Stringify(doc),Path.Combine(folder,"project.json"),null,true);
            HeightmapWorkflow.Refresh(state);
            var solved=ProjectJson.Object(ProjectJson.Parse(ProjectSerializer.Solve(state)),"settings");
            Check(Convert.ToDouble(solved["width_mm"])==80&&Convert.ToDouble(solved["height_mm"])==50,"automatic mode preserves imported dimensions");
            Check(Convert.ToInt32(solved["views"])==3,"source count supplies views");
            Check(Math.Abs(Convert.ToDouble(solved["thickness_mm"])-2*Convert.ToDouble(info["maximum"]))<1e-12,"white-level scale applies once");
            Check(Math.Abs(Convert.ToDouble(solved["base_mm"])-2*Convert.ToDouble(info["minimum"]))<1e-12,"imported valley retained");
            double size=state.ReferenceOrientation=="Vertical"?80:50;
            double pixels=Convert.ToDouble(info[state.ReferenceOrientation=="Vertical"?"width_px":"height_px"]);
            Check(Math.Abs(Convert.ToDouble(solved["lpi"])-pixels*25.4/(size*state.ReferencePitchPx))<1e-8,"LPI uses selected physical dimension");
            string key=ProjectBuild.InterlaceKey(state);var change=state.Snapshot();change.ReferenceStyle="CLEAR";change.ReferenceShow=false;
            Check(key==ProjectBuild.InterlaceKey(change),"reference style/visibility do not invalidate production");
            change.ReferenceScaleMm+=.1;Check(key!=ProjectBuild.InterlaceKey(change),"physical height invalidates matched pair");
            var partial=SettingsRules.Read("{\"settings\":{\"workflow\":\"Build from heightmap\",\"reference_heightmap_width_mm\":60}}",state.ProjectPath,state,false);
            Check(partial.ReferenceInfoJson==state.ReferenceInfoJson,"fast solve retains imported sample metadata");
            var published=ProjectJson.Parse(ProjectSerializer.Publish(state,4,"ready",""));
            var reread=SettingsRules.Read(ProjectJson.Stringify(published),state.ProjectPath,null,true);
            Check(reread.ReferencePath==state.ReferencePath&&reread.ReferenceShow&&reread.ReferenceStyle=="TINTED","shared project round-trip");
            Check(Math.Abs(reread.ReferencePitchPx-state.ReferencePitchPx)<1e-10&&reread.ReferenceInfoJson==state.ReferenceInfoJson,"shared pitch and profiles round-trip");
        }
        var crop=RasterEngine.SourceCropForAspect(800,800,1.6);Check(crop.Width==800&&crop.Height==500&&crop.Y==150,"artwork crop uses physical aspect for non-square map pixels");
        foreach(string order in new[]{"little","big"})
        {
            string source=Path.Combine(folder,"tiff_"+order+".tif"),copy=Path.Combine(folder,"tiff_"+order+"_csharp.tif");
            byte[] original=File.ReadAllBytes(source);File.Copy(source,copy,true);
            TiffHeightmapMetadata.Annotate(copy,997,17,82,61,2.15);
            byte[] modified=File.ReadAllBytes(copy);
            Check(original.Skip(8).SequenceEqual(modified.Skip(8).Take(original.Length-8)),"TIFF pixel strips and all original entries remain unchanged: "+order);
            Check(File.ReadAllBytes(source).SequenceEqual(original),"TIFF source remains unchanged: "+order);
        }
        Console.WriteLine("PASS: "+checks+" heightmap checks; "+cases.Length+" cross-language maps; exact stripe mapping, geometry scale, shared settings and preserved source files.");
    }
}
