@echo off
REM Jalankan aplikasi manual di jendela ini (pesan error tampil langsung). Tutup jendela atau Ctrl+C untuk berhenti.
REM Hentikan dulu Scheduled Task bila sudah terpasang:  schtasks /End /TN "DHK Register"
cd /d "%~dp0"
DHKRegister.exe
echo.
echo Aplikasi berhenti. Kode keluar: %errorlevel%  (2 = gagal startup, lihat logs\STARTUP_ERROR.txt)
pause
