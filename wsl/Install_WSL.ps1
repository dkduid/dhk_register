<#
.SYNOPSIS  Register DHK - pasang di WSL2 (Ubuntu) dari Windows. Jalankan sebagai Administrator (lewat Install_WSL.bat).
.PARAMETER Distro  Nama distro WSL (default Ubuntu-24.04)
.PARAMETER Lan     Izinkan akses dari komputer lain di jaringan (mirrored networking di Windows 11 22H2+, atau portproxy)
.PARAMETER Port    Port HTTPS aplikasi (default 8443)
#>
param([string]$Distro = "Ubuntu-24.04", [switch]$Lan, [int]$Port = 8443)
$ErrorActionPreference = "Stop"
$Src = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $PSScriptRoot "logs"; New-Item -ItemType Directory -Force $LogDir | Out-Null
$Log = Join-Path $LogDir ("install_wsl_{0:yyyyMMdd_HHmmss}.log" -f (Get-Date))
Start-Transcript -Path $Log | Out-Null
function Step($t) { Write-Host "`n== $t ==" -ForegroundColor Cyan }
function Ok($t)   { Write-Host "  [OK]   $t" -ForegroundColor Green }
function Warn($t) { Write-Host "  [WARN] $t" -ForegroundColor Yellow }
function Fail($code, $msg, $fix) { Write-Host "`n  [GAGAL] [$code] $msg" -ForegroundColor Red; Write-Host "          Perbaikan: $fix"; Write-Host "          Log: $Log"; Stop-Transcript | Out-Null; Read-Host "`nTekan Enter untuk menutup" | Out-Null; exit 1 }
function Wsl-Distros { (& wsl.exe -l -q 2>$null) -replace "`0", "" | ForEach-Object { $_.Trim() } | Where-Object { $_ } }

try {
  Step "1/6 Pemeriksaan"
  if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail "WI-01" "Harus dijalankan sebagai Administrator." "Klik kanan Install_WSL.bat > Run as administrator." }
  if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { Fail "WI-02" "wsl.exe tidak ada (Windows terlalu lama)." "Gunakan Windows 10 22H2 / Windows 11 dan aktifkan fitur WSL." }
  if (-not (Test-Path (Join-Path $Src "run.py"))) { Fail "WI-03" "run.py tidak ditemukan di $Src." "Jalankan dari folder wsl di dalam paket sumber lengkap (bukan dist\DHKRegister)." }
  Ok "Administrator, WSL tersedia, sumber: $Src"

  Step "2/6 Distro WSL2 ($Distro)"
  if (-not (Wsl-Distros | Where-Object { $_ -eq $Distro })) {
    Write-Host "  Memasang $Distro (butuh internet; bisa perlu restart Windows)..."
    & wsl.exe --install -d $Distro --no-launch
    if ($LASTEXITCODE -ne 0) { Fail "WI-04" "wsl --install gagal (kode $LASTEXITCODE)." "Aktifkan Virtualization di BIOS, jalankan 'wsl --update', restart Windows, lalu ulangi." }
    $exe = ($Distro -replace "[-.]", "").ToLower() + ".exe"          # Ubuntu-24.04 -> ubuntu2404.exe
    $cmd = Get-Command $exe -ErrorAction SilentlyContinue
    if ($cmd) { & $cmd.Source install --root }                       # tanpa prompt user; kita pakai root
    if (-not (Wsl-Distros | Where-Object { $_ -eq $Distro })) { Fail "WI-05" "Distro $Distro belum terdaftar (kemungkinan perlu restart)." "Restart Windows, lalu jalankan Install_WSL.bat lagi." }
  }
  & wsl.exe --set-version $Distro 2 2>$null | Out-Null
  Ok "$Distro siap (WSL2)"

  Step "3/6 Aktifkan systemd"
  $has = (& wsl.exe -d $Distro -u root -- bash -c "grep -qs '^systemd *= *true' /etc/wsl.conf && echo yes || echo no").Trim()
  if ($has -ne "yes") {
    & wsl.exe -d $Distro -u root -- bash -c "printf '[boot]\nsystemd=true\n' >> /etc/wsl.conf"
    & wsl.exe --terminate $Distro; Start-Sleep 3
    Ok "systemd diaktifkan di /etc/wsl.conf, distro dijalankan ulang"
  } else { Ok "systemd sudah aktif" }

  if ($Lan -and [Environment]::OSVersion.Version.Build -ge 22621) {
    $cfg = Join-Path $env:USERPROFILE ".wslconfig"
    if (-not (Test-Path $cfg) -or -not (Select-String -Path $cfg -Pattern "networkingMode" -Quiet)) {
      Add-Content $cfg "`n[wsl2]`nnetworkingMode=mirrored"; & wsl.exe --shutdown; Start-Sleep 3
      Ok "mirrored networking diaktifkan di $cfg"
    }
  }

  Step "4/6 Instalasi aplikasi di dalam WSL"
  $wslSrc = (& wsl.exe -d $Distro -u root -- wslpath -a ($Src -replace "\\", "/")).Trim()
  Write-Host "  Sumber (WSL): $wslSrc"
  & wsl.exe -d $Distro -u root -- bash "$wslSrc/wsl/install_wsl.sh" "$wslSrc" 2>&1 | Tee-Object -Variable out | Write-Host
  if ($LASTEXITCODE -ne 0) { Fail "WI-06" "install_wsl.sh gagal (kode $LASTEXITCODE)." "Lihat kode [W-xx] di atas dan /var/log/dhk_install_wsl.log di dalam WSL." }

  Step "5/6 Jaga WSL tetap hidup & jalan saat boot"
  $act = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d $Distro -u root -- sleep infinity"
  $trg = New-ScheduledTaskTrigger -AtStartup
  $pri = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest
  $set = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
  Register-ScheduledTask -TaskName "DHK Register WSL" -Action $act -Trigger $trg -Principal $pri -Settings $set -Force | Out-Null
  Start-ScheduledTask -TaskName "DHK Register WSL"
  Ok "Scheduled Task 'DHK Register WSL' terdaftar (distro tetap hidup sehingga service ikut berjalan)"

  Step "6/6 Firewall / akses LAN"
  if ($Lan) {
    New-NetFirewallRule -DisplayName "DHK Register (HTTPS $Port)" -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Domain,Private -ErrorAction SilentlyContinue | Out-Null
    if ([Environment]::OSVersion.Version.Build -lt 22621) {
      $ip = (& wsl.exe -d $Distro -u root -- hostname -I).Trim().Split(" ")[0]
      & netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=0.0.0.0 2>$null | Out-Null
      & netsh interface portproxy add v4tov4 listenport=$Port listenaddress=0.0.0.0 connectport=$Port connectaddress=$ip | Out-Null
      Warn "Windows < 11 22H2: portproxy ke $ip. IP WSL bisa berubah setelah restart; jalankan ulang Install_WSL.bat -Lan bila LAN tidak tembus."
    }
    Ok "Aturan firewall dibuat; akses dari LAN: https://<IP-Windows>:$Port"
  } else { Ok "Akses hanya dari komputer ini (https://localhost:$Port). Gunakan -Lan untuk membuka ke jaringan." }

  Write-Host "`nSELESAI. Buka https://localhost:$Port  (catat password admin yang tampil di langkah 4)." -ForegroundColor Green
  Stop-Transcript | Out-Null
  Read-Host "`nTekan Enter setelah password admin dicatat" | Out-Null
} catch {
  Fail "WI-99" $_.Exception.Message "Kirim berkas log ini untuk analisis."
}
