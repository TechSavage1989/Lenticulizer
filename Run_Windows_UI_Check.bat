@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "LENTICULIZER_APP=%~dp0dist\Lenticulizer.exe"
set "LENTICULIZER_REPORT=%~dp0validation\Last_Windows_UI_Check.json"
if not exist "%LENTICULIZER_APP%" (
  echo Run Build_SelfContained.bat to compile the application first.
  exit /b 1
)
echo Checking the packaged Windows interface, source previews and generation...
echo The app opens a temporary test session and closes when checks finish.
start "" /wait "%LENTICULIZER_APP%" --verify-ui "%LENTICULIZER_REPORT%"
set "LENTICULIZER_CHECK_RESULT=%errorlevel%"
if exist "%LENTICULIZER_REPORT%" type "%LENTICULIZER_REPORT%"
if not "%LENTICULIZER_CHECK_RESULT%"=="0" echo Windows interface verification failed.
if /I not "%~1"=="--no-pause" pause
exit /b %LENTICULIZER_CHECK_RESULT%
