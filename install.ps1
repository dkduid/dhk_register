#Requires -Version 5.1
<#
.SYNOPSIS
  Instalasi lengkap Register DHK: PostgreSQL (bila belum ada) + database + tabel + aplikasi + auto-start.
  Jalankan lewat Install.bat (otomatis minta hak Administrator).

.PARAMETER PgInstaller   Path installer PostgreSQL (EDB) .exe. Default: cari installers\postgresql-*-windows-x64.exe
.PARAMETER PgUrl         URL unduhan installer bila berkas tidak ada (butuh internet)
.PARAMETER PgSuperPassword  Password superuser 'postgres'. Instalasi baru: dibuat acak bila kosong. PostgreSQL sudah ada: ditanyakan.
.PARAMETER SkipPostgres  Jangan pasang PostgreSQL (pakai server database yang sudah ada, termasuk server lain)
.PARAMETER DbHost/DbPort/DbName/DbUser  Target database aplikasi
.PARAMETER AppPort       Port HTTPS aplikasi (default 8443)
.PARAMETER Force         Timpa .env yang sudah ada (cadangan dibuat otomatis)
.PARAMETER NoPause       Jangan menunggu Enter di akhir (otomasi)
#>
[CmdletBinding()]
param(
    [string]$InstallDir = $PSScriptRoot,
    [string]$PgInstaller = "",
    [string]$PgUrl = "",
    [string]$PgSuperPassword = "",
    [switch]$SkipPostgres,
    [string]$DbHost = "localhost",
    [int]$DbPort = 5432,
    [string]$DbName = "dhk_register",
    [string]$DbUser = "dhk_user",
    [int]$AppPort = 8443,
    [switch]$Force,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
# Ubah bila versi PostgreSQL berbeda. Lebih baik: letakkan installer di folder installers\ (tanpa internet).
$DefaultPgUrl = "https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64.exe"
$PgServiceName = "postgresql-x64-16"
$TaskName = "DHK Register"

$LogDir = Join-Path $InstallDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$InstallLog = Join-Path $LogDir "install_$Stamp.log"
$InstallErr = Join-Path $LogDir "install_error.log"
try { Start-Transcript -Path $InstallLog | Out-Null } catch { }

function Step($m)  { Write-Host ""; Write-Host ">> $m" -ForegroundColor Cyan }
function Ok($m)    { Write-Host "   [OK] $m" -ForegroundColor Green }
function Warn($m)  { Write-Host "   [PERHATIAN] $m" -ForegroundColor Yellow }

function Fail([string]$Code, [string]$Message, [string]$Hint) {
    $txt = @(
        "INSTALASI GAGAL  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "Kode      : $Code",
        "Masalah   : $Message",
        "Perbaikan : $Hint",
        "Log       : $InstallLog",
        "Server    : $env:COMPUTERNAME"
    ) -join "`r`n"
    Set-Content -Path $InstallErr -Value $txt -Encoding UTF8
    Write-Host ""; Write-Host $txt -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    try { eventcreate /T ERROR /ID 902 /L APPLICATION /SO DHKRegister /D "[$Code] $Message" 2>&1 | Out-Null } catch { }
    if (-not $NoPause) { Read-Host "`nTekan Enter untuk menutup" | Out-Null }
    exit 1
}

function New-RandomString([int]$Length, [string]$Chars) {
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $b = New-Object byte[] 4
    $sb = New-Object System.Text.StringBuilder
    for ($i = 0; $i -lt $Length; $i++) {
        $rng.GetBytes($b)
        [void]$sb.Append($Chars[[int]([BitConverter]::ToUInt32($b, 0) % $Chars.Length)])
    }
    $sb.ToString()
}
$Alnum = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Program native menulis error ke stderr; di PS 5.1 dengan EAP=Stop itu bisa menghentikan skrip. Jalankan dengan EAP=Continue.
function Invoke-App([string[]]$AppArgs) {
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    Push-Location $InstallDir
    try { $o = & $Exe @AppArgs 2>&1 | Out-String; $script:AppExit = $LASTEXITCODE; return $o }
    finally { Pop-Location; $ErrorActionPreference = $prev }
}

function Wait-Port([string]$H, [int]$P, [int]$Seconds) {
    $end = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $end) {
        try { $c = New-Object Net.Sockets.TcpClient; $c.Connect($H, $P); $c.Close(); return $true } catch { Start-Sleep -Seconds 2 }
    }
    return $false
}

try {
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host " Instalasi Register DHK" -ForegroundColor Cyan
    Write-Host "=============================================" -ForegroundColor Cyan
    Write-Host "Folder aplikasi : $InstallDir"
    Write-Host "Log instalasi   : $InstallLog"

    # 1. Hak Administrator
    Step "1/8 Memeriksa hak Administrator"
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { Fail "I-01" "Skrip tidak dijalankan sebagai Administrator." "Klik kanan Install.bat > Run as administrator." }
    Ok "Administrator"

    $Exe = Join-Path $InstallDir "DHKRegister.exe"
    if (-not (Test-Path $Exe)) { Fail "I-07" "DHKRegister.exe tidak ditemukan di $InstallDir." "Jalankan install.ps1 dari dalam folder hasil build (dist\DHKRegister)." }

    # 2. PostgreSQL
    Step "2/8 PostgreSQL"
    $generatedSuper = $false
    $pgSvc = Get-Service | Where-Object { $_.Name -like "postgresql*" } | Select-Object -First 1
    if ($SkipPostgres) {
        Ok "Dilewati (-SkipPostgres): memakai server database $DbHost`:$DbPort"
        if (-not $PgSuperPassword) {
            $s = Read-Host "Password superuser PostgreSQL di $DbHost (kosongkan bila role+database sudah dibuat DBA)" -AsSecureString
            $PgSuperPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
        }
    }
    elseif ($pgSvc) {
        Ok "PostgreSQL sudah terpasang: service '$($pgSvc.Name)' ($($pgSvc.Status)). Tidak dipasang ulang."
        if ($pgSvc.Status -ne "Running") { Start-Service $pgSvc.Name; Start-Sleep -Seconds 5 }
        if (-not $PgSuperPassword) {
            $s = Read-Host "Masukkan password superuser 'postgres' (untuk membuat role dan database aplikasi)" -AsSecureString
            $PgSuperPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
        }
    }
    else {
        if (-not $PgInstaller) {
            $cand = Get-ChildItem -Path (Join-Path $InstallDir "installers") -Filter "postgresql-*-windows-x64.exe" -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
            if ($cand) { $PgInstaller = $cand.FullName }
        }
        if (-not $PgInstaller) {
            $url = if ($PgUrl) { $PgUrl } else { $DefaultPgUrl }
            Warn "Installer PostgreSQL tidak ada di folder installers\. Mencoba mengunduh: $url"
            New-Item -ItemType Directory -Force -Path (Join-Path $InstallDir "installers") | Out-Null
            $PgInstaller = Join-Path $InstallDir ("installers\" + [IO.Path]::GetFileName($url))
            try { Invoke-WebRequest -Uri $url -OutFile $PgInstaller -UseBasicParsing }
            catch { Fail "I-02" "Installer PostgreSQL tidak ditemukan dan gagal diunduh ($($_.Exception.Message))." "Unduh installer Windows x86-64 dari https://www.enterprisedb.com/downloads/postgres-postgresql-downloads, letakkan di folder installers\, lalu jalankan Install.bat lagi." }
            if ((Get-Item $PgInstaller).Length -lt 100MB) { Remove-Item $PgInstaller -Force; Fail "I-02" "Berkas hasil unduhan terlalu kecil (bukan installer yang valid)." "Unduh manual dari situs EDB dan letakkan di folder installers\." }
        }
        Ok "Installer: $PgInstaller"
        if (-not $PgSuperPassword) { $PgSuperPassword = New-RandomString 20 $Alnum; $generatedSuper = $true }
        $pgLog = Join-Path $LogDir "postgresql_install_$Stamp.log"
        Write-Host "   Memasang PostgreSQL (sekitar 3-10 menit, jendela installer tidak ditampilkan)..."
        $argString = "--mode unattended --unattendedmodeui none --superpassword `"$PgSuperPassword`" --serverport $DbPort --servicename $PgServiceName --enable-components server,commandlinetools --debuglevel 2 --debugtrace `"$pgLog`""
        $p = Start-Process -FilePath $PgInstaller -ArgumentList $argString -Wait -PassThru
        if ($p.ExitCode -ne 0) { Fail "I-03" "Installer PostgreSQL berakhir dengan kode $($p.ExitCode)." "Lihat $pgLog dan %TEMP%\install-postgresql.log. Pastikan tidak ada instalasi PostgreSQL setengah jadi, dan disk cukup (>1 GB)." }
        Ok "PostgreSQL terpasang"
        $pgSvc = Get-Service | Where-Object { $_.Name -like "postgresql*" } | Select-Object -First 1
    }

    if (-not $SkipPostgres -or $DbHost -in @("localhost", "127.0.0.1")) {
        Step "3/8 Menunggu PostgreSQL siap di $DbHost`:$DbPort"
        if (-not (Wait-Port $DbHost $DbPort 90)) { Fail "I-04" "PostgreSQL tidak merespons di $DbHost`:$DbPort." "Buka services.msc, pastikan service postgresql-x64-xx berstatus Running; periksa port pada pengaturan PostgreSQL." }
        Ok "Port $DbPort terbuka"
    }
    else { Step "3/8 Server database eksternal"; if (-not (Wait-Port $DbHost $DbPort 15)) { Fail "I-04" "Server database $DbHost`:$DbPort tidak terjangkau." "Periksa jaringan/firewall." }; Ok "Terjangkau" }

    # 4. Konfigurasi .env
    Step "4/8 Konfigurasi (.env)"
    $EnvFile = Join-Path $InstallDir ".env"
    $DbPassword = ""
    if ((Test-Path $EnvFile) -and -not $Force) {
        Ok ".env sudah ada, dipertahankan (pakai -Force untuk membuat ulang)"
    }
    else {
        if (Test-Path $EnvFile) { Copy-Item $EnvFile "$EnvFile.bak_$Stamp"; Warn "Cadangan .env lama: .env.bak_$Stamp" }
        $tpl = Join-Path $InstallDir ".env.example"
        if (-not (Test-Path $tpl)) { Fail "I-07" ".env.example tidak ditemukan." "Salin ulang paket instalasi lengkap." }
        $DbPassword = New-RandomString 24 $Alnum
        $secret = (New-RandomString 64 "0123456789abcdef")
        $lines = Get-Content $tpl | ForEach-Object {
            if     ($_ -match "^SECRET_KEY=")   { "SECRET_KEY=$secret" }
            elseif ($_ -match "^DATABASE_URL=") { "DATABASE_URL=postgresql+psycopg2://${DbUser}:${DbPassword}@${DbHost}:${DbPort}/${DbName}" }
            elseif ($_ -match "^PORT=")         { "PORT=$AppPort" }
            else { $_ }
        }
        Set-Content -Path $EnvFile -Value $lines -Encoding UTF8
        & icacls $EnvFile /inheritance:r /grant:r "SYSTEM:(F)" "BUILTIN\Administrators:(F)" | Out-Null
        Ok ".env dibuat (SECRET_KEY acak, password database acak, akses dibatasi Administrator/SYSTEM)"
    }

    # 5. Database + tabel
    Step "5/8 Membuat role, database, tabel, dan data awal"
    $AdminPw = ((New-RandomString 4 "ABCDEFGHJKLMNPQRSTUVWXYZ") + (New-RandomString 6 "abcdefghijkmnpqrstuvwxyz") + (New-RandomString 4 "23456789") + (New-RandomString 2 "#@!%"))
    $env:PG_ADMIN_PASSWORD = $PgSuperPassword
    $env:ADMIN_PASSWORD = $AdminPw
    try { $out = Invoke-App @("--init-db"); $ec = $script:AppExit } finally { Remove-Item Env:PG_ADMIN_PASSWORD -ErrorAction SilentlyContinue; Remove-Item Env:ADMIN_PASSWORD -ErrorAction SilentlyContinue }
    $safe = ($out -split "`r?`n" | ForEach-Object { if ($_ -match "^\s*password:") { "  password: (disembunyikan)" } else { $_ } }) -join "`r`n"
    Write-Host $safe
    if ($ec -ne 0) {
        $se = Join-Path $LogDir "STARTUP_ERROR.txt"
        $detail = if (Test-Path $se) { (Get-Content $se -Raw) } else { "" }
        Fail "I-05" "Penyiapan database gagal (kode keluar $ec). $detail" "Lihat logs\STARTUP_ERROR.txt dan logs\error.log; jalankan Diagnose.bat. Kode E-DB-xx dijelaskan di Panduan Instalasi."
    }
    $adminCreated = $out -match "Admin awal dibuat"
    Ok "Database siap: $DbName (role $DbUser), tabel dan data awal terpasang"

    # 6. Firewall + auto-start
    Step "6/8 Firewall dan auto-start"
    $rule = "DHK Register (TCP $AppPort)"
    if (-not (Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $rule -Direction Inbound -Protocol TCP -LocalPort $AppPort -Action Allow -Profile Domain,Private | Out-Null
        Ok "Aturan firewall dibuat (profil Domain/Private). Port database ($DbPort) TIDAK dibuka ke jaringan."
    } else { Ok "Aturan firewall sudah ada" }
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    $action    = New-ScheduledTaskAction -Execute $Exe -WorkingDirectory $InstallDir
    $trigger   = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
    $settings  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    Ok "Scheduled Task '$TaskName' dibuat (otomatis berjalan saat server menyala, restart otomatis bila gagal)"

    # 7. Jalankan + cek kesehatan
    Step "7/8 Menjalankan aplikasi dan memeriksa kesehatan"
    Start-ScheduledTask -TaskName $TaskName
    $healthy = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 3
        [void](Invoke-App @("--healthcheck"))
        if ($script:AppExit -eq 0) { $healthy = $true; break }
    }
    if (-not $healthy) {
        $se = Join-Path $LogDir "STARTUP_ERROR.txt"
        $detail = if (Test-Path $se) { (Get-Content $se -Raw) } else { "Tidak ada STARTUP_ERROR.txt; periksa logs\error.log." }
        Fail "I-06" "Aplikasi tidak sehat setelah 60 detik. $detail" "Jalankan Diagnose.bat, lalu lihat logs\error.log. Uji manual: Start_Aplikasi.bat (menampilkan error di layar)."
    }
    Ok "Aplikasi berjalan dan sehat (/health = OK)"

    # 8. Diagnose
    Step "8/8 Pemeriksaan akhir"
    Write-Host (Invoke-App @("--diagnose"))

    try { Stop-Transcript | Out-Null } catch { }
    $hostName = [System.Net.Dns]::GetHostName()
    Write-Host ""
    Write-Host "=====================  INSTALASI SELESAI  =====================" -ForegroundColor Green
    Write-Host " Alamat aplikasi   : https://${hostName}:$AppPort   (atau https://localhost:$AppPort di server ini)"
    Write-Host "                     Peringatan sertifikat muncul bila memakai sertifikat self-signed; lihat Dokumentasi Konfigurasi."
    if ($adminCreated) {
        Write-Host " Login admin awal  : admin"
        Write-Host " Password awal     : $AdminPw      (WAJIB diganti saat login pertama)" -ForegroundColor Yellow
    } else { Write-Host " Akun admin        : sudah ada sebelumnya (tidak diubah)" }
    if ($generatedSuper) { Write-Host " Superuser Postgres: postgres / $PgSuperPassword" -ForegroundColor Yellow }
    Write-Host " Database          : $DbName di ${DbHost}:$DbPort (role $DbUser; password ada di .env)"
    Write-Host " CATAT kredensial di atas pada password vault. Tidak disimpan di file mana pun." -ForegroundColor Yellow
    Write-Host " Log               : $LogDir  (error.log, app.log, STARTUP_ERROR.txt, install_*.log)"
    Write-Host " Bila ada masalah  : jalankan Diagnose.bat"
    Write-Host "================================================================" -ForegroundColor Green
    if (-not $NoPause) { Read-Host "`nTekan Enter setelah kredensial dicatat" | Out-Null }
    exit 0
}
catch {
    $m = $_.Exception.Message
    Set-Content -Path $InstallErr -Value ("INSTALASI GAGAL (tak terduga) $(Get-Date)`r`nKode: I-99`r`n$m`r`n$($_.ScriptStackTrace)") -Encoding UTF8
    Write-Host "`nINSTALASI GAGAL (I-99): $m" -ForegroundColor Red
    Write-Host "Rincian: $InstallErr dan $InstallLog" -ForegroundColor Red
    try { Stop-Transcript | Out-Null } catch { }
    if (-not $NoPause) { Read-Host "`nTekan Enter untuk menutup" | Out-Null }
    exit 1
}
