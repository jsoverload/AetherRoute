@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto setup
py -3 -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,14) and sys.maxsize > 2**32" >nul 2>&1
if not errorlevel 1 goto pylauncher
python -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,14) and sys.maxsize > 2**32" >nul 2>&1
if not errorlevel 1 goto pythonlauncher
echo This tool needs 64-bit Python 3.11 through 3.14, including tkinter.
echo Install Python from python.org, extract this ZIP, then run START.cmd again.
pause
exit /b 1
:pylauncher
py -3 -m venv ".venv"
if errorlevel 1 goto fail
goto setup
:pythonlauncher
python -m venv ".venv"
if errorlevel 1 goto fail
:setup
if exist ".venv\ready-aetherroute-rc6.txt" goto launch
echo First-time setup: installing the local image-processing dependencies.
echo This requires internet access. Later launches run locally.
".venv\Scripts\python.exe" -m pip --isolated install --disable-pip-version-check --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r "requirements-windows.lock"
if errorlevel 1 goto fail
".venv\Scripts\python.exe" -c "import cv2, numpy, PIL, mss, tkinter"
if errorlevel 1 goto fail
echo ready>".venv\ready-aetherroute-rc6.txt"
:launch
".venv\Scripts\python.exe" "app.py"
if errorlevel 1 goto fail
exit /b 0
:fail
echo.
echo Setup or startup failed. Check Python, internet access and folder permissions.
pause
exit /b 1
