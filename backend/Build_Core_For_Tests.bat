@echo off
setlocal
cd /d "%~dp0.."
rem Compatibility entry point. Alpha 22 compiles its core into the application.
dotnet build Lenticulizer.csproj -c Release --disable-build-servers
exit /b %errorlevel%
