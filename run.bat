@echo off
chcp 65001 >nul
setlocal
REM IwannaseeManga launcher (Windows).
REM Double-click to open the window, OR:  run.bat INPUT [-o OUTPUT]
REM   INPUT can be a folder of images OR a single image file (you can drag it on).
REM The wrapper is stdlib-only, so launch it with ANY Python and let it
REM auto-detect BallonsTranslator. Prefer the system launcher; fall back to
REM BallonsTranslator's own venv Python if that is the only one available.
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py"
if not defined PYEXE ( where python >nul 2>nul && set "PYEXE=python" )
if not defined PYEXE if defined IWSM_BT_DIR if exist "%IWSM_BT_DIR%\venv\Scripts\python.exe" set "PYEXE=%IWSM_BT_DIR%\venv\Scripts\python.exe"
if not defined PYEXE if exist "%USERPROFILE%\BallonsTranslator\venv\Scripts\python.exe" set "PYEXE=%USERPROFILE%\BallonsTranslator\venv\Scripts\python.exe"
if not defined PYEXE (
  echo [IwannaseeManga] No Python found. Install Python 3.8+ from python.org,
  echo   or set IWSM_BT_DIR to your BallonsTranslator folder, then run again.
  pause
  exit /b 1
)
"%PYEXE%" "%~dp0iwannaseemanga.py" %*
pause
