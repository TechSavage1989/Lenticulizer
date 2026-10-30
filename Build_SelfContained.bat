@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "LENTICULIZER_PAUSE=1"
if /i "%~1"=="--no-pause" set "LENTICULIZER_PAUSE=0"
set "DOTNET_CLI_TELEMETRY_OPTOUT=1"
set "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE=true"
set "MSBuildEnableWorkloadResolver=false"
where dotnet >nul 2>nul
if errorlevel 1 (
  echo Building from source requires the Microsoft .NET 10 SDK. Running the release EXE does not.
  goto failed
)
if not exist "vendor\FixedRuntime\runtime.zip" (
  echo Restoring pinned WebView2 Fixed Version build asset...
  call Restore_Build_Assets.bat
  if errorlevel 1 goto failed
)
echo Building Lenticulizer 3D Alpha 32 with bundled .NET and WebView2...
call validation\Run_Source_Checks.bat
if errorlevel 1 goto failed
dotnet restore Lenticulizer.csproj --configfile NuGet.Config
if errorlevel 1 goto failed
dotnet build Lenticulizer.csproj -c Release --no-restore --disable-build-servers
if errorlevel 1 goto failed
call validation\Run_Core_Parity_Tests.bat
if errorlevel 1 goto failed
dotnet publish Lenticulizer.csproj -c Release --no-restore --disable-build-servers -o dist
if errorlevel 1 goto failed
start "" /wait "dist\Lenticulizer.exe" --verify-core "%CD%\validation\Last_Embedded_Core_Result.txt"
if errorlevel 1 goto failed
start "" /wait "dist\Lenticulizer.exe" --verify-runtime "%CD%\validation\Last_Runtime_Check.json"
if errorlevel 1 goto failed
call Run_Windows_UI_Check.bat --no-pause
if errorlevel 1 goto failed
if exist release rmdir /s /q release
mkdir release
"dist\Lenticulizer.exe" --package-release "%CD%\release"
if errorlevel 1 goto failed
echo Build, Windows checks and release packaging completed.
echo Portable executable: %CD%\dist\Lenticulizer.exe
echo Release assets: %CD%\release
if "%LENTICULIZER_PAUSE%"=="1" pause
exit /b 0
:failed
echo Build or a required check failed. See the output above.
if "%LENTICULIZER_PAUSE%"=="1" pause
exit /b 1
