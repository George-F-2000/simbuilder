@echo off
rem ============================================================================
rem  SimBuilder installer build - one command from repo root:
rem      build_installer.bat
rem  Chain:  PyInstaller (one-dir)  ->  Inno Setup  ->  dist\SimBuilder-Setup.exe
rem  Needs:  Python 3.12 env with the app deps + PyInstaller
rem  Workpath lives in %TEMP% - keeps churn out of the repo and dodges
rem  OneDrive sync locks when the repo lives under OneDrive.
rem          Inno Setup 6 (iscc.exe) - free: https://jrsoftware.org/isinfo.php
rem ============================================================================
setlocal
cd /d "%~dp0"

echo [0/2] clearing previous output (retries through OneDrive sync locks)...
for /l %%i in (1,1,6) do (
  if exist build\installer_dist rd /s /q build\installer_dist 2>nul
  if not exist build\installer_dist goto :cleaned
  timeout /t 3 /nobreak >nul
)
:cleaned

echo [1/2] PyInstaller one-dir build...
rem resolve a real Python (bare 'python' may be the Windows Store stub)
set "PYEXE=py -3.12"
%PYEXE% -c "pass" >nul 2>nul
if errorlevel 1 set "PYEXE=python"
%PYEXE% -c "pass" >nul 2>nul
if errorlevel 1 set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
%PYEXE% -c "pass" >nul 2>nul
if errorlevel 1 (
  echo   ERROR: no working Python found - install Python 3.12 or fix PATH
  goto :fail
)
%PYEXE% -m PyInstaller --clean --noconfirm ^
  --distpath build\installer_dist --workpath "%TEMP%\simbuilder_build_work" ^
  SimBuilder_dir.spec
if errorlevel 1 goto :fail

echo [2/2] Inno Setup...
set ISCC=iscc
where %ISCC% >nul 2>nul
if errorlevel 1 set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo   ERROR: Inno Setup not found. Install from https://jrsoftware.org/isinfo.php
  goto :fail
)
"%ISCC%" installer.iss
if errorlevel 1 goto :fail

echo.
echo   DONE: dist\SimBuilder-Setup.exe
exit /b 0

:fail
echo   BUILD FAILED
exit /b 1
