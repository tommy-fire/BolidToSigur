@echo off
chcp 1251 >nul
cd /d "%~dp0"
echo ============================================================
echo    Выгрузка из резервной копии "Орион Про" (файл .bak)
echo ============================================================
echo.

echo [1/3] Проверяю Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python не установлен.
  echo.
  echo  Скачай Python с сайта https://www.python.org/downloads/
  echo  При установке поставь галочку "Add Python to PATH" - это важно.
  echo  Затем запусти этот файл снова.
  echo.
  pause
  exit /b 1
)
python --version

echo.
echo [2/3] Проверяю компоненты (устанавливаются один раз)...
python -c "import pyodbc" >nul 2>&1
if errorlevel 1 (
  echo  Устанавливаю, нужен интернет...
  python -m pip install --upgrade pip
  python -m pip install pyodbc
  if errorlevel 1 (
    echo.
    echo  Не получилось установить компонент. Проверь интернет.
    echo.
    pause
    exit /b 1
  )
)
echo  Компоненты на месте.

echo.
echo [3/3] Запускаю программу...
echo.
python "%~dp0Выгрузка_из_резервной_копии.pyw"
echo.
echo  Программа закрыта.
pause
