@echo off
REM Pemeriksaan menyeluruh: konfigurasi, database, tabel, port, sertifikat. Hasil disimpan di logs\diagnose_*.txt
cd /d "%~dp0"
DHKRegister.exe --diagnose
echo.
if exist logs\STARTUP_ERROR.txt (
  echo ===== Kegagalan startup terakhir =====
  type logs\STARTUP_ERROR.txt
)
pause
