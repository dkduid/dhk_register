@echo off
REM ============================================================================
REM  Build paket instalasi Register DHK (jalankan di Windows, Python 3.10+ terpasang)
REM  Hasil : dist\DHKRegister\  (DHKRegister.exe + Install.bat + installer PostgreSQL + dokumen)
REM          DHKRegister_Paket.zip   (siap disalin ke server tujuan)
REM          DHKRegister_Setup_v1.1.exe (bila Inno Setup / iscc.exe terpasang)
REM ============================================================================
setlocal
cd /d "%~dp0"

REM --- Installer PostgreSQL yang disertakan. Letakkan sendiri di installers\ (disarankan, tanpa internet) ---
REM --- atau ubah PG_URL ke tautan Windows x86-64 versi 16 dari https://www.enterprisedb.com/downloads/postgres-postgresql-downloads ---
set "PG_URL=https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64.exe"

where python >nul 2>&1 || (echo [GAGAL] Python tidak ditemukan di PATH. & goto :err)
if not exist .venv\Scripts\activate.bat ( python -m venv .venv || goto :err )
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip || goto :err
pip install -r requirements.txt || goto :err

echo.
echo [1/5] Menguji aplikasi (smoke test, SQLite sementara)...
python tests\smoke_test.py || (echo [GAGAL] Uji otomatis gagal; build dibatalkan. & goto :err)

echo.
echo [2/5] Membangun DHKRegister.exe...
pyinstaller dhk_register.spec --noconfirm --clean || goto :err
set "OUT=dist\DHKRegister"

echo.
echo [3/5] Menyiapkan installer PostgreSQL...
if not exist installers mkdir installers
dir /b installers\postgresql-*-windows-x64.exe >nul 2>&1
if errorlevel 1 (
  for %%F in ("%PG_URL%") do set "PG_FILE=%%~nxF"
  echo Mengunduh dari %PG_URL% ...
  powershell -NoProfile -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; try { Invoke-WebRequest -Uri '%PG_URL%' -OutFile 'installers\%PG_FILE%' -UseBasicParsing } catch { exit 1 }"
  if errorlevel 1 (
    echo [PERHATIAN] Unduhan gagal. Unduh installer PostgreSQL 16 Windows x86-64 secara manual, letakkan di folder installers\, lalu jalankan build_exe.bat lagi.
    echo             Build dilanjutkan TANPA installer PostgreSQL ^(Install.bat akan mencoba mengunduh saat dipasang, atau gunakan PostgreSQL yang sudah ada^).
  )
)

echo.
echo [4/5] Menyalin berkas pendukung...
copy /Y .env.example "%OUT%\.env.example" >nul
copy /Y Install.bat "%OUT%\" >nul
copy /Y install.ps1 "%OUT%\" >nul
copy /Y uninstall.ps1 "%OUT%\" >nul
copy /Y Diagnose.bat "%OUT%\" >nul
copy /Y Start_Aplikasi.bat "%OUT%\" >nul
copy /Y README.md "%OUT%\" >nul
if not exist "%OUT%\db" mkdir "%OUT%\db"
copy /Y db\schema.sql "%OUT%\db\" >nul
if exist docs xcopy /E /I /Y docs "%OUT%\docs" >nul
if exist installers xcopy /E /I /Y installers "%OUT%\installers" >nul

echo.
echo [5/5] Mengemas...
powershell -NoProfile -Command "Compress-Archive -Path '%OUT%\*' -DestinationPath 'DHKRegister_Paket.zip' -Force"
where iscc >nul 2>&1 && ( iscc installer.iss ) || echo (Inno Setup tidak ditemukan; DHKRegister_Setup.exe dilewati. Paket zip sudah cukup.)

echo.
echo ============================================================
echo  BUILD SELESAI
echo  Salin DHKRegister_Paket.zip ke server tujuan, ekstrak, lalu klik kanan Install.bat ^> Run as administrator.
echo  Panduan lengkap: docs\05_Panduan_Instalasi.docx
echo ============================================================
exit /b 0
:err
echo.
echo BUILD GAGAL. Lihat pesan di atas.
exit /b 1
