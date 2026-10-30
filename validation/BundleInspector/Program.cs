using System;
using System.IO;
using System.Reflection;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text.Json;
class Inspect {
static int Main(string[] args) {
try {
var sdk=Assembly.LoadFrom(args[0]);
var method=sdk.GetType("Microsoft.NET.HostModel.Bundle.Bundler").GetMethod("IsBundle",BindingFlags.Static|BindingFlags.Public|BindingFlags.NonPublic);
object[] input={args[1],0L};
if(!(bool)method.Invoke(null,input)) throw new Exception("Not a .NET single-file bundle");
long header=(long)input[1];
using var file=File.OpenRead(args[1]); using var reader=new BinaryReader(file);
file.Position=0x3c;int pe=reader.ReadInt32(); file.Position=pe;
if(reader.ReadUInt32()!=0x4550 || reader.ReadUInt16()!=0x8664) throw new Exception("Apphost is not Windows x64");
file.Position=header;
uint major=reader.ReadUInt32(),minor=reader.ReadUInt32();int count=reader.ReadInt32();string id=reader.ReadString();
if(major!=6 || minor!=0 || count<200 || count>1000) throw new Exception("Unexpected bundle header");
long depsOffset=reader.ReadInt64(),depsSize=reader.ReadInt64(),configOffset=reader.ReadInt64(),configSize=reader.ReadInt64();ulong flags=reader.ReadUInt64();
if(flags!=0)throw new Exception("Unexpected compatibility extraction mode");
var entries=new List<(long Offset,long Size,long Compressed,byte Type,string Path)>();
for(int i=0;i<count;i++) entries.Add((reader.ReadInt64(),reader.ReadInt64(),reader.ReadInt64(),reader.ReadByte(),reader.ReadString()));
if(file.Position!=file.Length) throw new Exception("Unexpected trailing bundle data");
var proofs=new List<object>();
foreach(var entry in entries) {
if(entry.Compressed!=0 || entry.Offset<0 || entry.Size<=0 || entry.Offset+entry.Size>header)throw new Exception("Invalid entry: "+entry.Path);
string source=Path.Combine(args[2],entry.Path);if(entry.Path.EndsWith(".deps.json")) source=Path.Combine(args[4],entry.Path);if(!File.Exists(source))throw new Exception("Missing build input: "+entry.Path);
using var hash=IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
file.Position=entry.Offset;long remaining=entry.Size;byte[] buffer=new byte[1024*1024];
while(remaining>0){int n=file.Read(buffer,0,(int)Math.Min(buffer.Length,remaining));if(n==0)throw new Exception("Truncated entry");hash.AppendData(buffer,0,n);remaining-=n;}
byte[] actual=hash.GetHashAndReset();using var reference=File.OpenRead(source);
if(reference.Length!=entry.Size || !actual.SequenceEqual(SHA256.HashData(reference))) throw new Exception("Bundle differs from build input: "+entry.Path);
proofs.Add(new {path=entry.Path,bytes=entry.Size,type=entry.Type,sha256=Convert.ToHexString(actual).ToLowerInvariant()});
}
foreach(string required in new[]{"Lenticulizer.dll","System.Private.CoreLib.dll","System.Text.Json.dll","System.Drawing.Common.dll","System.Windows.Forms.dll","Microsoft.Web.WebView2.Core.dll","Microsoft.Web.WebView2.WinForms.dll","Lenticulizer.runtimeconfig.json","Lenticulizer.deps.json"}) if(!entries.Any(x=>x.Path==required))throw new Exception("Runtime dependency not bundled: "+required);
if(entries.Any(x=>x.Path=="Lenticulizer.Core.dll"))throw new Exception("External core in bundle");
// The Microsoft Windows singlefilehost statically links CoreCLR and ClrJIT.
// Confirm the apphost has a native code section matching that exact SDK host.
using(var host=File.OpenRead(args[5])) using(var hr=new BinaryReader(host)) {
byte[] Section(BinaryReader r,string wanted) {
r.BaseStream.Position=0x3c;int h=r.ReadInt32();r.BaseStream.Position=h+6;int n=r.ReadUInt16();r.BaseStream.Position=h+20;int optional=r.ReadUInt16();r.BaseStream.Position=h+24+optional;
for(int i=0;i<n;i++){string name=System.Text.Encoding.ASCII.GetString(r.ReadBytes(8)).TrimEnd('\0');r.BaseStream.Position+=8;int length=r.ReadInt32(),offset=r.ReadInt32();r.BaseStream.Position+=16;if(name==wanted){r.BaseStream.Position=offset;return r.ReadBytes(length);}}
throw new Exception("Native host section missing");
}
if(!Section(reader,".text").SequenceEqual(Section(hr,".text")))throw new Exception("Singlefilehost native runtime code does not match SDK host");
}
file.Position=configOffset;var runtime=JsonDocument.Parse(reader.ReadBytes((int)configSize));
var options=runtime.RootElement.GetProperty("runtimeOptions");
if(options.TryGetProperty("frameworks",out _)||options.TryGetProperty("framework",out _))throw new Exception("Runtime config requires installed framework");
var versions=options.GetProperty("includedFrameworks").EnumerateArray().Select(x=>x.GetProperty("name").GetString()+"/"+x.GetProperty("version").GetString()).ToArray();
if(!versions.Contains("Microsoft.NETCore.App/10.0.11")||!versions.Contains("Microsoft.WindowsDesktop.App/10.0.11"))throw new Exception("Incorrect bundled frameworks");
string[] unbundled=Directory.GetFiles(args[2],"*",SearchOption.AllDirectories).Select(x=>Path.GetRelativePath(args[2],x)).Except(entries.Select(x=>x.Path)).ToArray();
File.WriteAllText(args[3],JsonSerializer.Serialize(new {ok=true,platform="Windows x64",bundle_version=major,entry_count=count,frameworks=versions,native_runtime="CoreCLR and ClrJIT statically linked in Microsoft singlefilehost; native code matches SDK input",entries=proofs,build_files_not_in_bundle=unbundled},new JsonSerializerOptions{WriteIndented=true}));
Console.WriteLine("PASS: Windows x64 single EXE; "+count+" bundled files match the actual build inputs, including .NET 10.0.11, WinForms, WebView2 SDK and embedded processing. No installed framework required by runtimeconfig.");
Console.WriteLine("Build inputs outside the bundle: "+string.Join(", ",unbundled));
return 0;
} catch(Exception e){Console.Error.WriteLine(e);return 1;}
}}
