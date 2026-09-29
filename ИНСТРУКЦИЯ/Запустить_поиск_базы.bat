@echo off
chcp 1251 >nul
cd /d "%~dp0"
echo ============================================================
echo    Поиск базы данных "Орион Про" на этом компьютере
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
  echo  Python НЕ НАЙДЕН. Установите с https://www.python.org/downloads/
  echo  с галочкой "Add Python to PATH" и запустите снова.
  echo.
  pause
  exit /b 1
)

python -c "import pyodbc" >nul 2>&1
if errorlevel 1 (
  echo  Устанавливаю библиотеку pyodbc ^(нужен интернет^)...
  python -m pip install pyodbc
)

python "%~dp0Поиск_базы_Болид.py"
