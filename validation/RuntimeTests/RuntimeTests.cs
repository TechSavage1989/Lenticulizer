using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using Lenticulizer.Core;
using Lenticulizer.Desktop;

internal static class RuntimeTests
{
    static int checks, cases, maps, exactPngs, tolerantNumbers;
    static void Check(bool ok, string message) { checks++; if (!ok) throw new Exception(message); }
    static string Hash(byte[] bytes) { return Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant(); }
    static void Equal(object expected, object actual, string name)
    {
        if (expected == null || actual == null) { Check(expected == actual,name); return; }
        var expectedMap = expected as Dictionary<string,object>; var actualMap = actual as Dictionary<string,object>;
        if (expectedMap != null)
        {
            Check(actualMap != null && expectedMap.Keys.OrderBy(x=>x).SequenceEqual(actualMap.Keys.OrderBy(x=>x)),name+" keys");
            foreach (var item in expectedMap) Equal(item.Value,actualMap[item.Key],name+"."+item.Key);
            return;
        }
        var expectedArray = expected as object[]; var actualArray = actual as object[];
        if (expectedArray != null)
        {
            Check(actualArray != null && expectedArray.Length == actualArray.Length,name+" array");
            for (int i=0;i<expectedArray.Length;i++) Equal(expectedArray[i],actualArray[i],name+"["+i+"]");
            return;
        }
        if (expected is string || expected is bool) { Check(expected.Equals(actual),name+": "+expected+" != "+actual); return; }
        double a=Convert.ToDouble(expected), b=Convert.ToDouble(actual);
        Check(double.IsFinite(b) && Math.Abs(a-b)<=Math.Max(1,Math.Abs(a))*1e-12,name+": "+a+" != "+b);
        if (a!=b) tolerantNumbers++;
    }
    static byte[] PngPixels(byte[] png)
    {
        Check(png[0]==137 && png[24]==16 && png[25]==0,"PNG16 signature and format");
        using (var compressed = new MemoryStream())
        {
            for (int offset=8;offset<png.Length;)
            {
                int count=checked((int)PngCodec.Read32(png,offset));
                if (Encoding.ASCII.GetString(png,offset+4,4)=="IDAT") compressed.Write(png,offset+8,count);
                offset+=count+12;
            }
            byte[] zlib=compressed.ToArray();
            using (var input=new MemoryStream(zlib,2,zlib.Length-6))
            using (var deflate=new DeflateStream(input,CompressionMode.Decompress))
            using (var pixels=new MemoryStream()) { deflate.CopyTo(pixels); return pixels.ToArray(); }
        }
    }
    static void Compatibility(string root,string temporary)
    {
        var golden=ProjectJson.Parse(File.ReadAllText(Path.Combine(root,"validation","Alpha21_Runtime_Reference.json")));
        foreach (Dictionary<string,object> item in (object[])golden["cases"])
        {
            var expected=(Dictionary<string,object>)item["expected"];
            var actual=RuntimeCompatibility.Evaluate((Dictionary<string,object>)item["input"],temporary,(cases++).ToString());
            if (expected.ContainsKey("png"))
            {
                Check(actual.ContainsKey("png"),"Heightmap generation: "+ProjectJson.Stringify(actual));
                byte[] a=Convert.FromBase64String((string)expected["png"]),b=Convert.FromBase64String((string)actual["png"]);
                Check(a.Take(33).SequenceEqual(b.Take(33)),"Heightmap dimensions and format");
                Check(PngPixels(a).SequenceEqual(PngPixels(b)),"Heightmap pixels differ across runtimes");
                if (a.SequenceEqual(b)) exactPngs++;
                maps++; expected.Remove("png"); actual.Remove("png");
            }
            Equal(expected,ProjectJson.Parse(ProjectJson.Stringify(actual)),"case "+cases);
        }
    }
    static void Serializer()
    {
        var value=ProjectJson.Parse("\uFEFF{\"ticks\":638900000000000001,\"float\":1.25e-7,\"decimal\":1.234567890123456789,\"name\":\"C:\\\\image # & + % \\u00e9.png\",\"array\":[null,true,2,{\"keep\":\"yes\"}]}");
        Check(value["ticks"] is long && (long)value["ticks"]==638900000000000001L,"64-bit timestamps preserved");
        Check(value["decimal"] is decimal && (decimal)value["decimal"]==1.234567890123456789m,"Decimal precision preserved");
        Check(value["array"] is object[],"Legacy array representation");
        Equal(value,ProjectJson.Parse(ProjectJson.Stringify(value)),"unknown metadata roundtrip");
        Check(ProjectJson.Number(value,"float",0)==1.25e-7,"Exponent number");
        bool rejected=false;try { ProjectJson.Parse("[1,2]"); } catch(ArgumentException){rejected=true;}
        Check(rejected,"Non-object projects rejected");
        rejected=false;try { ProjectJson.Parse("{broken}"); } catch(ArgumentException){rejected=true;}
        Check(rejected,"Malformed projects rejected");
    }
    static void CacheFixtures(string temporary)
    {
        var source=new Dictionary<string,byte[]>{{"browser/msedgewebview2.exe",new byte[4096]},{"assets/unicode \u00e9 # +.txt",Encoding.UTF8.GetBytes("runtime fixture")}};
        byte[] payload;
        using(var output=new MemoryStream())
        {
            using(var zip=new ZipArchive(output,ZipArchiveMode.Create,true))
                foreach(var item in source) using(var entry=zip.CreateEntry(item.Key).Open()) entry.Write(item.Value);
            payload=output.ToArray();
        }
        var manifest=new RuntimeManifest{version="fixture",archive_sha256=Hash(payload),archive_bytes=payload.Length,unpacked_bytes=source.Sum(x=>x.Value.Length),files=source.Select(x=>new RuntimeFile{path=x.Key,size=x.Value.Length,sha256=Hash(x.Value)}).ToList()};
        string cache=Path.Combine(temporary,"cache # & + \u00e9"); Directory.CreateDirectory(cache);
        string abandoned=Path.Combine(cache,manifest.archive_sha256.Substring(0,24)+".staging-abandoned"); Directory.CreateDirectory(abandoned); File.WriteAllText(Path.Combine(abandoned,"partial"),"partial");
        int opened=0;
        Func<Stream> open=()=>{Interlocked.Increment(ref opened);return new MemoryStream(payload,false);};
        Func<string> prepare=()=>BundledRuntime.PrepareCache(cache,manifest,open,null,CancellationToken.None,false);
        var together=Task.WhenAll(Task.Run(prepare),Task.Run(prepare)).GetAwaiter().GetResult();
        Check(together[0]==together[1] && opened==2,"Concurrent starts publish one verified cache");
        Check(!Directory.Exists(abandoned),"Interrupted extraction recovered");
        Check(BundledRuntime.Ready(together[0],manifest,true,CancellationToken.None),"Extracted fixture hashes");
        string reused=prepare();Check(reused==together[0] && opened==2,"Warm start does not reopen archive");
        File.Delete(BundledRuntime.Target(reused,source.Keys.First()));
        string repaired=prepare();Check(repaired!=reused && BundledRuntime.Ready(repaired,manifest,true,CancellationToken.None),"Missing runtime file repaired");
        Check(prepare()==repaired,"Repair cache reused");
        string changed=BundledRuntime.Target(repaired,source.Keys.Last());byte[] modified=File.ReadAllBytes(changed);modified[0]^=1;File.WriteAllBytes(changed,modified);
        string verified=BundledRuntime.PrepareCache(cache,manifest,open,null,CancellationToken.None,true);
        Check(verified!=repaired && BundledRuntime.Ready(verified,manifest,true,CancellationToken.None),"Full verification repairs same-size corruption");
        foreach(string path in new[]{"../outside","/outside","C:/outside","folder\\..\\outside"})
        { bool denied=false;try{BundledRuntime.Target(cache,path);}catch(InvalidDataException){denied=true;}Check(denied,"Unsafe archive path rejected"); }
        var cancellation=new CancellationTokenSource();cancellation.Cancel();bool canceled=false;
        try{BundledRuntime.PrepareCache(cache,manifest,open,null,cancellation.Token,false);}catch(OperationCanceledException){canceled=true;}
        Check(canceled,"Startup cancellation honored");
        byte[] corrupted=(byte[])payload.Clone();corrupted[corrupted.Length-1]^=1;bool invalid=false;
        try{BundledRuntime.PrepareCache(Path.Combine(temporary,"bad"),manifest,()=>new MemoryStream(corrupted),null,CancellationToken.None,false);}catch(InvalidDataException){invalid=true;}
        Check(invalid,"Corrupted embedded archive rejected");
        Check(!Directory.GetDirectories(Path.Combine(temporary,"bad"),"*.staging-*").Any(),"Failed extraction cleaned up");
    }
    static void EmbeddedRuntime(string temporary)
    {
        Assembly app=typeof(ProjectJson).Assembly;
        Check(!app.GetReferencedAssemblies().Any(x=>x.Name=="mscorlib" || x.Name=="Lenticulizer.Core" || x.Name=="System.Web.Extensions"),"No legacy processing/framework dependencies");
        var verify=app.GetType("Lenticulizer.Desktop.Program").GetMethod("VerifyEmbeddedCore",BindingFlags.Static|BindingFlags.NonPublic);
        Check((int)verify.Invoke(null,new object[]{""})==0,"Actual app collection/optics/PNG16 self-check");
        foreach(string resource in new[]{"/src/index.html","/src/bridge.js","/src/renderer.js","/src/app.css","/assets/Lenticulizer.ico"})
            Check(AppResources.Read(AppResources.Origin+resource,"GET",null).Status==200,"Embedded UI: "+resource);
        string windowsPath="C:\\sources\\image \u00e9 # & + % '.png",seen=null;
        var response=AppResources.Read(IntegratedProject.ImageUrl(windowsPath),"GET",path=>{seen=path;return new byte[]{137,80,78,71};});
        Check(seen==windowsPath && response.Status==200 && response.Headers.Contains("Content-Type: image/png"),"Same-origin image bridge path decoding");
        RuntimeManifest manifest;
        using(var input=app.GetManifestResourceStream("Lenticulizer.FixedRuntime.json"))manifest=JsonSerializer.Deserialize<RuntimeManifest>(input);
        string exported=Path.Combine(temporary,"exported-build-assets");
        BundledRuntime.ExportForBuild(exported);
        using(var input=File.OpenRead(Path.Combine(exported,"runtime.zip")))
            Check(Convert.ToHexString(SHA256.HashData(input)).Equals(manifest.archive_sha256,StringComparison.OrdinalIgnoreCase),"Source build payload export hash");
        using(var input=File.OpenRead(Path.Combine(exported,"manifest.json")))
            Check(JsonSerializer.Deserialize<RuntimeManifest>(input).archive_sha256==manifest.archive_sha256,"Source build manifest export");
        string cache=BundledRuntime.PrepareCache(Path.Combine(temporary,"real-runtime"),manifest,()=>app.GetManifestResourceStream("Lenticulizer.FixedRuntime.zip"),null,CancellationToken.None,true);
        Check(BundledRuntime.Ready(cache,manifest,true,CancellationToken.None),"All real bundled runtime file hashes verified");
        foreach(string file in new[]{"browser/msedgewebview2.exe","WebView2Loader.dll","Lenticular-Builder.blend","blender/Lenticulizer_Blender_Addon_v1.18.38.zip","notices/Runtime-Notices.txt"})
            Check(File.Exists(BundledRuntime.Target(cache,file)),"Bundled runtime resource: "+file);
        Console.WriteLine("PASS: extracted and verified "+manifest.files.Count+" actual bundled files, including browser "+manifest.version+".");
    }
    static int Main(string[] args)
    {
        string root=Path.GetFullPath(args[0]);
        string temporary=Path.Combine(root,"validation","runtime-check-"+Guid.NewGuid().ToString("N")); Directory.CreateDirectory(temporary);
        try
        {
            HeightmapWorkflowChecks.Run(root); Serializer(); CacheFixtures(temporary); EmbeddedRuntime(temporary); Compatibility(root,temporary);
            Console.WriteLine("PASS: "+checks+" checks on Microsoft .NET "+Environment.Version+"; "+cases+" compatibility cases; "+maps+" matching PNG16 pixel arrays; "+exactPngs+" byte-identical PNGs; "+tolerantNumbers+" numeric values required the 1e-12 tolerance.");
            return 0;
        }
        catch(Exception error){Console.Error.WriteLine(error);return 1;}
        finally{Directory.Delete(temporary,true);}
    }
}
