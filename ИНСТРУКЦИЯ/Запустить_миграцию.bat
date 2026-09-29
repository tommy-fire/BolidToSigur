@echo off
chcp 1251 >nul
cd /d "%~dp0"
echo ============================================================
echo    Перенос картотеки:  «Орион Про» (Болид)  --^>  Sigur
echo ============================================================
echo.

echo [1/3] Проверяю Python...
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python НЕ НАЙДЕН.
  echo.
  echo  Установите Python с сайта https://www.python.org/downloads/
  echo  При установке ОБЯЗАТЕЛЬНО поставьте галочку
  echo  "Add Python to PATH" внизу первого окна установщика.
  echo  Потом запустите этот файл снова.
  echo.
  pause
  exit /b 1
)
python --version

echo.
echo [2/3] Проверяю библиотеки (первый раз нужен интернет)...
python -c "import xlwt, PIL, openpyxl, xlrd" >nul 2>&1
if errorlevel 1 (
  echo  Устанавливаю, подождите минуту-две...
  python -m pip install --upgrade pip
  python -m pip install xlwt pillow openpyxl xlrd
  if errorlevel 1 (
    echo.
    echo  Не удалось установить библиотеки. Проверьте интернет.
    echo.
    pause
    exit /b 1
  )
)
echo  Библиотеки на месте.

echo.
echo [3/3] Запускаю программу...
echo.
python "%~dp0Миграция_Болид_Sigur.pyw"
echo.
echo  Программа закрыта.
pause
