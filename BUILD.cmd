@echo off
setlocal
cd /d "%~dp0"
py -3 -c "import sys; assert (3,11) <= sys.version_info[:2] <= (3,14) and sys.maxsize > 2**32" >nul 2>&1
if errorlevel 1 goto fail
if not exist ".build-env\Scripts\python.exe" py -3 -m venv ".build-env"
if errorlevel 1 goto fail
".build-env\Scripts\python.exe" -m pip --isolated install --index-url https://pypi.org/simple --only-binary=:all: --require-hashes -r requirements-build-windows.lock
if errorlevel 1 goto fail
".build-env\Scripts\python.exe" build_windows.py
if errorlevel 1 goto fail
pause
exit /b 0
:fail
echo Build failed. Use 64-bit Python 3.11 through 3.14 and Inno Setup 6; inspect the build error.
pause
exit /b 1
