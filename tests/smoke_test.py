"""Uji menyeluruh (smoke/regression). Jalankan dari folder aplikasi:

    set DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/dhk_test   (database uji KOSONG, jangan database produksi)
    python tests/smoke_test.py

Tanpa DATABASE_URL, memakai SQLite sementara. Exit code 0 bila semua lulus.
"""
import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TMP / 't.db'}")
os.environ["HTTPS"] = "false"

from app import create_app, init_db                    # noqa: E402
from app.models import AppInfo, AuditLog, Parameter, Register, User, db   # noqa: E402

app = create_app({"WTF_CSRF_ENABLED": False, "SESSION_COOKIE_SECURE": False, "ADMIN_PASSWORD": "Admin#12345x", "HTTPS": False})
with app.app_context():
    if "sqlite" not in os.environ["DATABASE_URL"]:
        db.drop_all()
init_db(app)
c = app.test_client()
RES = []


def chk(name, cond, extra=""):
    RES.append(bool(cond))
    print(("PASS" if cond else "FAIL"), name, extra)


with app.app_context():
    from app.dbsetup import verify_schema
    chk("semua tabel ada", verify_schema(db) == [], str(len(db.metadata.tables)) + " tabel")
    chk("app_info terisi", db.session.get(AppInfo, "schema_version") is not None)
r = c.get("/health"); chk("/health tanpa login", r.status_code == 200 and r.get_json()["status"] == "ok")
r = c.post("/login", data={"username": "admin", "password": "salah"}); chk("login salah", b"salah" in r.data)
r = c.post("/login", data={"username": "admin", "password": "Admin#12345x"}, follow_redirects=True); chk("login ok -> paksa ganti pw", b"Ubah password" in r.data)
r = c.post("/password", data={"old": "Admin#12345x", "new": "Baru#Passw0rd!", "new2": "Baru#Passw0rd!"}, follow_redirects=True); chk("ganti pw -> dashboard", b"Total distribusi" in r.data)
for p in ["/dashboard", "/register", "/register/new", "/register/import", "/laporan", "/admin/parameter", "/admin/parameter?cat=KLASIFIKASI",
          "/admin/pengguna", "/admin/hak-akses", "/admin/audit", "/register/template.xlsx"]:
    r = c.get(p); chk("GET " + p, r.status_code == 200, r.status_code)
f = dict(tanggal_permintaan="2026-10-01", unit_kerja="Hukum dan Kepatuhan", pic="Andi", dokumen_hukum="Perjanjian Kerja Sama X", pihak_ketiga="PT ABC",
         tujuan="Due diligence", media="Email", klasifikasi="Rahasia", watermark="Y", isi_watermark="Confidential - PT ABC", password="T",
         data_pribadi="Y", redaksi="T", nda="T", pic_dhk="Budi")
r = c.post("/register/new", data=f, follow_redirects=True); chk("tambah register", b"Register tersimpan" in r.data); chk("temuan kepatuhan tampil", b"temuan kontrol" in r.data)
r = c.get("/register/new"); chk("form baru tidak menampilkan teks 'None'", b'value="None"' not in r.data and b">None</textarea>" not in r.data)
r = c.get("/register?q=ABC"); chk("pencarian", b"Perjanjian Kerja" in r.data)
from datetime import date   # noqa: E402
from app.services import parse_date   # noqa: E402
chk("parse_date ISO tidak tertukar (2026-04-12 = 12 April)", parse_date("2026-04-12") == date(2026, 4, 12) and parse_date("2026-10-01") == date(2026, 10, 1))
chk("parse_date dd/mm/yyyy (05/10/2026 = 5 Oktober)", parse_date("05/10/2026") == date(2026, 10, 5))
with app.app_context():
    chk("tanggal tersimpan dari form benar", db.session.get(Register, 1).tanggal_permintaan == date(2026, 10, 1))
r = c.get("/register?dari=2026-10-01&sampai=2026-10-01"); chk("filter rentang tanggal ISO", b"Perjanjian Kerja" in r.data)
r = c.get("/register?dari=2026-01-10&sampai=2026-01-10"); chk("filter tanggal tidak salah tafsir", b"Perjanjian Kerja" not in r.data)
pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
up = lambda data, name, **k: c.post("/register/1/upload", data={"files": (io.BytesIO(data), name), **k}, content_type="multipart/form-data", follow_redirects=True)
r = up(pdf, "kontrak.pdf"); chk("upload bersih", b"tersimpan setelah" in r.data)
r = up(pdf + b"v2", "kontrak.pdf", note="rev"); chk("versi 2", b"v2" in r.data)
eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
r = up(b"%PDF-1.4 " + eicar, "x.pdf"); chk("EICAR ditolak", b"INFECTED" in r.data)
r = up(b"MZ\x90\x00 exe", "a.pdf"); chk("magic mismatch ditolak", b"ditolak" in r.data)
r = up(b"MZ\x90", "a.exe"); chk("ekstensi exe ditolak", b"tidak diizinkan" in r.data)
r = up(b"%PDF-1.4 /JavaScript (app.alert)", "j.pdf"); chk("PDF JS ditolak", b"SUSPICIOUS" in r.data)
r = c.get("/dokumen/1"); chk("unduh dokumen (isi persis sama)", r.status_code == 200 and r.data == pdf)
from openpyxl import load_workbook   # noqa: E402
wb = load_workbook(io.BytesIO(c.get("/register/template.xlsx").data)); ws = wb["Register"]
ws.append(["05/10/2026", "Keuangan", "Sari", "NDA Vendor", "Terbatas", "PT XYZ", "Audit", "Portal / Data Room", "Y", "Conf - XYZ", "Y", "WhatsApp", "T", "T", "Y", "06/10/2026", "Budi", "ok"])
ws.append([None, "x", "x"])
b = io.BytesIO(); wb.save(b); b.seek(0)
r = c.post("/register/import", data={"file": (b, "isi.xlsx")}, content_type="multipart/form-data", follow_redirects=True); chk("import xlsx (1 masuk, 1 ditolak)", b"<b>1</b> baris berhasil" in r.data)
with app.app_context():
    xr = Register.query.filter_by(pihak_ketiga="PT XYZ").first()
    chk("tanggal import xlsx benar (5 & 6 Okt)", xr and xr.tanggal_permintaan == date(2026, 10, 5) and xr.tanggal_pengiriman == date(2026, 10, 6))
csvb = "No;Tanggal Permintaan;Unit Kerja;PIC;Dokumen Hukum;Pihak Ketiga;NDA (Y/T)\n1;01/09/2026;Keuangan;A;Doc CSV;PT CSV;Y\n".encode()
r = c.post("/register/import", data={"file": (io.BytesIO(csvb), "a.csv")}, content_type="multipart/form-data", follow_redirects=True); chk("import csv", b"<b>1</b> baris berhasil" in r.data)
for fmt in ["xlsx", "pdf", "csv", "docx"]:
    r = c.get(f"/laporan/unduh?format={fmt}&jenis=register&dari=2026-01-01&sampai=2026-12-31"); chk("unduh laporan " + fmt, r.status_code == 200 and len(r.data) > 500, len(r.data))
r = c.get("/laporan/unduh?format=pdf&jenis=audit"); chk("unduh audit pdf", r.status_code == 200)
r = c.get("/laporan?lihat=1&jenis=register"); chk("preview laporan", b"Unduh:" in r.data)
for p in ["/register?q=' OR 1=1--", "/register?q=<script>alert(1)</script>", "/register?q=../../etc/passwd", "/register?q=a;cat /etc/passwd", "/register?q=UNION SELECT password FROM users"]:
    r = c.get(p); chk("blok " + p[:40], r.status_code == 403)
r = c.get("/register", headers={"User-Agent": "sqlmap/1.7"}); chk("blok scanner UA", r.status_code == 403)
r = c.get("/register?q=Perjanjian select dari"); chk("tidak false positive", r.status_code == 200)
r = c.post("/admin/parameter/save", data={"category": "KLASIFIKASI", "label": "Internal", "level": 2, "color": "#336699", "req_wm": "1", "sort_order": 5}, follow_redirects=True); chk("tambah parameter", b"Internal" in r.data)
r = c.post("/admin/parameter/save", data={"new_category": "jenis dokumen", "label": "Kontrak"}, follow_redirects=True); chk("kategori baru", b"Kontrak" in r.data)
with app.app_context():
    pid = Parameter.query.filter_by(label="Rahasia").first().id
c.post("/admin/parameter/save", data={"id": pid, "category": "KLASIFIKASI", "label": "Rahasia Perusahaan", "level": 3, "req_wm": "1"}, follow_redirects=True)
with app.app_context():
    chk("rename parameter ikut ke register", db.session.get(Register, 1).klasifikasi == "Rahasia Perusahaan")
r = c.post("/admin/hak-akses/save", data={"name": "Tamu", "perms": ["dashboard"]}, follow_redirects=True); chk("role baru", b"Tamu" in r.data)
r = c.post("/admin/pengguna/save", data={"username": "rina", "full_name": "Rina", "role_id": 4, "password": "lemah", "active": "1"}, follow_redirects=True); chk("password lemah ditolak", b"minimal 10" in r.data)
r = c.post("/admin/pengguna/save", data={"username": "rina", "full_name": "Rina", "role_id": 4, "password": "Rina#Passw0rd1", "active": "1"}, follow_redirects=True); chk("user baru", b"rina" in r.data)
c2 = app.test_client()
c2.post("/login", data={"username": "rina", "password": "Rina#Passw0rd1"}, follow_redirects=True)
c2.post("/password", data={"old": "Rina#Passw0rd1", "new": "Rina#Passw0rd2", "new2": "Rina#Passw0rd2"}, follow_redirects=True)
r = c2.get("/admin/audit"); chk("RBAC: viewer tidak boleh buka audit", r.status_code == 403, r.status_code)
for _ in range(6):
    c2.post("/login", data={"username": "rina", "password": "x"})
r = c.get("/admin/audit?kategori=SECURITY"); chk("audit menampilkan MITRE (T1190, T1110)", b"T1190" in r.data and b"T1110" in r.data)
with app.app_context():
    acts = {a for (a,) in db.session.query(AuditLog.action).distinct()}
    need = {"LOGIN", "AKSES_MENU", "TAMBAH_REGISTER", "UPLOAD_DOKUMEN", "UPLOAD_DITOLAK", "GENERATE_LAPORAN", "UNDUH_LAPORAN", "IMPORT_REGISTER",
            "SERANGAN_TERDETEKSI", "LOGIN_GAGAL", "AKSES_DITOLAK"}
    chk("audit log lengkap", need <= acts, "" if need <= acts else f"kurang: {need - acts}")
# --- lupa password ---
c3 = app.test_client()
r = c3.get("/lupa-password"); chk("halaman lupa password terbuka", r.status_code == 200 and b"Lupa password" in r.data, r.status_code)
r = c3.get("/login"); chk("login memuat tautan lupa password", b"/lupa-password" in r.data)
r1 = c3.post("/lupa-password", data={"username": "rina"}); r2 = c3.post("/lupa-password", data={"username": "tidak-ada-xyz"})
chk("jawaban sama untuk akun ada/tidak ada", r1.status_code == 200 and r2.status_code == 200 and b"Jika username terdaftar" in r1.data and b"Jika username terdaftar" in r2.data)
r = c.get("/admin/pengguna"); chk("admin melihat permintaan reset", b"Permintaan reset password" in r.data and b"rina" in r.data)
with app.app_context():
    rid = User.query.filter_by(username="rina").first().id
r = c.post(f"/admin/pengguna/{rid}/reset", follow_redirects=True); chk("admin reset password", b"Password sementara untuk rina" in r.data)
import re as _re
tmp = _re.search(r"rina: (\S+)", r.get_data(as_text=True)); tmp = tmp.group(1) if tmp else ""
c4 = app.test_client()
r = c4.post("/login", data={"username": "rina", "password": tmp}, follow_redirects=True); chk("login dengan password sementara wajib ganti password", b"/password" in r.request.path.encode() or b"Ganti" in r.data, r.request.path)
with app.app_context():
    chk("audit RESET_PASSWORD & PERMINTAAN_RESET_PASSWORD", {"RESET_PASSWORD", "PERMINTAAN_RESET_PASSWORD"} <= {a for (a,) in db.session.query(AuditLog.action).distinct()})
print(f"\n{sum(RES)}/{len(RES)} lulus")
sys.exit(0 if all(RES) else 1)
