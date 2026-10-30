@echo off
if not exist "%~dp0dist\Lenticulizer.exe" (
  echo Build the application first with Build_SelfContained.bat.
  pause
  exit /b 1
)
start "" "%~dp0dist\Lenticulizer.exe"
