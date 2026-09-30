@echo off
cd /d "%~dp0"
python --version
if errorlevel 1 goto fail
python -c "import xlwt, PIL"
if errorlevel 1 python -m pip install -r requirements-offline.txt
if errorlevel 1 goto fail
python start_safe.py
pause
exit /b
:fail
echo Install Python and dependencies. See README.
pause
