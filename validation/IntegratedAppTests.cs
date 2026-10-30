using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Threading;
using Lenticulizer.Core;
using Lenticulizer.Desktop;

[assembly: System.Runtime.Versioning.SupportedOSPlatform("windows10.0.17763")]

// References the actual managed application assembly bundled into the EXE.
// Its real embedded controller, core,
// worker queue and file transactions run here without a WebView or a window.
static class IntegratedAppTests
{
    static int checks, pairs;
    static void Check(bool value, string message) { if (!value) throw new Exception(message); checks++; }
    static Dictionary<string,object> Settings(Dictionary<string,object> value) { return ProjectJson.Object(value,"settings"); }
    static string Text(Dictionary<string,object> value,string key) { return ProjectJson.Text(value,key,""); }
    static void Wait(Func<bool> condition, string message)
    {
        DateTime limit = DateTime.UtcNow.AddSeconds(15);
        while (!condition()) { if (DateTime.UtcNow > limit) throw new Exception("Timed out: " + message); Thread.Sleep(15); }
    }
    static Dictionary<string,object> Ready(IntegratedProject app, int revision)
    {
        Dictionary<string,object> result = null;
        Wait(delegate { result=app.Read(); return ProjectJson.Number(result,"revision",0)>revision && Text(ProjectJson.Object(result,"generation"),"status")!="queued"; },"generation revision "+revision);
        Check(Text(ProjectJson.Object(result,"generation"),"status")=="ready",ProjectJson.Stringify(result));
        string a=DesktopFiles.Asset(result,"interlaced"), b=DesktopFiles.Asset(result,"heightmap"); string why;
        Check(PngCodec.VerifyImagePair(a,b,out why),"Output pair: "+why);
        Check(File.ReadAllBytes(b)[24]==16,"Heightmap lost 16-bit depth");
        return result;
    }
    static void EqualFile(string a,string b,string message) { Check(File.ReadAllBytes(a).SequenceEqual(File.ReadAllBytes(b)),message); }
    static Dictionary<string,object> PatchSettings(Dictionary<string,object> settings)
    { return new Dictionary<string,object>{{"settings",settings}}; }
    static void Write(string path,Dictionary<string,object> value)
    {
        for(int i=0;;i++)
        {
            try { using(var s=new FileStream(path,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None)) { byte[] bytes=new System.Text.UTF8Encoding(false).GetBytes(ProjectJson.Stringify(value));s.Position=0;s.Write(bytes,0,bytes.Length);s.SetLength(bytes.Length);s.Flush(true); } return; }
            catch(IOException){if(i==40)throw;Thread.Sleep(10);}
        }
    }
    static void CheckResources(IntegratedProject app, string root, string directory, string[] generated, string source, string tiff)
    {
        foreach (string relative in new[] { "src/index.html", "src/app.css", "src/bridge.js", "src/renderer.js", "assets/Lenticulizer.ico", "assets/Lenticulizer_Icon_Source.svg" })
        {
            var result = AppResources.Read(AppResources.Origin + "/" + relative, "GET", null);
            Check(result.Status == 200, "Embedded resource status: " + relative);
            Check(result.Bytes.SequenceEqual(File.ReadAllBytes(Path.Combine(root, "ui", relative))), "Embedded interface differs from build source: " + relative);
            Check(result.Headers.Contains("Content-Length: " + result.Bytes.Length + "\r\n"), "Resource content length: " + relative);
        }
        var formats = new[] { new { Extension = ".jpg", Type = "image/jpeg", Format = ImageFormat.Jpeg }, new { Extension = ".bmp", Type = "image/bmp", Format = ImageFormat.Bmp } };
        foreach (var format in formats)
        {
            string file = Path.Combine(directory, "preview # & + % ' \u00e9" + format.Extension);
            using (var bitmap = new Bitmap(source)) bitmap.Save(file, format.Format);
            app.ImageInfo(file);
            var result = AppResources.Read(IntegratedProject.ImageUrl(file), "GET", app.ReadImage);
            Check(result.Status == 200 && result.Headers.Contains("Content-Type: " + format.Type + "\r\n"), "Browser image type: " + format.Extension);
            Check(result.Bytes.SequenceEqual(File.ReadAllBytes(file)), "Browser image bytes: " + format.Extension);
        }
        foreach (string file in new[] { source, generated[0], generated[1], tiff })
        {
            var result = AppResources.Read(IntegratedProject.ImageUrl(file) + "&v=123", "GET", app.ReadImage);
            Check(result.Status == 200 && result.Headers.Contains("Content-Type: image/png\r\n"), "PNG source/generated/TIFF response");
            Check(result.Headers.Contains("Cache-Control: no-store\r\n"), "Regenerated image can be stale in the browser");
            Check(result.Bytes.SequenceEqual(app.ReadImage(file)), "Image endpoint changed preview bytes");
            using (var bytes = new MemoryStream(result.Bytes))
            using (var bitmap = new Bitmap(bytes)) Check(bitmap.Width > 0 && bitmap.Height > 0, "Image response is not decodable");
        }
        var map = AppResources.Read(IntegratedProject.ImageUrl(generated[1]), "GET", app.ReadImage);
        Check(map.Bytes[24] == 16 && map.Bytes[25] == 0, "Browser response changed 16-bit heightmap");
        var head = AppResources.Read(IntegratedProject.ImageUrl(source), "HEAD", app.ReadImage);
        Check(head.Status == 200 && head.Bytes.Length == 0 && head.Headers.Contains("Content-Length: " + new FileInfo(source).Length + "\r\n"), "HEAD response metadata");
        foreach (string address in new[] { "https://unrelated.invalid/src/index.html", AppResources.Origin + "/default-project.json", AppResources.Origin + "/src/../../app/Program.cs" })
            Check(AppResources.Read(address, "GET", app.ReadImage).Status == 404, "Unexpected route exposes local content");
        Check(AppResources.Read(AppResources.Origin + "/local-image", "GET", app.ReadImage).Status == 400, "Missing image path");
        Check(AppResources.Read(IntegratedProject.ImageUrl(source) + "&path=another", "GET", app.ReadImage).Status == 400, "Ambiguous image path");
        Check(AppResources.Read(IntegratedProject.ImageUrl(source), "POST", app.ReadImage).Status == 405, "Unexpected resource method");
        string unselected = Path.Combine(directory, "not-in-project.png"); File.Copy(source, unselected);
        bool denied = false;
        try { AppResources.Read(IntegratedProject.ImageUrl(unselected), "GET", app.ReadImage); }
        catch (UnauthorizedAccessException) { denied = true; }
        Check(denied, "Resource handler bypasses active image authorization");
        string seen = null;
        string windowsPath = "C:\\images\\space # & + % ' \u00e9\\Red.png";
        AppResources.Read(IntegratedProject.ImageUrl(windowsPath), "GET", value => { seen = value; return new byte[0]; });
        Check(seen == windowsPath, "Windows path is decoded incorrectly by the image endpoint");
        Console.WriteLine("PASS: embedded interface and image responses, PNG/JPEG/BMP/TIFF previews, generated PNG16, special-character paths, cache headers and resource access checks.");
    }
    static void HeightmapPipelines(IntegratedProject app,string root,string directory,string projectPath,string[] frames)
    {
        HeightmapEngine.OtherImageReader=WindowsHeightmapReader.Read;
        foreach(string endian in new[]{"little","big"})
        {
            string tiff=Path.Combine(root,"validation","heightmap-fixtures","tiff_"+endian+"_copy.tif");
            var data=HeightmapEngine.Load(tiff);
            Check(data.BitDepth==16&&data.Width==997&&data.Height==17,"TIFF sample format");
            Check(Math.Abs(data.WidthMm-82)<1e-5&&Math.Abs(data.HeightMm-61)<1e-5&&Math.Abs(data.ScaleMm-2.15)<1e-9,"TIFF physical and height metadata");
            Check((bool)HeightmapEngine.Analyze(tiff)["ok"],"TIFF lens detection");
        }
        foreach(string orientation in new[]{"Vertical","Horizontal"})
        {
            string source=Path.Combine(directory,"imported_"+orientation+".png");
            File.Copy(Path.Combine(root,"validation","heightmap-fixtures",orientation+"_39_0_triangle.png"),source);
            byte[] original=File.ReadAllBytes(source);var info=HeightmapEngine.Analyze(source);
            var settings=new Dictionary<string,object>{{"workflow","Build from heightmap"},{"mode","Automatic"},{"reference_heightmap_width_mm",80},{"reference_heightmap_height_mm",50},{"reference_heightmap_thickness_mm",1.72},{"reference_heightmap_detection","Automatic"},{"reference_heightmap_show",false},{"phase_pitch",0}};
            var written=app.Patch(new Dictionary<string,object>{{"settings",settings},{"assets",new Dictionary<string,object>{{"reference_heightmap",source},{"source_frames",frames}}},{"reference_heightmap_info",info}},"rebuild-pair",projectPath);
            var result=Ready(app,(int)ProjectJson.Number(written,"revision",0));string[] pair=DesktopFiles.Pair(result);
            var solved=Settings(result);var map=HeightmapEngine.Load(pair[1]);var input=HeightmapEngine.Load(source);
            Check(File.ReadAllBytes(source).SequenceEqual(original),"Heightmap import was modified");
            Check(map.Width==input.Width&&map.Height==input.Height&&map.X.SequenceEqual(input.X)&&map.Y.SequenceEqual(input.Y),"Imported height samples changed");
            Check(Text(solved,"orientation")==orientation&&Convert.ToDouble(solved["width_mm"])==80&&Convert.ToDouble(solved["height_mm"])==50,"Imported geometry settings changed");
            using(var bitmap=new Bitmap(pair[0]))
            {
                Check(bitmap.Width==input.Width&&bitmap.Height==input.Height,"Imported pair dimensions differ");
                bool vertical=orientation=="Vertical";
                int[] stripes=RasterEngine.StripeIndices(vertical?input.Width:input.Height,Convert.ToDouble(solved["reference_heightmap_pitch_px"]),Convert.ToDouble(solved["reference_heightmap_phase_pitch"]),frames.Length,false,true);
                Color[] colors=frames.Select(frame=>{using(var b=new Bitmap(frame))return b.GetPixel(b.Width/2,b.Height/2);}).ToArray();
                for(int i=0;i<stripes.Length;i++)
                {
                    Color actual=bitmap.GetPixel(vertical?i:bitmap.Width/2,vertical?bitmap.Height/2:i),expected=colors[stripes[i]];
                    Check(actual.R==expected.R&&actual.G==expected.G&&actual.B==expected.B,"Imported interlace stripe/phase mismatch "+orientation+" pixel "+i);
                }
            }
            var style=app.Patch(PatchSettings(new Dictionary<string,object>{{"reference_heightmap_display_style","CLEAR"},{"reference_heightmap_show",true}}),"reference",projectPath);
            var styled=Ready(app,(int)ProjectJson.Number(style,"revision",0));
            Check(DesktopFiles.Pair(styled).SequenceEqual(pair),"Reference display caused regeneration");
            var phase=app.Patch(PatchSettings(new Dictionary<string,object>{{"phase_pitch",.2}}),"rebuild-pair",projectPath);
            var shifted=Ready(app,(int)ProjectJson.Number(phase,"revision",0));
            Check(DesktopFiles.Asset(shifted,"interlaced")!=pair[0],"Heightmap registration did not rebuild image");
            Check(File.ReadAllBytes(source).SequenceEqual(original),"Registration edited original map");
            var exact=HeightmapEngine.Load(DesktopFiles.Asset(shifted,"heightmap"));Check(exact.X.SequenceEqual(input.X)&&exact.Y.SequenceEqual(input.Y),"Registration shifted height samples");
        }
        Console.WriteLine("PASS: imported heightmap pipelines, vertical/horizontal stripe pixels, scale, reference-only updates and unchanged source samples.");
    }
    [STAThread]
    static int Main(string[] args)
    {
        string directory=Path.Combine(Path.GetTempPath(),"LenticulizerIntegrated_"+Guid.NewGuid().ToString("N"));
        IntegratedProject app=null;
        try
        {
            string root=Path.GetFullPath(args[0]);Directory.CreateDirectory(directory);
            string session=Path.Combine(directory,"session");Directory.CreateDirectory(session);
            string path=Path.Combine(session,"project.json"), template=Path.Combine(root,"backend","Lenticular-Builder.blend");
            var initial=ProjectJson.Parse(File.ReadAllText(Path.Combine(root,"app","default-project.json")));
            var originalSettings=Settings(initial); originalSettings["width_mm"]=8.1; originalSettings["height_mm"]=6.7;
            initial["changed_by"]="integrated";initial["project_name"]="fixture";initial["extension"]=new Dictionary<string,object>{{"keep",42}};
            Write(path,initial);
            var frames=new List<string>();
            for(int frame=0;frame<2;frame++)
            {
                string file=Path.Combine(directory,"source # & + % ' \u00e9 "+frame+".png");
                using(var bitmap=new Bitmap(27+frame,21+frame,PixelFormat.Format24bppRgb))
                { for(int y=0;y<bitmap.Height;y++)for(int x=0;x<bitmap.Width;x++)bitmap.SetPixel(x,y,Color.FromArgb((x*11+frame*90)%256,(y*13+frame*10)%256,(x+y+frame*110)%256));bitmap.Save(file,ImageFormat.Png); }
                frames.Add(file);
            }
            app=new IntegratedProject(path,Path.Combine(directory,"working"),template,directory);
            var errors=new List<string>();app.Diagnostic += value => {lock(errors)errors.Add(value);};
            int notifications=0;bool switched=false;app.Updated += value => {Interlocked.Increment(ref notifications);if(value.ContainsKey("project_switched"))switched=true;};
            app.Start();
            Wait(()=>Text(ProjectJson.Object(app.Read(),"generation"),"status")=="waiting-for-sources","initial empty project");
            string before=File.ReadAllText(path);
            foreach(string mode in new[]{"Automatic","Semi-Automatic","Manual"})
            {
                var solved=app.Solve(PatchSettings(new Dictionary<string,object>{{"mode",mode}}),path);
                Check(Text(Settings(solved),"mode")==mode,"Fast solve mode");
            }
            Check(File.ReadAllText(path)==before,"Fast solve wrote a project or scheduled generation");
            foreach(string mode in new[]{"Automatic","Semi-Automatic","Manual"})
            foreach(string orientation in new[]{"Vertical","Horizontal"})
            foreach(string output in new[]{"Lenticular Lens","Lens-Free Relief"})
            {
                var settings=Settings(ProjectJson.Parse(ProjectJson.Stringify(initial)));
                settings["mode"]=mode;settings["orientation"]=orientation;settings["output_mode"]=output;
                settings["lpi_helper_mode"]="Recommended";
                var patch=PatchSettings(settings);patch["assets"]=new Dictionary<string,object>{{"source_frames",frames.ToArray()}};
                var written=app.Patch(patch,"rebuild-pair",path);
                var result=Ready(app,(int)ProjectJson.Number(written,"revision",0));
                Check(Text(Settings(result),"mode")==mode,"Committed settings mode");
                Check(Text(Settings(result),"orientation")==orientation,"Committed orientation");
                Check(ProjectJson.Number(ProjectJson.Object(result,"extension"),"keep",0)==42,"Unknown project metadata was lost");
                var state=SettingsRules.Read(ProjectJson.Stringify(written),path,null,true);
                using(var reference=new ProjectBuild(Path.Combine(directory,"direct")))
                using(var generated=reference.Run(new BuildRequest(state,1,"",true,true),()=>false))
                {
                    EqualFile(DesktopFiles.Asset(result,"interlaced"),generated.State.InterlacedPath,"Embedded host changed interlace bytes");
                    EqualFile(DesktopFiles.Asset(result,"heightmap"),generated.State.HeightmapPath,"Embedded host changed heightmap bytes");
                }
                pairs++;
            }
            var manual=PatchSettings(new Dictionary<string,object>{{"mode","Manual"},{"output_mode","Lenticular Lens"},{"lpi_helper_mode","Manual"},{"lpi",24},{"print_profile","Manual Thickness"},{"manual_thickness_mm",1.86},{"base_mode","Manual base height"},{"manual_base_mm",0.3},{"build_detail_mode","Custom"},{"pixels_per_lenticule",48}});
            var manualWrite=app.Patch(manual,"rebuild-pair",path);var manualResult=Ready(app,(int)ProjectJson.Number(manualWrite,"revision",0));
            Check(Text(Settings(manualResult),"print_profile")=="Manual Thickness","Manual print selection");
            Check(Math.Abs(ProjectJson.Number(Settings(manualResult),"manual_thickness_mm",0)-1.86)<1e-8,"Manual thickness was lost");
            var snapshot=app.Read();string[] pair=DesktopFiles.Pair(snapshot);
            string export=Path.Combine(directory,"export");Directory.CreateDirectory(export);
            string[] destinations={Path.Combine(export,"interlace.png"),Path.Combine(export,"heightmap.png")};
            DesktopFiles.Export(pair,destinations);EqualFile(pair[0],destinations[0],"Interlace export bytes");EqualFile(pair[1],destinations[1],"Heightmap export bytes");
            File.WriteAllText(destinations[0],"Existing file");string obstructed=Path.Combine(export,"obstructed");Directory.CreateDirectory(obstructed);
            bool failed=false;try{DesktopFiles.Export(pair,new[]{destinations[0],obstructed});}catch(IOException){failed=true;}
            Check(failed,"Partial export failure did not fail");Check(File.ReadAllText(destinations[0])=="Existing file","Partial export did not roll back");
            Check(!Directory.GetFiles(export,"*.tmp").Any()&&!Directory.GetFiles(export,"*.bak").Any(),"Export temporary files leaked");
            app.ImageInfo(frames[0]);Check(app.ReadImage(frames[0]).SequenceEqual(File.ReadAllBytes(frames[0])),"Authorized source image bytes");
            string tiff=Path.Combine(directory,"preview.tiff");using(var bitmap=new Bitmap(frames[0]))bitmap.Save(tiff,ImageFormat.Tiff);
            byte[] originalTiff=File.ReadAllBytes(tiff);app.ImageInfo(tiff);byte[] previewTiff=app.ReadImage(tiff);
            Check(previewTiff.Length>24&&previewTiff[0]==137&&previewTiff[1]==80,"TIFF preview is not a browser-readable PNG");
            Check(File.ReadAllBytes(tiff).SequenceEqual(originalTiff),"TIFF preview changed the original image");
            Check(IntegratedProject.ImageUrl(frames[0]).Contains("%23")&&IntegratedProject.ImageUrl(frames[0]).Contains("%26"),"Image URL escaping");
            bool denied=false;try{app.ReadImage(path);}catch(UnauthorizedAccessException){denied=true;}Check(denied,"Arbitrary project file was served as an image");
            CheckResources(app,root,directory,pair,frames[0],tiff);
            Dictionary<string,object> rapid=null;
            for(int i=0;i<20;i++)rapid=app.Patch(PatchSettings(new Dictionary<string,object>{{"mode",i==19?"Manual":"Semi-Automatic"},{"orientation",i%2==0?"Vertical":"Horizontal"}}),"rebuild-pair",path);
            var last=Ready(app,(int)ProjectJson.Number(rapid,"revision",0));
            Check(Text(Settings(last),"mode")=="Manual"&&Text(Settings(last),"orientation")=="Horizontal","A superseded edit was committed");
            var blender=ProjectJson.Parse(File.ReadAllText(path));blender["changed_by"]="blender";blender["revision"]=(int)ProjectJson.Number(blender,"revision",0)+1;
            Settings(blender)["orientation"]="Vertical";Settings(blender)["mode"]="Automatic";
            blender["requested_change"]=new Dictionary<string,object>{{"priority","rebuild-pair"},{"scope","images"}};
            Write(path,blender);var fromBlender=Ready(app,(int)ProjectJson.Number(blender,"revision",0));
            Check(Text(Settings(fromBlender),"mode")=="Automatic"&&Text(Settings(fromBlender),"orientation")=="Vertical","Blender changes did not reach the embedded core");
            Check(DesktopFiles.Asset(fromBlender,"interlaced")!=DesktopFiles.Asset(last,"interlaced"),"Blender orientation did not regenerate interlace");
            foreach(string kind in new[]{"analyze","calibration","blender-sync","blender-open","blender-reset","blender-export"})
            {
                string id=Guid.NewGuid().ToString("N"), destination=kind=="calibration"?export:Path.Combine(export,"portable.zip");
                var request=new Dictionary<string,object>{{"id",id},{"kind",kind},{"destination",destination}};
                var written=app.Patch(new Dictionary<string,object>{{"command_request",request}},kind,path);
                var result=Ready(app,(int)ProjectJson.Number(written,"revision",0));
                var command=ProjectJson.Object(result,"command_result");
                Check(Text(command,"id")==id&&Text(command,"status")=="ready",kind+": "+ProjectJson.Stringify(command));
                if(kind=="blender-open"||kind=="blender-reset")EqualFile(Text(command,"path"),template,"Command baseline");
                if(kind=="blender-export")
                {
                    string unpacked=Path.Combine(directory,"portable");ZipFile.ExtractToDirectory(destination,unpacked);
                    EqualFile(Path.Combine(unpacked,"Lenticulizer_3D_Template.blend"),template,"Portable baseline");
                }
            }
            foreach(string dir in app.HandoffDirectories())Check(!File.Exists(Path.Combine(dir,"pending_blender_project.txt")),"Ordinary project/core command created a reconnect pointer");
            string imported=DesktopFiles.Asset(app.Read(),"interlaced");byte[] importedBytes=File.ReadAllBytes(imported);
            var importedWrite=app.Patch(new Dictionary<string,object>{{"settings",new Dictionary<string,object>{{"workflow","Use existing interlaced image"},{"mode","Semi-Automatic"},{"lpi_helper_mode","Manual"}}},{"assets",new Dictionary<string,object>{{"interlaced_image",imported},{"heightmap",""}}}},"rebuild-heightmap",path);
            var importedResult=Ready(app,(int)ProjectJson.Number(importedWrite,"revision",0));
            Check(DesktopFiles.Asset(importedResult,"interlaced")==imported&&File.ReadAllBytes(imported).SequenceEqual(importedBytes),"Imported artwork was replaced");
            HeightmapPipelines(app,root,directory,path,frames.ToArray());
            string shared=Path.Combine(directory,"shared");Directory.CreateDirectory(shared);string sharedPath=Path.Combine(shared,"project.json");Write(sharedPath,initial);
            foreach(string dir in app.HandoffDirectories()){Directory.CreateDirectory(dir);File.WriteAllText(Path.Combine(dir,"pending_app_project.txt"),sharedPath);}
            Wait(()=>app.ProjectPath==sharedPath&&switched,"shared-project handoff");
            foreach(string dir in app.HandoffDirectories())Check(!File.Exists(Path.Combine(dir,"pending_app_project.txt")),"Duplicate handoff was not consumed");
            bool stale=false;try{app.Patch(manual,"rebuild-pair",path);}catch(InvalidOperationException){stale=true;}Check(stale,"A late action modified a newly opened project");
            app.Dispose();Check(app.WaitForStop(5000),"Embedded worker did not stop");
            int count=notifications;Thread.Sleep(250);Check(count==notifications,"Notification arrived after shutdown");
            Console.WriteLine("PASS: "+checks+" integrated application checks; "+pairs+" generated pairs match direct processing byte-for-byte. Modes, manual values, latest edits, Blender edits/handoffs, commands, imported artwork, exports/rollback, image access and shutdown exercised in the actual application assembly.");
            return 0;
        }
        catch(Exception error){Console.Error.WriteLine(error);return 1;}
        finally{if(app!=null){app.Dispose();app.WaitForStop(5000);}try{Directory.Delete(directory,true);}catch{}}
    }
}
