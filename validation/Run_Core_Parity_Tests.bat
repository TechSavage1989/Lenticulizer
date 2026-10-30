@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
echo Restoring validation projects from the repository NuGet configuration...
for %%P in (validation\RuntimeTests\RuntimeTests.csproj validation\DropImportTests\DropImportTests.csproj validation\IntegratedAppTests\IntegratedAppTests.csproj) do (
  dotnet restore "%%P" --configfile "%CD%\NuGet.Config"
  if errorlevel 1 exit /b 1
)
echo Checking the Microsoft .NET runtime and processing compatibility...
dotnet run --project validation\RuntimeTests\RuntimeTests.csproj -c Release --no-restore -- "%CD%"
if errorlevel 1 exit /b 1
echo Checking dropped-image recognition and heightmap imports...
dotnet run --project validation\DropImportTests\DropImportTests.csproj -c Release --no-restore -- "%CD%"
if errorlevel 1 exit /b 1
echo Checking the Windows image pipeline, commands, exports and embedded controller...
dotnet run --project validation\IntegratedAppTests\IntegratedAppTests.csproj -c Release --no-restore -- "%CD%"
if errorlevel 1 exit /b 1
exit /b 0
