@echo off
chcp 65001 >nul
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Сейчас Windows спросит разрешение.
  echo Нажмите Да — без этого телефон в Wi-Fi журнал не увидит.
  echo.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo Открываю доступ с телефона...
netsh advfirewall firewall delete rule name=JournalLocalPhone >nul 2>&1
netsh advfirewall firewall add rule name=JournalLocalPhone dir=in action=allow protocol=TCP localport=8765 profile=any

for /f "delims=" %%i in ('python -c "import sys; print(sys.executable)"') do (
  netsh advfirewall firewall delete rule name=JournalPython >nul 2>&1
  netsh advfirewall firewall add rule name=JournalPython dir=in action=allow program="%%i" profile=any
)

powershell -NoProfile -Command "Get-NetConnectionProfile | Set-NetConnectionProfile -NetworkCategory Private"

for /f "delims=" %%i in ('python -c "import socket; s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(('8.8.8.8',80)); print(s.getsockname()[0]); s.close()"') do set LANIP=%%i

echo.
echo Готово. Сеть помечена как частная, порт открыт.
echo.
echo 1. Журнал должен быть запущен файлом запустить.bat
echo 2. Телефон в той же Wi-Fi, что компьютер, не в мобильном интернете
echo 3. На телефоне откройте Chrome и введите СТРОГО:
echo.
echo    http://%LANIP%:8765/
echo.
echo Не https, а http. Если Safari сам ставит замочек — возьмите Chrome.
echo.
pause
