@echo off
REM Instalasi lengkap (PostgreSQL + database + aplikasi + auto-start). Klik ganda; akan meminta hak Administrator.
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Meminta hak Administrator...
  powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0' -ArgumentList '%*'"
  exit /b
)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -InstallDir "%~dp0." %*
exit /b %errorlevel%
