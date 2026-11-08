@echo off
REM Pasang Register DHK di WSL2. Klik kanan > Run as administrator.
REM Tambahkan -Lan untuk membuka akses dari komputer lain:  Install_WSL.bat -Lan
net session >nul 2>&1
if %errorlevel% neq 0 ( echo Jalankan sebagai Administrator ^(klik kanan ^> Run as administrator^). & pause & exit /b 1 )
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install_WSL.ps1" %*
