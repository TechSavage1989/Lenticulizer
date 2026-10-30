@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if not "%~1"=="" (
  if not exist "%~f1" exit /b 1
  start "" /wait "%~f1" --export-runtime "%~dp0vendor\FixedRuntime"
  if errorlevel 1 exit /b 1
  if not exist "%~dp0vendor\FixedRuntime\runtime.zip" exit /b 1
  echo The bundled build assets have been recovered from the supplied Lenticulizer executable.
  exit /b 0
)
where powershell >nul 2>nul
if errorlevel 1 (
  echo PowerShell is required to restore the pinned WebView2 Fixed Version runtime.
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\restore_fixed_runtime.ps1"
if errorlevel 1 exit /b 1
if not exist "%~dp0vendor\FixedRuntime\runtime.zip" exit /b 1
exit /b 0
