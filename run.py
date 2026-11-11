"""Titik masuk aplikasi.

  DHKRegister.exe                  jalankan server
  DHKRegister.exe --init-db        siapkan database (buat role/DB bila perlu, buat tabel, data awal) lalu selesai
  DHKRegister.exe --diagnose       pemeriksaan menyeluruh, hasil ke logs\\diagnose_*.txt
  DHKRegister.exe --healthcheck    cek apakah aplikasi yang sedang berjalan sehat (exit 0 = sehat)
  DHKRegister.exe --export-schema  tulis db\\schema.sql
  DHKRegister.exe --reset-admin [USERNAME]   setel ulang password akun (bawaan: admin), buka kunci, wajib ganti saat login
  DHKRegister.exe --akun-divisi    buat satu akun login per divisi (password sementara ke AKUN_DIVISI_AWAL.txt)

Kode keluar: 0 sukses | 1 error tak terduga | 2 gagal startup terklasifikasi (lihat logs\\STARTUP_ERROR.txt) | 3 diagnose menemukan masalah
"""
import argparse
import datetime
import ipaddress
import os
import socket
import sys
from datetime import timedelta
from pathlib import Path

from config import Config
from app.errors import (StartupError, classify, clear_startup_error, init_logging, install_hooks, mask_url, report_fatal)

VERSION = "1.1"


def _summary():
    return {"Database": mask_url(Config.SQLALCHEMY_DATABASE_URI), "Port": f"{Config.PORT} ({'HTTPS' if Config.HTTPS else 'HTTP'})",
            "Versi": VERSION}


def ensure_cert(d: Path):
    d.mkdir(exist_ok=True)
    crt, key = d / "server.crt", d / "server.key"
    if crt.exists() and key.exists():
        return str(crt), str(key)
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "dhk-register")])
    now = datetime.datetime.utcnow()
    san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    try:
        san.append(x509.DNSName(socket.gethostname()))
    except Exception:
        pass
    c = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key())
         .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
         .not_valid_after(now + timedelta(days=825)).add_extension(x509.SubjectAlternativeName(san), False).sign(k, hashes.SHA256()))
    key.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                    serialization.NoEncryption()))
    crt.write_bytes(c.public_bytes(serialization.Encoding.PEM))
    return str(crt), str(key)


def validate_config():
    env_file = Config.BASE_DIR / ".env"
    if not env_file.exists() and "DATABASE_URL" not in os.environ:
        raise StartupError("E-CFG-01", f"Tidak ada {env_file}")
    if not (1 <= Config.PORT <= 65535):
        raise StartupError("E-CFG-02", f"PORT={Config.PORT} di luar rentang 1-65535")
    if Config.SECRET_KEY.startswith("dev-") and getattr(sys, "frozen", False):
        raise StartupError("E-CFG-02", "SECRET_KEY masih nilai bawaan; ganti dengan string acak panjang di .env")


def check_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((Config.HOST, Config.PORT))
    except OSError as e:
        raise StartupError("E-NET-01", f"{Config.HOST}:{Config.PORT} -> {e}", e)
    finally:
        s.close()


def prepare_app():
    """validate -> database -> app -> tabel. Raise StartupError bila gagal."""
    from app import create_app, init_db
    from app.dbsetup import ensure_database
    validate_config()
    cfg = {k: getattr(Config, k) for k in dir(Config) if k.isupper()}
    state = ensure_database(cfg)
    app = create_app()
    init_db(app)
    return app, state


def do_reset_admin(username):
    """Pemulihan akses: password baru acak (atau dari env ADMIN_PASSWORD), akun diaktifkan dan dibuka kuncinya."""
    import secrets
    from app import audit
    from app.models import User, db
    from app.auth import valid_password
    app, _ = prepare_app()
    with app.app_context():
        u = User.query.filter(db.func.lower(User.username) == username.lower()).first()
        if not u:
            names = ", ".join(x.username for x in User.query.order_by(User.id).limit(10).all())
            print(f"Akun '{username}' tidak ditemukan. Akun yang ada: {names}")
            return 2
        if u.auth_source != "local":
            print(f"Akun '{u.username}' memakai LDAP; password diatur di direktori perusahaan.")
            return 2
        pw = os.environ.get("ADMIN_PASSWORD") or (secrets.token_urlsafe(9) + "aA1!")
        err = valid_password(pw)
        if err:
            print("ADMIN_PASSWORD tidak memenuhi kebijakan: " + err)
            return 2
        u.set_password(pw); u.active = True; u.failed_login = 0; u.locked_until = None; u.must_change_pw = True
        db.session.commit()
        audit.log("RESET_PASSWORD", menu="CLI", detail=f"--reset-admin untuk {u.username}", level="WARN", username="CLI")
        print(f"\n=== Password direset ===\n  username: {u.username}\n  password: {pw}\n  (akun aktif, kunci dibuka; wajib diganti saat login pertama)\n")
    return 0


def do_division_accounts():
    """Buat akun per divisi; password sementara hanya ditulis ke AKUN_DIVISI_AWAL.txt (tidak ke layar)."""
    from app import create_division_accounts
    app, _ = prepare_app()
    with app.app_context():
        rows = create_division_accounts()
    made = [r for r in rows if r[2]]
    for label, un, pw in rows:
        print(f"  {un:<14} {label}{'' if pw else '  (sudah ada, tidak diubah)'}")
    if made:
        out = Config.BASE_DIR / "AKUN_DIVISI_AWAL.txt"
        out.write_text("Akun login divisi Register DHK - password sementara, wajib diganti saat login pertama.\n"
                       "Bagikan ke tiap divisi melalui kanal aman, lalu HAPUS file ini.\n\n"
                       + "\n".join(f"{label}\n  username: {un}\n  password: {pw}\n" for label, un, pw in made), encoding="utf-8")
        print(f"\n{len(made)} akun dibuat. Password sementara: {out}")
    else:
        print("\nSemua akun divisi sudah ada.")
    return 0


def do_diagnose():
    from app import create_app
    from app.dbsetup import diagnose, format_report
    from app.models import db
    try:
        app = create_app()
    except Exception:  # noqa: BLE001
        app = None
    res = diagnose(Config, db if app else None, app)
    txt = format_report(res)
    print(txt)
    out = Config.BASE_DIR / "logs" / f"diagnose_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
    out.write_text(txt, encoding="utf-8")
    print(f"\nLaporan disimpan: {out}")
    return 3 if any(r[0] == "FAIL" for r in res) else 0


def main():
    ap = argparse.ArgumentParser(description="Register DHK", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--init-db", action="store_true")
    ap.add_argument("--diagnose", action="store_true")
    ap.add_argument("--healthcheck", action="store_true")
    ap.add_argument("--export-schema", action="store_true")
    ap.add_argument("--version", action="store_true")
    ap.add_argument("--reset-admin", nargs="?", const="", metavar="USERNAME")
    ap.add_argument("--akun-divisi", action="store_true")
    a = ap.parse_args()
    init_logging(Config.BASE_DIR / "logs")
    install_hooks()
    if a.version:
        print(VERSION)
        return 0
    try:
        if a.healthcheck:
            from app.healthcheck import check
            ok, info = check(Config)
            print(("SEHAT: " if ok else "TIDAK SEHAT: ") + info)
            return 0 if ok else 1
        if a.diagnose:
            return do_diagnose()
        if a.export_schema:
            from app.dbsetup import export_schema_sql
            from app.models import db
            out = Config.BASE_DIR / "db" / "schema.sql"
            export_schema_sql(db, out)
            print(f"Skema ditulis ke {out}")
            return 0
        if a.reset_admin is not None:
            return do_reset_admin(a.reset_admin or Config.ADMIN_USERNAME)
        if a.akun_divisi:
            return do_division_accounts()
        app, state = prepare_app()
        clear_startup_error()
        if a.init_db:
            print({"ok": "Database sudah siap (tabel diperiksa).", "dibuat": "Role dan database dibuat, tabel dan data awal siap.",
                   "lewati": "Database non-PostgreSQL; tabel dibuat."}[state])
            return 0
        check_port()
        from cheroot.wsgi import Server
        srv = Server((Config.HOST, Config.PORT), app, numthreads=20)
        if Config.HTTPS:
            try:
                from cheroot.ssl.builtin import BuiltinSSLAdapter
                crt, key = (Config.SSL_CERT, Config.SSL_KEY) if Config.SSL_CERT and Config.SSL_KEY else ensure_cert(Config.BASE_DIR / "certs")
                if not (Path(crt).exists() and Path(key).exists()):
                    raise FileNotFoundError(f"{crt} / {key}")
                srv.ssl_adapter = BuiltinSSLAdapter(crt, key)
            except Exception as e:  # noqa: BLE001
                raise StartupError("E-TLS-01", str(e), e)
        app.logger.info("Aplikasi dijalankan pada %s:%s (%s)", Config.HOST, Config.PORT, "HTTPS" if Config.HTTPS else "HTTP")
        print(f"DHK Register berjalan di {'https' if Config.HTTPS else 'http'}://localhost:{Config.PORT}  (Ctrl+C untuk berhenti)")
        try:
            srv.start()
        except KeyboardInterrupt:
            srv.stop()
        except OSError as e:
            raise StartupError("E-NET-01", str(e), e)
        return 0
    except StartupError as e:
        report_fatal(e.code, e.detail, e.exc or e, _summary())
        return 2
    except Exception as e:  # noqa: BLE001
        code = classify(e)
        report_fatal(code if code != "E-DB-99" else "E-APP-01", f"{type(e).__name__}: {e}", e, _summary())
        return 1


if __name__ == "__main__":
    sys.exit(main())
