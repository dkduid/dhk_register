#!/usr/bin/env bash
# Register DHK - instalasi di dalam WSL2 (Ubuntu 22.04/24.04). Jalankan sebagai root:
#   sudo bash install_wsl.sh [FOLDER_SUMBER]      (default: folder induk skrip ini)
# Idempoten: aman dijalankan ulang. .env yang sudah ada dipertahankan.
set -euo pipefail

SRC="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
APP_DIR="${APP_DIR:-/opt/dhk_register}"
APP_USER="dhk"
DB_NAME="dhk_register"; DB_USER="dhk_user"
PORT="${PORT:-8443}"
LOG="/var/log/dhk_install_wsl.log"
SKIP_SYSTEMD="${SKIP_SYSTEMD:-0}"      # 1 = lewati service systemd (uji/CI)

step(){ echo; echo "== $* =="; }
ok(){ echo "  [OK]   $*"; }
warn(){ echo "  [WARN] $*"; }
fail(){ echo; echo "  [GAGAL] [$1] $2"; echo "          Perbaikan: $3"; echo "          Log: $LOG"; exit 1; }
rand(){ python3 - "$1" <<'PY'
import secrets, string, sys
n = int(sys.argv[1]); a = string.ascii_letters + string.digits
print("".join(secrets.choice(a) for _ in range(n)))
PY
}

[ "$(id -u)" -eq 0 ] || fail W-01 "Harus dijalankan sebagai root." "Gunakan: sudo bash install_wsl.sh"
[ -f "$SRC/run.py" ] || fail W-02 "run.py tidak ditemukan di $SRC." "Berikan folder sumber aplikasi sebagai argumen."
exec > >(tee -a "$LOG") 2>&1
echo "Instalasi Register DHK di WSL2  $(date '+%F %T')  sumber=$SRC  tujuan=$APP_DIR"

step "1/7 Paket sistem"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq || fail W-03 "apt-get update gagal (jaringan/proxy)." "Periksa koneksi internet atau proxy di dalam WSL."
apt-get install -y -qq postgresql postgresql-client python3 python3-venv python3-pip rsync curl openssl libpq5 >/dev/null \
  || fail W-03 "Pemasangan paket gagal." "Periksa log di atas; jalankan ulang."
ok "postgresql, python3, venv terpasang ($(python3 --version))"

step "2/7 PostgreSQL"
if ! pg_lsclusters 2>/dev/null | grep -q online; then
  if [ "$SKIP_SYSTEMD" = "1" ] || ! pidof systemd >/dev/null 2>&1; then
    pg_ctlcluster "$(pg_lsclusters -h | awk 'NR==1{print $1}')" main start 2>/dev/null || service postgresql start || true
  else
    systemctl enable --now postgresql || true
  fi
  sleep 3
fi
pg_lsclusters | grep -q online || fail W-04 "Cluster PostgreSQL tidak berjalan." "Jalankan: pg_lsclusters ; sudo service postgresql start"
ok "PostgreSQL berjalan ($(pg_lsclusters -h | awk 'NR==1{print $1" "$3}'))"

step "3/7 Berkas aplikasi"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
mkdir -p "$APP_DIR"
rsync -a --delete --exclude '.git' --exclude '.env' --exclude 'logs' --exclude 'certs' --exclude 'uploads' \
      --exclude '__pycache__' --exclude 'venv' --exclude '.venv' --exclude 'dist' --exclude 'build' --exclude '*.db' \
      "$SRC"/ "$APP_DIR"/
mkdir -p "$APP_DIR"/{logs,certs,uploads}
ok "disalin ke $APP_DIR"

step "4/7 Python virtualenv"
[ -x "$APP_DIR/venv/bin/python" ] || python3 -m venv "$APP_DIR/venv"
grep -vi '^pyinstaller' "$APP_DIR/requirements.txt" > /tmp/dhk_req.txt
"$APP_DIR/venv/bin/pip" install -q --upgrade pip >/dev/null
"$APP_DIR/venv/bin/pip" install -q -r /tmp/dhk_req.txt || fail W-05 "pip install gagal." "Periksa akses ke pypi.org dari dalam WSL."
ok "dependensi terpasang"

step "5/7 Database dan konfigurasi (.env)"
ENVF="$APP_DIR/.env"
NEW_ENV=0
if [ -f "$ENVF" ]; then
  ok ".env sudah ada, dipertahankan"
else
  NEW_ENV=1
  DBPW="$(rand 24)"; SK="$(rand 48)"
  cat > "$ENVF" <<ENV
SECRET_KEY=$SK
DATABASE_URL=postgresql+psycopg2://$DB_USER:$DBPW@localhost:5432/$DB_NAME
AUTO_CREATE_DB=false
HOST=0.0.0.0
PORT=$PORT
HTTPS=true
SESSION_MINUTES=30
MAX_UPLOAD_MB=25
ADMIN_USERNAME=admin
LDAP_ENABLED=false
CLAMAV_ENABLED=false
BLOCK_ON_ATTACK=true
MAX_FAILED_LOGIN=5
LOCK_MINUTES=15
ENV
  chmod 600 "$ENVF"
  # role + database (password disinkronkan dengan .env)
  sudo -u postgres psql -v ON_ERROR_STOP=1 -q <<SQL || fail W-06 "Pembuatan role/database gagal." "Lihat log; cek: sudo -u postgres psql -l"
DO \$\$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname='$DB_USER') THEN ALTER ROLE $DB_USER WITH LOGIN PASSWORD '$DBPW';
  ELSE CREATE ROLE $DB_USER WITH LOGIN PASSWORD '$DBPW'; END IF; END \$\$;
SQL
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 \
    || sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"
  ok ".env dibuat (SECRET_KEY dan password database acak, mode 600), role dan database siap"
fi
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chmod 600 "$ENVF"

step "6/7 Inisialisasi tabel dan akun admin"
ADMIN_PW="Aa1!$(rand 14)"
INIT_OUT="$(cd "$APP_DIR" && ADMIN_PASSWORD="$ADMIN_PW" sudo -u "$APP_USER" -E "$APP_DIR/venv/bin/python" run.py --init-db 2>&1)" \
  || { echo "$INIT_OUT"; fail W-07 "run.py --init-db gagal." "Lihat pesan di atas dan $APP_DIR/logs/error.log; jalankan: $APP_DIR/venv/bin/python run.py --diagnose"; }
echo "$INIT_OUT" | tail -5
ok "tabel siap"

step "7/7 Service"
if [ "$SKIP_SYSTEMD" = "1" ]; then
  warn "systemd dilewati (SKIP_SYSTEMD=1). Jalankan manual: cd $APP_DIR && venv/bin/python run.py"
elif ! pidof systemd >/dev/null 2>&1; then
  fail W-08 "systemd belum aktif di distro ini." "Tambahkan ke /etc/wsl.conf:  [boot]  systemd=true  lalu di Windows: wsl --shutdown, dan jalankan ulang skrip ini."
else
  cat > /etc/systemd/system/dhk-register.service <<UNIT
[Unit]
Description=Register DHK
After=network.target postgresql.service
Wants=postgresql.service

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python run.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now dhk-register
  for i in $(seq 1 30); do
    curl -ksf "https://localhost:$PORT/health" >/dev/null 2>&1 && break; sleep 1
  done
  curl -ksf "https://localhost:$PORT/health" >/dev/null 2>&1 \
    && ok "aplikasi sehat di https://localhost:$PORT" \
    || fail W-09 "Aplikasi tidak menjawab /health." "journalctl -u dhk-register -n 50 ; cat $APP_DIR/logs/STARTUP_ERROR.txt"
fi

echo
echo "=============================================================="
echo " INSTALASI SELESAI"
echo " URL      : https://localhost:$PORT   (sertifikat self-signed: terima peringatan browser)"
if [ "$NEW_ENV" = "1" ]; then
echo " Username : admin"
echo " Password : $ADMIN_PW        <-- CATAT SEKARANG, tidak ditampilkan lagi"
echo "            (wajib diganti saat login pertama)"
else
echo " .env lama dipertahankan. Bila lupa password admin:"
echo "   sudo -u $APP_USER $APP_DIR/venv/bin/python $APP_DIR/run.py --reset-admin"
fi
echo " Log      : $APP_DIR/logs   |   Service: systemctl status dhk-register"
echo "=============================================================="
