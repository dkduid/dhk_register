"""Bootstrap database: pastikan role + database ada, tabel lengkap, dan sediakan pemeriksaan (diagnose)."""
import logging
import os
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from .errors import CODES, StartupError, classify, mask_url, port_open

log = logging.getLogger("dhk.db")


def is_postgres(uri):
    return make_url(uri).drivername.startswith("postgresql")


def _pg_connect(url, user=None, password=None, dbname=None):
    import psycopg2
    return psycopg2.connect(host=url.host or "localhost", port=url.port or 5432, dbname=dbname or url.database,
                            user=user or url.username, password=password if password is not None else url.password,
                            connect_timeout=5)


def _try_connect(url):
    c = _pg_connect(url)
    c.close()


def ensure_database(cfg):
    """Pastikan PostgreSQL dapat dihubungi dengan DATABASE_URL. Bila role/database belum ada dan
    PG_ADMIN_PASSWORD tersedia, buat otomatis. Return 'ok' | 'dibuat' | 'lewati'. Raise StartupError bila gagal."""
    uri = cfg["SQLALCHEMY_DATABASE_URI"]
    if not is_postgres(uri):
        return "lewati"
    url = make_url(uri)
    host, port = url.host or "localhost", url.port or 5432
    try:
        _try_connect(url)
        return "ok"
    except Exception as first:  # noqa: BLE001
        code = classify(first, host, port)
        log.warning("Koneksi awal ke %s gagal [%s]: %s", mask_url(uri), code, str(first).strip()[:300])
        if code in ("E-DB-02", "E-DB-03") and cfg.get("AUTO_CREATE_DB") and cfg.get("PG_ADMIN_PASSWORD"):
            _create_role_and_db(url, cfg)
            try:
                _try_connect(url)
                return "dibuat"
            except Exception as again:  # noqa: BLE001
                raise StartupError(classify(again, host, port), str(again).strip(), again)
        detail = str(first).strip()
        if code in ("E-DB-02", "E-DB-03") and not cfg.get("PG_ADMIN_PASSWORD"):
            detail += "  (Pembuatan otomatis dilewati: PG_ADMIN_PASSWORD tidak diisi.)"
        raise StartupError(code, detail, first)


def _create_role_and_db(url, cfg):
    from psycopg2 import sql
    user, pw, dbname = url.username, url.password or "", url.database
    try:
        conn = _pg_connect(url, user=cfg.get("PG_ADMIN_USER") or "postgres", password=cfg["PG_ADMIN_PASSWORD"],
                           dbname=cfg.get("PG_ADMIN_DB") or "postgres")
    except Exception as e:  # noqa: BLE001
        raise StartupError(classify(e, url.host, url.port or 5432),
                           f"Login superuser PostgreSQL gagal: {str(e).strip()}", e)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (user,))
        if cur.fetchone():
            cur.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(sql.Identifier(user), sql.Literal(pw)))
            log.warning("Role '%s' sudah ada; password disamakan dengan DATABASE_URL.", user)
        else:
            cur.execute(sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD {}").format(sql.Identifier(user), sql.Literal(pw)))
            log.info("Role '%s' dibuat.", user)
        cur.execute("SELECT 1 FROM pg_database WHERE datname=%s", (dbname,))
        if not cur.fetchone():
            cur.execute(sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0")
                        .format(sql.Identifier(dbname), sql.Identifier(user)))
            log.info("Database '%s' dibuat.", dbname)
        cur.close()
    except Exception as e:  # noqa: BLE001
        raise StartupError(classify(e), f"Gagal membuat role/database: {str(e).strip()}", e)
    finally:
        conn.close()
    # PostgreSQL 15+: hak CREATE pada schema public tidak lagi otomatis
    try:
        c2 = _pg_connect(url, user=cfg.get("PG_ADMIN_USER") or "postgres", password=cfg["PG_ADMIN_PASSWORD"], dbname=dbname)
        c2.autocommit = True
        c2.cursor().execute(sql.SQL("GRANT ALL ON SCHEMA public TO {}").format(sql.Identifier(user)))
        c2.close()
    except Exception:  # noqa: BLE001
        log.warning("Tidak dapat memberi hak pada schema public (diabaikan).", exc_info=True)


def verify_schema(db):
    """Return daftar tabel yang seharusnya ada tetapi belum ada."""
    have = set(inspect(db.engine).get_table_names())
    return sorted(set(db.metadata.tables) - have)


def export_schema_sql(db, path):
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable
    d = postgresql.dialect()
    out = ["-- Skema database Register DHK (PostgreSQL)",
           "-- Dibuat otomatis oleh: DHKRegister.exe --export-schema",
           "-- Aplikasi membuat tabel ini sendiri saat --init-db; berkas ini untuk keperluan DBA/dokumentasi.", ""]
    for t in db.metadata.sorted_tables:
        out.append(str(CreateTable(t).compile(dialect=d)).strip() + ";")
        for ix in sorted(t.indexes, key=lambda i: i.name or ""):
            out.append(str(CreateIndex(ix).compile(dialect=d)).strip() + ";")
        out.append("")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(out), encoding="utf-8")


# ---------------- Diagnose ----------------
def diagnose(Config, db=None, app=None):
    """Kumpulan pemeriksaan mandiri. Return list (status, nama, detail); status OK/WARN/FAIL."""
    R = []
    add = lambda s, n, d="": R.append((s, n, d))
    base = Path(Config.BASE_DIR)
    add("OK", "Lingkungan", f"Python {sys.version.split()[0]} | {sys.platform} | folder {base}")
    envf = base / ".env"
    add("OK" if envf.exists() else ("WARN" if "DATABASE_URL" in os.environ else "FAIL"), "Berkas .env",
        str(envf) if envf.exists() else "tidak ditemukan [E-CFG-01]")
    add("FAIL" if Config.SECRET_KEY.startswith("dev-") else "OK", "SECRET_KEY",
        "masih nilai bawaan [E-CFG-02]" if Config.SECRET_KEY.startswith("dev-") else "sudah diganti")
    try:
        t = base / "logs" / ".w"
        t.parent.mkdir(exist_ok=True)
        t.write_text("x")
        t.unlink()
        add("OK", "Folder logs dapat ditulis", str(base / "logs"))
    except Exception as e:  # noqa: BLE001
        add("FAIL", "Folder logs dapat ditulis", str(e))
    try:
        free = shutil.disk_usage(base).free / 1024 ** 3
        add("OK" if free >= 1 else "WARN", "Ruang disk bebas", f"{free:.1f} GB")
    except Exception:  # noqa: BLE001
        pass
    uri = Config.SQLALCHEMY_DATABASE_URI
    add("OK", "DATABASE_URL", mask_url(uri))
    url = make_url(uri)
    host, port = url.host or "localhost", url.port or 5432
    db_ok = False
    if is_postgres(uri):
        if port_open(host, port):
            add("OK", f"Port PostgreSQL terbuka ({host}:{port})")
        else:
            add("FAIL", f"Port PostgreSQL terbuka ({host}:{port})", f"{CODES['E-DB-01'][0]} [E-DB-01]")
        try:
            c = _pg_connect(url)
            cur = c.cursor()
            cur.execute("SELECT version()")
            add("OK", "Login database", cur.fetchone()[0][:90])
            c.close()
            db_ok = True
        except Exception as e:  # noqa: BLE001
            code = classify(e, host, port)
            add("FAIL", "Login database", f"[{code}] {CODES[code][0]} -> {str(e).strip()[:200]}")
    else:
        db_ok = True
        add("WARN", "Jenis database", f"{url.drivername} (bukan PostgreSQL; hanya untuk uji)")
    if db_ok and db is not None and app is not None:
        try:
            with app.app_context():
                miss = verify_schema(db)
                add("OK" if not miss else "FAIL", "Tabel database lengkap",
                    f"{len(db.metadata.tables)} tabel" if not miss else f"hilang: {', '.join(miss)} [E-DB-09]")
                if not miss:
                    from .models import Parameter, Role, User
                    nr, nu, npm = Role.query.count(), User.query.count(), Parameter.query.count()
                    add("OK" if (nr and nu and npm) else "WARN", "Data awal", f"role={nr}, pengguna={nu}, parameter={npm}")
        except Exception as e:  # noqa: BLE001
            add("FAIL", "Tabel database lengkap", f"[{classify(e)}] {str(e).strip()[:200]}")
    # port aplikasi
    try:
        s = socket.socket()
        s.settimeout(1)
        busy = s.connect_ex(("127.0.0.1", Config.PORT)) == 0
        s.close()
        if busy:
            from .healthcheck import check as hc
            ok, info = hc(Config)
            add("OK" if ok else "FAIL", f"Port aplikasi {Config.PORT}",
                "aplikasi sedang berjalan dan sehat" if ok else f"dipakai proses lain atau aplikasi tidak sehat ({info}) [E-NET-01]")
        else:
            add("OK", f"Port aplikasi {Config.PORT}", "bebas")
    except Exception as e:  # noqa: BLE001
        add("WARN", "Port aplikasi", str(e))
    if Config.HTTPS:
        crt, key = (Config.SSL_CERT, Config.SSL_KEY) if Config.SSL_CERT and Config.SSL_KEY else (str(base / "certs/server.crt"), str(base / "certs/server.key"))
        ok = Path(crt).exists() and Path(key).exists()
        add("OK" if ok else ("WARN" if not Config.SSL_CERT else "FAIL"), "Sertifikat HTTPS",
            crt if ok else ("belum ada; dibuat otomatis (self-signed) saat aplikasi dijalankan" if not Config.SSL_CERT else f"berkas tidak ditemukan [E-TLS-01]: {crt}"))
    else:
        add("WARN", "HTTPS", "dinonaktifkan (HTTPS=false); hanya untuk uji lokal")
    if Config.LDAP_ENABLED:
        ok = port_open(Config.LDAP_SERVER, Config.LDAP_PORT)
        add("OK" if ok else "WARN", f"LDAP ({Config.LDAP_SERVER}:{Config.LDAP_PORT})", "terjangkau" if ok else "tidak terjangkau [E-LDAP-01]")
    if Config.CLAMAV_ENABLED:
        ok = port_open(Config.CLAMAV_HOST, Config.CLAMAV_PORT)
        add("OK" if ok else ("FAIL" if Config.CLAMAV_REQUIRED else "WARN"), f"ClamAV ({Config.CLAMAV_HOST}:{Config.CLAMAV_PORT})",
            "terjangkau" if ok else "tidak terjangkau (upload " + ("DITOLAK" if Config.CLAMAV_REQUIRED else "memakai pemindai internal saja") + ")")
    return R


def format_report(results):
    mark = {"OK": "[ OK ]", "WARN": "[WARN]", "FAIL": "[GAGAL]"}
    lines = [f"PEMERIKSAAN REGISTER DHK   {datetime.now():%Y-%m-%d %H:%M:%S}", "-" * 72]
    for s, n, d in results:
        lines.append(f"{mark[s]:<8}{n}" + (f"\n        {d}" if d else ""))
    f = sum(1 for r in results if r[0] == "FAIL")
    w = sum(1 for r in results if r[0] == "WARN")
    lines += ["-" * 72, f"Ringkasan: {len(results) - f - w} OK, {w} peringatan, {f} gagal"]
    return "\n".join(lines)
