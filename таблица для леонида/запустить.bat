@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Запускаю журнал занятий...
echo Не закрывайте это окно, пока работаете с таблицами.
echo.
echo Если телефон в Wi-Fi не открывает журнал:
echo   1. Закройте это окно
echo   2. Запустите файл «разрешить-телефон.bat» и нажмите Да
echo   3. Снова запустите этот файл
echo.

set PYTHONUNBUFFERED=1
python server.py
if errorlevel 1 (
  echo.
  echo Не удалось запустить программу.
  echo Установите Python: https://www.python.org/downloads/
  echo При установке отметьте пункт "Add python.exe to PATH".
  pause
)
