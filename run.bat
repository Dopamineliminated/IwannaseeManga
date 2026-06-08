@echo off
chcp 65001 >nul
REM IwannaseeManga launcher (Windows).
REM Usage:  run.bat <input_folder> [-o <output_folder>]
REM    or:  drag a folder onto this file.
REM Point IWSM_BT_DIR at your BallonsTranslator checkout if it isn't in your home folder.
if "%IWSM_BT_DIR%"=="" set "IWSM_BT_DIR=%USERPROFILE%\BallonsTranslator"
"%IWSM_BT_DIR%\venv\Scripts\python.exe" "%~dp0iwannaseemanga.py" %*
pause
