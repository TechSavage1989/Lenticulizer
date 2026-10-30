@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "PYTHON_CMD=python"
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python is required for the release source checks.
    echo Install Python and run: python -m pip install -r validation\requirements.txt
    exit /b 1
  )
  set "PYTHON_CMD=py -3"
)
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js is required for the release JavaScript checks.
  exit /b 1
)
%PYTHON_CMD% -c "import numpy, PIL"
if errorlevel 1 (
  echo Python validation dependencies are missing.
  echo Run: %PYTHON_CMD% -m pip install -r validation\requirements.txt
  exit /b 1
)
echo Checking JavaScript syntax and desktop bridge behavior...
node --check ui\src\bridge.js || exit /b 1
node --check ui\src\renderer.js || exit /b 1
node --check ui\src\test-output.js || exit /b 1
node validation\BridgeTests.js || exit /b 1
node validation\DropUiTests.js || exit /b 1
echo Checking image, Blender, updater, source-layout and source-package contracts...
%PYTHON_CMD% validation\DesktopHeightmapContractChecks.py || exit /b 1
%PYTHON_CMD% validation\HeightmapFixtures.py || exit /b 1
%PYTHON_CMD% validation\BlenderHeightmapChecks.py || exit /b 1
%PYTHON_CMD% validation\Alpha32FoundationChecks.py || exit /b 1
%PYTHON_CMD% validation\UpdaterContractChecks.py || exit /b 1
%PYTHON_CMD% validation\RootGuardChecks.py || exit /b 1
%PYTHON_CMD% validation\SourceArchiveChecks.py || exit /b 1
echo Source checks passed.
exit /b 0
