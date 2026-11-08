@echo off
REM Cek status Register DHK di WSL2 (service, kesehatan aplikasi, 20 baris log terakhir).
set D=Ubuntu-24.04
wsl -d %D% -u root -- bash -c "systemctl is-active dhk-register; curl -ks https://localhost:8443/health; echo; tail -n 20 /opt/dhk_register/logs/error.log 2>/dev/null"
echo.
echo Diagnosa penuh: wsl -d %D% -u dhk -- /opt/dhk_register/venv/bin/python /opt/dhk_register/run.py --diagnose
echo Reset admin   : wsl -d %D% -u dhk -- /opt/dhk_register/venv/bin/python /opt/dhk_register/run.py --reset-admin
pause
