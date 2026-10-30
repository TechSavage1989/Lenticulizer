param(
    [string]$Destination = "vendor/FixedRuntime"
)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$destinationPath = Join-Path $root $Destination
$manifestPath = Join-Path $destinationPath "manifest.json"
if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Expected runtime manifest is missing: $manifestPath" }
$expected = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
$version = [string]$expected.version
if ($version -ne "152.0.4191.62") { throw "Unexpected pinned WebView2 version: $version" }
$cabName = "Microsoft.WebView2.FixedVersionRuntime.$version.x64.cab"
$cabUrl = "https://github.com/ciderapp/WebView2-Archives/releases/download/$version/$cabName"
$cabSha256 = "2dc7d817ddce4d036f33684425c218f1ca2d073911136e5d3f8ce9b2340569b5"
$temp = Join-Path ([IO.Path]::GetTempPath()) ("Lenticulizer-WebView2-" + [Guid]::NewGuid().ToString("N"))
$cabPath = Join-Path $temp $cabName
$expanded = Join-Path $temp "expanded"
try {
    New-Item -ItemType Directory -Path $expanded -Force | Out-Null
    Write-Host "Downloading pinned WebView2 Fixed Version runtime $version..."
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($null -ne $curl) {
        & $curl.Source --fail --location --retry 3 --retry-delay 5 --output $cabPath $cabUrl
        if ($LASTEXITCODE -ne 0) { throw "curl.exe failed with exit code $LASTEXITCODE" }
    }
    else {
        Invoke-WebRequest -Uri $cabUrl -OutFile $cabPath -UseBasicParsing
    }
    $actualCabHash = (Get-FileHash -LiteralPath $cabPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualCabHash -ne $cabSha256) { throw "WebView2 cabinet SHA-256 mismatch. Expected $cabSha256; got $actualCabHash" }
    & expand.exe $cabPath -F:* $expanded | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "expand.exe failed with exit code $LASTEXITCODE" }
    $browserExe = Get-ChildItem -LiteralPath $expanded -Recurse -Filter msedgewebview2.exe | Select-Object -First 1
    if ($null -eq $browserExe) { throw "Expanded WebView2 runtime does not contain msedgewebview2.exe" }
    $runtimeRoot = $browserExe.Directory.FullName

    $expectedBrowser = @($expected.files | Where-Object { $_.path -like 'browser/*' })
    $expectedMap = @{}
    foreach ($item in $expectedBrowser) {
        $relativePath = $item.path.Substring(8).Replace('/', [IO.Path]::DirectorySeparatorChar)
        $expectedMap[$relativePath] = $item
    }

    # Some Microsoft WebView2 cabinets contain mutable preload-data files that were
    # not present in the Lenticulizer baseline. Reconstruct the exact pinned browser
    # file set instead of silently accepting those additions.
    $actualFiles = @(Get-ChildItem -LiteralPath $runtimeRoot -Recurse -File)
    $extraFiles = @()
    foreach ($file in $actualFiles) {
        $relative = $file.FullName.Substring($runtimeRoot.Length).TrimStart('\\')
        if (-not $expectedMap.ContainsKey($relative)) {
            $extraFiles += $file
        }
    }
    if ($extraFiles.Count -gt 0) {
        Write-Host "Removing $($extraFiles.Count) runtime file(s) not present in the pinned Lenticulizer baseline..."
        foreach ($file in $extraFiles) {
            $relative = $file.FullName.Substring($runtimeRoot.Length).TrimStart('\\')
            Write-Host "  extra: $relative"
            Remove-Item -LiteralPath $file.FullName -Force
        }
        Get-ChildItem -LiteralPath $runtimeRoot -Recurse -Directory |
            Sort-Object { $_.FullName.Length } -Descending |
            ForEach-Object {
                if (-not (Get-ChildItem -LiteralPath $_.FullName -Force | Select-Object -First 1)) {
                    Remove-Item -LiteralPath $_.FullName -Force
                }
            }
    }

    foreach ($relative in $expectedMap.Keys) {
        $filePath = Join-Path $runtimeRoot $relative
        if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
            throw "Expected runtime file is missing: $relative"
        }
        $entry = $expectedMap[$relative]
        $file = Get-Item -LiteralPath $filePath
        if ($file.Length -ne [int64]$entry.size) { throw "Runtime size mismatch: $relative" }
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) { throw "Runtime SHA-256 mismatch: $relative" }
    }

    $remainingFiles = @(Get-ChildItem -LiteralPath $runtimeRoot -Recurse -File)
    if ($remainingFiles.Count -ne $expectedBrowser.Count) {
        throw "Reconstructed runtime file count mismatch. Expected $($expectedBrowser.Count); got $($remainingFiles.Count)"
    }

    foreach ($criticalRelative in @('msedgewebview2.exe','msedge.dll','EBWebView\\x64\\EmbeddedBrowserWebView.dll')) {
        $critical = Join-Path $runtimeRoot $criticalRelative
        if (-not (Test-Path -LiteralPath $critical)) { throw "Critical WebView2 binary missing: $criticalRelative" }
        $sig = Get-AuthenticodeSignature -LiteralPath $critical
        if ($sig.Status -ne 'Valid' -or $null -eq $sig.SignerCertificate -or $sig.SignerCertificate.Subject -notlike '*Microsoft Corporation*') {
            throw "Invalid Microsoft Authenticode signature: $criticalRelative ($($sig.Status))"
        }
    }

    Write-Host "Pinned runtime matches the expected baseline. Rebuilding vendor/FixedRuntime/runtime.zip..."
    python (Join-Path $root 'packaging/pack_runtime.py') $runtimeRoot --version $version
    if ($LASTEXITCODE -ne 0) { throw "pack_runtime.py failed with exit code $LASTEXITCODE" }
    if (-not (Test-Path -LiteralPath (Join-Path $destinationPath 'runtime.zip'))) { throw "runtime.zip was not created" }
    Write-Host "Fixed runtime restored successfully."
}
finally {
    if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue }
}
