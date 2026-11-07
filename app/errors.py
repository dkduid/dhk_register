"""Kode error, klasifikasi kegagalan, dan pencatatan log startup/runtime.

Semua kegagalan yang membuat aplikasi tidak dapat berjalan (konfigurasi, database, port, sertifikat)
dicatat ke:  logs/error.log (riwayat), logs/STARTUP_ERROR.txt (kegagalan terakhir, mudah dibaca),
Windows Event Viewer (Application, sumber "DHKRegister") bila tersedia, dan ditampilkan di console.
"""
import logging
import os
import platform
import socket
import subprocess
import sys
import threading
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

# kode -> (judul, langkah perbaikan). Dipakai juga oleh dokumentasi (tabel troubleshooting).
CODES = {
    "E-CFG-01": ("Berkas konfigurasi .env tidak ditemukan",
                 "Salin .env.example menjadi .env di folder aplikasi, lalu isi DATABASE_URL dan SECRET_KEY. "
                 "Atau jalankan ulang Install.bat agar .env dibuat otomatis."),
    "E-CFG-02": ("Nilai konfigurasi tidak valid atau masih default",
                 "Periksa .env: SECRET_KEY wajib diganti (jangan nilai bawaan), PORT harus angka 1-65535."),
    "E-DB-01": ("PostgreSQL tidak dapat dihubungi (service mati / port tertutup)",
                "Pastikan service PostgreSQL berjalan (services.msc > postgresql-x64-xx > Start), host dan port pada "
                "DATABASE_URL benar, dan firewall tidak memblokir port 5432."),
    "E-DB-02": ("Login database ditolak (username atau password salah)",
                "Samakan user/password pada DATABASE_URL dengan role di PostgreSQL. Bila perlu jalankan "
                "DHKRegister.exe --init-db dengan PG_ADMIN_PASSWORD untuk membuat ulang role aplikasi."),
    "E-DB-03": ("Database belum dibuat",
                "Jalankan DHKRegister.exe --init-db dengan PG_ADMIN_PASSWORD (superuser PostgreSQL) agar database "
                "dibuat otomatis, atau buat manual: CREATE DATABASE dhk_register."),
    "E-DB-05": ("Koneksi database kedaluwarsa (timeout)",
                "Server database tidak merespons. Periksa jaringan/VPN, alamat host, dan beban server database."),
    "E-DB-06": ("Nama host database tidak dikenali",
                "Periksa host pada DATABASE_URL (ejaan, DNS) atau gunakan alamat IP."),
    "E-DB-07": ("PostgreSQL menolak koneksi (pg_hba.conf)",
                "Tambahkan aturan pada pg_hba.conf untuk alamat server aplikasi, lalu reload PostgreSQL."),
    "E-DB-08": ("Pesan error database tidak dapat didekode (locale Windows)",
                "Terjadi pada PostgreSQL berlocale non-Inggris. Atur lc_messages = 'English_United States.1252' "
                "pada postgresql.conf, restart service, lalu jalankan ulang."),
    "E-DB-09": ("Tabel database belum lengkap",
                "Jalankan DHKRegister.exe --init-db untuk membuat tabel yang hilang. Detail tabel ada di log."),
    "E-DB-10": ("User database tidak memiliki hak akses yang cukup",
                "Berikan hak pada user aplikasi (pemilik database) atau jalankan --init-db dengan PG_ADMIN_PASSWORD."),
    "E-DB-99": ("Kesalahan database lain",
                "Lihat detail pada logs/error.log dan log server PostgreSQL (folder data\\log)."),
    "E-NET-01": ("Port aplikasi sudah dipakai proses lain",
                 "Ganti PORT di .env atau hentikan proses yang memakai port tersebut "
                 "(netstat -ano | findstr :8443)."),
    "E-TLS-01": ("Sertifikat HTTPS tidak dapat dimuat/dibuat",
                 "Periksa SSL_CERT dan SSL_KEY (path dan format PEM), atau kosongkan keduanya agar dibuat "
                 "self-signed, atau set HTTPS=false untuk uji lokal."),
    "E-LDAP-01": ("Server LDAP tidak dapat dihubungi",
                  "Periksa LDAP_SERVER, LDAP_PORT, firewall, dan LDAP_SSL. Login akun lokal tetap berfungsi."),
    "E-APP-01": ("Kesalahan tak terduga pada aplikasi",
                 "Kirimkan logs/error.log dan logs/STARTUP_ERROR.txt ke tim pengembang."),
}


class StartupError(Exception):
    def __init__(self, code, detail="", exc=None):
        super().__init__(f"[{code}] {detail}")
        self.code, self.detail, self.exc = code, str(detail), exc


LOGDIR = Path("logs")
_MARK = "_dhk_handler"


def init_logging(logdir):
    """Idempotent. app.log (INFO+), error.log (ERROR+), audit_fallback.log (bila DB audit gagal)."""
    global LOGDIR
    LOGDIR = Path(logdir)
    LOGDIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if any(getattr(h, _MARK, False) for h in root.handlers):
        return
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    for name, level in (("app.log", logging.INFO), ("error.log", logging.ERROR)):
        h = RotatingFileHandler(LOGDIR / name, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        h.setLevel(level)
        h.setFormatter(fmt)
        setattr(h, _MARK, True)
        root.addHandler(h)
    fb = logging.getLogger("dhk.audit_fallback")
    fb.propagate = False
    h = RotatingFileHandler(LOGDIR / "audit_fallback.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    fb.addHandler(h)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def install_hooks():
    """Exception yang lolos tetap tercatat di error.log."""
    def _hook(t, v, tb):
        if not issubclass(t, KeyboardInterrupt):
            logging.getLogger("dhk").critical("Exception tidak tertangani", exc_info=(t, v, tb))
        sys.__excepthook__(t, v, tb)
    sys.excepthook = _hook
    threading.excepthook = lambda a: logging.getLogger("dhk").critical(
        "Exception pada thread %s", getattr(a.thread, "name", "?"), exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def mask_url(uri):
    try:
        from sqlalchemy.engine import make_url
        return make_url(uri).render_as_string(hide_password=True)
    except Exception:
        return "(tidak dapat dibaca)"


def port_open(host, port, timeout=3):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def _msg(exc):
    o = getattr(exc, "orig", None) or exc
    try:
        return str(o)
    except Exception:
        return repr(o)


def classify(exc, host=None, port=None):
    """Petakan exception database/jaringan ke kode error."""
    if isinstance(exc, StartupError):
        return exc.code
    o = getattr(exc, "orig", None)
    if isinstance(exc, UnicodeDecodeError) or isinstance(o, UnicodeDecodeError):
        return "E-DB-08"
    m = _msg(exc).lower()
    if "password authentication failed" in m or "authentication failed" in m or ('role "' in m and "does not exist" in m):
        return "E-DB-02"
    if "no pg_hba.conf entry" in m:
        return "E-DB-07"
    if 'database "' in m and "does not exist" in m:
        return "E-DB-03"
    if "permission denied" in m:
        return "E-DB-10"
    if "could not translate host name" in m or "name or service not known" in m or "getaddrinfo" in m or "unknown host" in m:
        return "E-DB-06"
    if "timeout expired" in m or "timed out" in m:
        return "E-DB-05"
    if "connection refused" in m or "could not connect to server" in m or "is the server running" in m or "actively refused" in m:
        return "E-DB-01"
    if 'relation "' in m and "does not exist" in m:
        return "E-DB-09"
    if host and port and not port_open(host, port):
        return "E-DB-01"
    return "E-DB-99"


def report_fatal(code, detail="", exc=None, summary=None):
    """Catat kegagalan fatal ke semua tujuan dan tampilkan petunjuk perbaikan."""
    title, hint = CODES.get(code, CODES["E-APP-01"])
    log = logging.getLogger("dhk")
    log.error("[%s] %s | %s", code, title, detail, exc_info=exc if isinstance(exc, BaseException) else None)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "=" * 72, f"APLIKASI TIDAK DAPAT DIJALANKAN   {now}", "=" * 72,
        f"Kode      : {code}", f"Masalah   : {title}", f"Rincian   : {detail}", f"Perbaikan : {hint}", "",
        f"Server    : {platform.node()} ({platform.platform()})", f"Python    : {sys.version.split()[0]}",
        f"Folder    : {LOGDIR.resolve().parent}",
    ]
    for k, v in (summary or {}).items():
        lines.append(f"{k:<10}: {v}")
    if isinstance(exc, BaseException):
        lines += ["", "Jejak teknis:", "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()]
    lines += ["", f"Log lengkap: {LOGDIR.resolve()}", "Jalankan  DHKRegister.exe --diagnose  untuk pemeriksaan menyeluruh.", "=" * 72]
    text = "\n".join(lines)
    try:
        (LOGDIR / "STARTUP_ERROR.txt").write_text(text, encoding="utf-8")
    except Exception:
        pass
    try:
        print("\n" + text, file=sys.stderr)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            subprocess.run(["eventcreate", "/T", "ERROR", "/ID", "901", "/L", "APPLICATION", "/SO", "DHKRegister",
                            "/D", f"[{code}] {title}. {detail}"[:1000]], capture_output=True, timeout=10)
        except Exception:
            pass
    if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
        try:
            input("\nTekan Enter untuk menutup...")
        except Exception:
            pass


def clear_startup_error():
    try:
        (LOGDIR / "STARTUP_ERROR.txt").unlink()
    except Exception:
        pass
