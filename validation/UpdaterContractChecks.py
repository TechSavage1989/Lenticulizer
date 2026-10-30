from pathlib import Path
import json, re, tempfile, zipfile

root=Path(__file__).resolve().parent.parent

def text(rel): return (root/rel).read_text(encoding='utf-8')

program=text('app/Program.cs')
csproj=text('Lenticulizer.csproj')
window=text('app/AppWindow.cs')
service=text('app/UpdateService.cs')
installer=text('app/UpdateInstaller.cs')
prefs=text('app/AppPreferences.cs')
packager=text('app/ReleasePackager.cs')
bridge=text('ui/src/bridge.js')
renderer=text('ui/src/renderer.js')
html=text('ui/src/index.html')
build=text('Build_SelfContained.bat')
source_checks=text('validation/Run_Source_Checks.bat')
parity_checks=text('validation/Run_Core_Parity_Tests.bat')
nuget=text('NuGet.Config')
start=text('Start_Lenticulizer.bat')
ui_check=text('Run_Windows_UI_Check.bat')

# Stable identity and package entry point.
assert '3.0.0-alpha.32' in program
assert '<AssemblyName>Lenticulizer</AssemblyName>' in csproj
assert 'AssemblyInformationalVersion("3.0.0-alpha.32")' in program
for value in (build,start,ui_check):
    assert 'Lenticulizer.exe' in value
assert 'Lenticulizer_3D_v3.0.0-alpha.32_SelfContained.exe' not in build
assert 'Lenticulizer_3D.exe' not in renderer
assert '--package-release' in program and '--package-release' in build
assert 'Lenticulizer_Windows_Portable.zip' in packager
assert 'update-manifest.json' in packager
assert 'SHA256SUMS.txt' in packager
assert 'CompressionLevel.NoCompression' in packager
assert 'call validation\\Run_Source_Checks.bat' in build
assert 'dotnet restore Lenticulizer.csproj --configfile NuGet.Config' in build
assert 'https://api.nuget.org/v3/index.json' in nuget and '<clear />' in nuget
assert '--configfile "%CD%\\NuGet.Config"' in parity_checks
for check in ('BridgeTests.js','DropUiTests.js','Alpha32FoundationChecks.py','UpdaterContractChecks.py','RootGuardChecks.py','SourceArchiveChecks.py'):
    assert check in source_checks, check

# Native check scheduling and focus behavior.
assert 'System.Windows.Forms.Timer' in window and 'Interval = 300000' in window
assert 'Shown +=' in window and 'CheckUpdatesSafe(false)' in window
assert 'Activated +=' in window and 'TimeSpan.FromMinutes(2)' in window
assert 'SemaphoreSlim(1, 1)' in service
assert 'singleFlight.Dispose();' not in service
assert 'TimeSpan.FromSeconds(10)' in service

# Conditional requests, cached results, throttling and clear error states.
assert 'If-None-Match' in service and 'response.Headers.ETag' in service
assert 'cache.ReleasesJson' in service
assert 'RetryAfter' in service and 'X-RateLimit-Reset' in service
assert 'BaseStatus("error"' in service
assert 'BaseStatus("offline"' in service and 'NetworkInterface.GetIsNetworkAvailable()' in service
assert 'BaseStatus("unavailable"' in service
assert 'BaseStatus(newer ? "available" : "up_to_date"' in service

# Feed identity and transport boundaries.
assert 'https://api.github.com/repos/TechSavage1989/Lenticulizer/releases?per_page=20' in service
assert 'techsavage1989.lenticulizer' in service and 'techsavage1989.lenticulizer' in packager
assert 'const string PackageName = "Lenticulizer_Windows_Portable.zip"' in service
assert 'string.Equals(packageName, PackageName, StringComparison.Ordinal)' in service
assert 'packageAssetSize != size' in service
for host in ('github.com','api.github.com','objects.githubusercontent.com','github-releases.githubusercontent.com','release-assets.githubusercontent.com'):
    assert host in service, host
assert 'uri.Scheme' in service and 'Uri.UriSchemeHttps' in service
assert 'MaximumDownloadBytes = 1610612736L' in service

# Cryptographic/package/archive/executable identity checks.
assert 'SHA256.HashData' in service
assert 'lastPublishedBytes' in service and 'progressClock.ElapsedMilliseconds >= 250' in service
assert 'archive.Entries.Count != 1' in service
assert 'entry.FullName.Replace' in service and '"Lenticulizer.exe"' in service
assert 'compression ratio is not allowed' in service
assert 'Update archive path escapes staging.' in service
assert "stream.ReadByte() != 'M'" in service and "stream.ReadByte() != 'Z'" in service
assert 'FileVersionInfo.GetVersionInfo' in service
assert 'info.ProductName' in service and '"Lenticulizer"' in service
assert 'info.ProductVersion' in service

# Explicit user-controlled download/install and active-operation restart guard.
for method in ('update:check','update:download','update:install'):
    assert method in window and method in bridge
assert 'BusyForRestart()' in window
assert 'Save any external work, then install the verified update and restart Lenticulizer?' in window
assert 'downloadUpdate' in renderer and 'installUpdate' in renderer
assert 'onUpdateStatus' in renderer and 'update-status' in window
assert 'Read more' in html or 'Read more' in renderer
# No startup/timer path invokes DownloadAsync or Begin install automatically.
for line in window.splitlines():
    if 'Shown +=' in line or 'Activated +=' in line or 'updateTimer.Tick' in line:
        assert 'DownloadAsync' not in line and 'UpdateInstaller.Begin' not in line

# Per-user mutable state.
assert 'Environment.SpecialFolder.LocalApplicationData' in program
assert 'Path.Combine(Program.LocalRoot, "Lenticulizer", "Settings")' in prefs
assert 'Path.Combine(Program.LocalRoot, "Lenticulizer", "Updates")' in service
assert 'Path.Combine(Program.LocalRoot, "Lenticulizer", "Updates")' in installer
assert 'Path.Combine(LocalRoot, "Lenticulizer", "Logs")' in program

# Installer: same target path, one rollback, same-filesystem replacement, health-confirmed restart and restore.
assert 'Environment.ProcessPath' in installer
assert 'EnsureNoOtherRunningTarget(target)' in installer and 'Process.GetProcessesByName' in installer
assert 'Close the other Lenticulizer window before installing the update.' in installer
assert 'Lenticulizer.previous.exe' in installer
assert 'LenticulizerUpdateHelper-' in installer and 'Directory.GetFiles(HelperRoot, "LenticulizerUpdateHelper-*.exe")' in installer
assert 'WaitForHealth' in installer and '75000' in installer
assert '--update-health' in installer
assert 'File.Copy(backup, target, true)' in installer
assert 'backupCreated' in installer and 'RestoreAndRelaunch(target, backup, targetDirectory)' in installer
assert 'Rollback failed:' in installer
assert 'Quote(plan.PackagePath)' in installer and 'TryDelete(packagePath)' in installer
assert 'Path.Combine(targetDirectory' in installer
assert 'File.Copy(staged, sameVolumeStage, true)' in installer
assert 'Process.Start' in installer
assert 'UpdateInstaller.ReportHealthy(updateHealthToken)' in window
assert 'Task.Delay(5000)' in window and 'UpdateInstaller.CleanupCompletedUpdateArtifacts()' in window
assert 'UpdateInstaller.CleanupCompletedUpdateArtifacts();' not in program

# UI elements and manual action contract.
for id_ in ('updateBanner','updateHeadline','updateVersionText','updateNotes','updateReadMoreButton','updateDownloadButton','updateInstallButton','updateDismissButton'):
    assert f'id="{id_}"' in html, id_
assert 'Check for updates' in html

# Active validation projects must follow the stable assembly name.
for rel in ('validation/IntegratedAppTests/IntegratedAppTests.csproj','validation/DropImportTests/DropImportTests.csproj','validation/RuntimeTests/RuntimeTests.csproj'):
    value=text(rel)
    assert 'Reference Include="Lenticulizer"' in value
    assert 'Lenticulizer.dll' in value
    assert 'Lenticulizer_3D.dll' not in value
bundle=text('validation/BundleInspector/Program.cs')
for name in ('Lenticulizer.dll','Lenticulizer.runtimeconfig.json','Lenticulizer.deps.json'):
    assert name in bundle

# Root guard is part of the foundation and must pass from the extracted source tree.
assert (root/'scripts/root-allowlist.txt').is_file()
assert (root/'scripts/check_root.py').is_file()
assert (root/'validation/RootGuardChecks.py').is_file()

# Isolated archive-contract negative controls mirror the deliberately narrow updater format.
def acceptable_zip(path):
    with zipfile.ZipFile(path) as z:
        infos=z.infolist()
        if len(infos)!=1: return False
        n=infos[0].filename.replace('\\','/')
        if n.lower()!='lenticulizer.exe': return False
        if '..' in n.split('/') or n.startswith('/'): return False
        return infos[0].file_size>0
with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    good=td/'good.zip'
    with zipfile.ZipFile(good,'w',zipfile.ZIP_STORED) as z: z.writestr('Lenticulizer.exe',b'MZ'+b'0'*64)
    assert acceptable_zip(good)
    extra=td/'extra.zip'
    with zipfile.ZipFile(extra,'w',zipfile.ZIP_STORED) as z:
        z.writestr('Lenticulizer.exe',b'MZ'+b'0'*64); z.writestr('helper.exe',b'MZ')
    assert not acceptable_zip(extra)
    traversal=td/'traversal.zip'
    with zipfile.ZipFile(traversal,'w',zipfile.ZIP_STORED) as z: z.writestr('../Lenticulizer.exe',b'MZ')
    assert not acceptable_zip(traversal)

print('PASS: Alpha 32 updater/stable-launch/per-user-state contract and archive negative controls.')
