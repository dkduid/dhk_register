#Requires -Version 5.1
<# Hapus auto-start dan aturan firewall. Data TIDAK dihapus kecuali diminta.
   -RemoveDatabase  : hapus database aplikasi (BUTUH password superuser; tidak dapat dibatalkan, backup dulu!)
   -RemovePostgres  : jalankan uninstaller PostgreSQL (hanya bila PostgreSQL dipasang oleh Install.bat dan tidak dipakai aplikasi lain) #>
[CmdletBinding()]
param([switch]$RemoveDatabase, [switch]$RemovePostgres, [string]$DbName = "dhk_register", [string]$DbUser = "dhk_user", [int]$DbPort = 5432)
$ErrorActionPreference = "Continue"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Write-Host "Jalankan sebagai Administrator." -ForegroundColor Red; exit 1 }
Stop-ScheduledTask -TaskName "DHK Register" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "DHK Register" -Confirm:$false -ErrorAction SilentlyContinue
Get-NetFirewallRule -DisplayName "DHK Register*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
Write-Host "Auto-start dan aturan firewall dihapus. Folder aplikasi dan database tetap ada."
if ($RemoveDatabase) {
    if ((Read-Host "Ketik HAPUS untuk menghapus database $DbName secara permanen") -ceq "HAPUS") {
        $psql = Get-ChildItem "C:\Program Files\PostgreSQL\*\bin\psql.exe" -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | Select-Object -First 1
        if (-not $psql) { Write-Host "psql tidak ditemukan; hapus manual lewat pgAdmin/psql." -ForegroundColor Yellow }
        else {
            $s = Read-Host "Password superuser postgres" -AsSecureString
            $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
            & $psql.FullName -h localhost -p $DbPort -U postgres -c "DROP DATABASE IF EXISTS $DbName" -c "DROP ROLE IF EXISTS $DbUser"
            Remove-Item Env:PGPASSWORD
        }
    } else { Write-Host "Dibatalkan." }
}
if ($RemovePostgres) {
    $un = Get-ChildItem "C:\Program Files\PostgreSQL\*\uninstall-postgresql.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($un -and (Read-Host "Ketik HAPUS untuk menghapus PostgreSQL beserta SEMUA database di dalamnya") -ceq "HAPUS") { Start-Process $un.FullName -ArgumentList "--mode unattended" -Wait }
}
