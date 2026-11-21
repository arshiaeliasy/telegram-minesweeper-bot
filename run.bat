@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
python bot.py %*
if errorlevel 1 (
  echo.
  echo [!] ربات با خطا بسته شد.
  pause
)
endlocal
