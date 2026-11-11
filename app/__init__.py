import logging, secrets
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template, request, g
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect, CSRFError
from config import Config
from . import audit, security
from .models import db, User, Role, Parameter, Register, AuditLog, AppInfo, PERMS
from .errors import init_logging, classify, StartupError
from .dbsetup import verify_schema
from sqlalchemy.exc import OperationalError, InterfaceError
from .services import P, CAT_LABEL
from datetime import datetime, timedelta

csrf, lm = CSRFProtect(), LoginManager()
lm.login_view = "auth.login"; lm.login_message = "Silakan masuk terlebih dahulu."

MENU = {"main.dashboard": "Dashboard", "main.register_list": "Register", "main.register_detail": "Detail register", "main.register_new": "Tambah register",
        "main.register_edit": "Ubah register", "main.register_import": "Import template", "reports.reports": "Laporan", "admin.parameters": "Parameter",
        "admin.users": "Pengguna", "admin.roles": "Hak akses", "admin.audit_view": "Audit log", "auth.password": "Ubah password"}

# Divisi pengguna (label parameter UNIT_KERJA, username akun login divisi)
DIVISIONS = [("Divisi Teknologi Informasi", "div.ti"), ("Divisi Audit", "div.audit"),
             ("Divisi SDM, Pengadaan dan Umum", "div.sdm"),
             ("Divisi Operasional dan Pengembangan Bisnis PBK dan Aset Digital", "div.pbk"),
             ("Divisi Operasional dan Pengembangan Bisnis PFK", "div.pfk"),
             ("Divisi Operasional dan Pengembangan Bisnis SRG", "div.srg"),
             ("Divisi Sekretaris Perusahaan", "div.sekper"), ("Divisi Strategis dan Perencanaan", "div.renstra"),
             ("Divisi Manajemen Risiko", "div.mr"), ("Divisi Keuangan dan Akuntansi", "div.keuangan")]
DIVISION_ROLE = ("Pengguna Divisi", "Mengajukan & memantau register divisinya sendiri",
                 ["dashboard", "register_view", "register_edit", "document_upload", "document_download", "report"])
# Unit kerja bawaan v1.1 yang digantikan daftar divisi (dinonaktifkan bila belum dipakai)
LEGACY_UNITS = ["Operasional Kliring", "Pasar Fisik Komoditas", "Sistem Resi Gudang", "Keuangan", "Manajemen Risiko", "SDM dan Umum"]

def create_app(overrides=None):
    # Windows membaca tipe MIME dari registry; bila .js/.css salah (mis. text/plain) 'nosniff' membuat peramban menolaknya.
    import mimetypes
    for ext, mt in ((".js", "text/javascript"), (".css", "text/css"), (".json", "application/json"), (".svg", "image/svg+xml")):
        mimetypes.add_type(mt, ext)
    app = Flask(__name__); app.config.from_object(Config)
    if overrides: app.config.update(overrides)
    db.init_app(app); csrf.init_app(app); lm.init_app(app)
    init_logging(Config.BASE_DIR / "logs")

    def _authed():
        try: return current_user.is_authenticated
        except Exception: return False

    from . import auth, main, admin, reports
    for m in (auth, main, admin, reports): app.register_blueprint(m.bp)

    @lm.user_loader
    def load(uid): return db.session.get(User, int(uid))

    @app.before_request
    def _guard():
        security.inspect_request()
        if current_user.is_authenticated and current_user.must_change_pw and request.endpoint not in ("auth.password", "auth.logout", "static"):
            from flask import redirect, url_for, flash
            flash("Demi keamanan, ganti password awal Anda terlebih dahulu.", "error"); return redirect(url_for("auth.password"))

    @app.after_request
    def _after(resp):
        if (_authed() and request.method == "GET" and resp.status_code == 200 and request.endpoint in MENU):
            audit.log("AKSES_MENU", menu=MENU[request.endpoint], detail=request.full_path.rstrip("?")[:200])
        resp.headers.update({"X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
                             "Cache-Control": "no-store" if _authed() else resp.headers.get("Cache-Control", "no-cache"),
                             "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; form-action 'self'"})
        if app.config["HTTPS"]: resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        return resp

    @app.context_processor
    def _ctx():
        from .services import scope_unit
        warn = 0
        try:
            if current_user.is_authenticated and current_user.can("audit"):
                warn = AuditLog.query.filter(AuditLog.level == "HIGH", AuditLog.ts >= datetime.now() - timedelta(hours=24)).count()
        except Exception:
            try: db.session.rollback()
            except Exception: pass
        ds = None
        try:
            if current_user.is_authenticated: ds = scope_unit(current_user)
        except Exception: pass
        return dict(P=P, CAT_LABEL=CAT_LABEL, sec_warn=warn, div_scope=ds)

    @app.template_filter("filesize")
    def _filesize(n):
        n = n or 0
        return f"{n} B" if n < 1024 else (f"{n / 1024:.1f} KB" if n < 1048576 else f"{n / 1048576:.1f} MB")

    @app.errorhandler(OperationalError)
    @app.errorhandler(InterfaceError)
    def edb(e):
        try: db.session.rollback()
        except Exception: pass
        code = classify(e)
        app.logger.error("[%s] Database tidak dapat diakses saat memproses %s %s: %s", code, request.method, request.path,
                         str(getattr(e, "orig", e)).strip()[:400])
        # render langsung dari Jinja: context processor Flask-Login (current_user) akan menyentuh DB lagi
        html = app.jinja_env.get_template("dberror.html").render(code=code, ts=datetime.now().strftime("%d/%m/%Y %H:%M:%S"))
        return html, 503, {"Content-Type": "text/html; charset=utf-8", "Retry-After": "30"}

    @app.errorhandler(403)
    def e403(e): return render_template("error.html", code=403, title="Akses ditolak", msg="Permintaan diblokir atau Anda tidak memiliki hak akses. Kejadian dicatat di audit log."), 403
    @app.errorhandler(404)
    def e404(e): return render_template("error.html", code=404, title="Halaman tidak ditemukan", msg="Periksa kembali alamat atau kembali ke dashboard."), 404
    @app.errorhandler(413)
    def e413(e): return render_template("error.html", code=413, title="File terlalu besar", msg=f"Batas ukuran upload {app.config['MAX_CONTENT_LENGTH']//1024//1024} MB."), 413
    @app.errorhandler(CSRFError)
    def ecsrf(e):
        audit.log("CSRF_GAGAL", menu=request.endpoint, category="SECURITY", level="WARN", detail=e.description, mitre="T1185", tactic="Collection (Browser Session Hijacking)")
        return render_template("error.html", code=400, title="Sesi formulir kedaluwarsa", msg="Muat ulang halaman lalu coba lagi."), 400
    @app.errorhandler(500)
    def e500(e):
        db.session.rollback(); app.logger.exception("Error aplikasi")
        audit.log("ERROR_APLIKASI", menu=request.endpoint, category="APPLICATION", level="ERROR", detail=repr(getattr(e, "original_exception", e))[:1000])
        try:
            return render_template("error.html", code=500, title="Terjadi kesalahan", msg="Kesalahan dicatat di application log."), 500
        except Exception:
            return "Terjadi kesalahan pada aplikasi (E-APP-01). Hubungi administrator; rincian ada di logs/error.log.", 500
    return app

def _migrate(app):
    """Migrasi ringan untuk database yang dibuat versi lama (idempoten)."""
    from sqlalchemy import inspect as _insp, text as _text
    eng = db.engine; tbl = User.__tablename__
    cols = {c["name"] for c in _insp(eng).get_columns(tbl)}
    if "unit_kerja" not in cols:
        q = eng.dialect.identifier_preparer.quote(tbl)
        with eng.begin() as cx: cx.execute(_text(f"ALTER TABLE {q} ADD COLUMN unit_kerja VARCHAR(150) DEFAULT ''"))
        app.logger.warning("Migrasi: kolom %s.unit_kerja ditambahkan.", tbl)
    # izin baru: Administrator (dan Super Admin) otomatis boleh melihat semua divisi
    changed = False
    for name in ("Administrator", "Super Admin"):
        r = Role.query.filter_by(name=name).first()
        if r and "all_divisions" not in (r.permissions or []):
            r.permissions = list(r.permissions or []) + ["all_divisions"]; changed = True
    if not Role.query.filter_by(name="Super Admin").first() and Role.query.filter_by(name="Administrator").first():
        db.session.add(Role(name="Super Admin", description="Akses penuh, semua divisi", permissions=list(PERMS))); changed = True
    if not Role.query.filter_by(name=DIVISION_ROLE[0]).first():
        db.session.add(Role(name=DIVISION_ROLE[0], description=DIVISION_ROLE[1], permissions=list(DIVISION_ROLE[2]))); changed = True
    if changed: db.session.commit()

def _sync_divisions(app):
    """Sekali per database: tambahkan 10 divisi ke UNIT_KERJA dan nonaktifkan unit bawaan lama yang belum dipakai."""
    if db.session.get(AppInfo, "divisions_v1"): return
    labels = {p.label.lower(): p for p in Parameter.query.filter_by(category="UNIT_KERJA").all()}
    top = max([p.sort_order or 0 for p in labels.values()] + [0])
    for i, (label, _) in enumerate(DIVISIONS, 1):
        p = labels.get(label.lower())
        if p: p.active = True
        else: db.session.add(Parameter(category="UNIT_KERJA", label=label, sort_order=top + i, meta={}))
    for label in LEGACY_UNITS:
        p = labels.get(label.lower())
        if p and not Register.query.filter_by(unit_kerja=p.label).first() and not User.query.filter_by(unit_kerja=p.label).first():
            p.active = False
    db.session.add(AppInfo(key="divisions_v1", value=datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    db.session.commit()
    app.logger.info("Daftar divisi (UNIT_KERJA) disesuaikan: %d divisi.", len(DIVISIONS))

def create_division_accounts():
    """Satu akun lokal per divisi (role Pengguna Divisi). Akun yang sudah ada tidak diubah.
    Mengembalikan [(divisi, username, password_sementara|None)]."""
    role = Role.query.filter_by(name=DIVISION_ROLE[0]).first()
    out = []
    for label, username in DIVISIONS:
        if User.query.filter(db.func.lower(User.username) == username).first():
            out.append((label, username, None)); continue
        pw = secrets.token_urlsafe(9) + "aA1!"
        u = User(username=username, full_name=label, role=role, unit_kerja=label, must_change_pw=True, auth_source="local")
        u.set_password(pw); db.session.add(u); db.session.commit()
        audit.log("TAMBAH_USER", menu="CLI", detail=f"--akun-divisi: {username} ({label})", username="CLI")
        out.append((label, username, pw))
    return out

def init_db(app):
    """Idempotent: buat tabel + seed role, parameter, dan admin awal."""
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            raise StartupError(classify(e), f"Gagal membuat tabel: {str(getattr(e, 'orig', e)).strip()[:300]}", e)
        if Role.query.count() == 0:
            allp = list(PERMS)
            for n, d, pm in [("Administrator", "Akses penuh", allp),
                             ("Legal & Compliance", "Pengelola register DHK", ["dashboard", "register_view", "register_edit", "register_import", "document_upload", "document_download", "report"]),
                             ("Auditor", "Baca saja + audit log", ["dashboard", "register_view", "document_download", "report", "audit"]),
                             ("Viewer", "Hanya melihat", ["dashboard", "register_view"]),
                             ("Super Admin", "Akses penuh, semua divisi", allp)]:
                db.session.add(Role(name=n, description=d, permissions=pm))
            db.session.commit()
        _migrate(app)
        if Parameter.query.count() == 0:
            K = lambda l, d, lv, c, w, p, n: Parameter(category="KLASIFIKASI", label=l, description=d, sort_order=5 - lv, meta=dict(color=c, level=lv, req_wm=w, req_pw=p, req_nda=n))
            seed = [K("Sangat Rahasia", "Dampak sangat berat bila bocor (ISO 27001 A.5.12 / NIST FIPS 199: High). Wajib watermark, password, NDA.", 4, "#b42318", True, True, True),
                    K("Rahasia", "Dampak berat bila bocor (Confidential). Wajib watermark, password, NDA.", 3, "#d9480f", True, True, True),
                    K("Terbatas", "Hanya untuk pihak berkepentingan (Restricted/Internal). Wajib watermark.", 2, "#b7791f", True, False, False),
                    K("Publik", "Boleh dibagikan (Public). Tidak ada kontrol wajib.", 1, "#2f855a", False, False, False)]
            for cat, items in {"UNIT_KERJA": ["Hukum dan Kepatuhan"] + [d for d, _ in DIVISIONS],
                               "MEDIA": ["Email", "Portal / Data Room", "Media fisik (USB)", "Hardcopy", "Aplikasi kolaborasi"],
                               "CARA_KIRIM_PASSWORD": ["Telepon", "WhatsApp", "Email terpisah", "Media lainnya"],
                               "TUJUAN": ["Due diligence", "Audit", "Regulator (BAPPEBTI/OJK)", "Kontrak / kerja sama", "Litigasi", "Lainnya"]}.items():
                seed += [Parameter(category=cat, label=i, sort_order=n, meta={}) for n, i in enumerate(items)]
            db.session.add_all(seed); db.session.commit()
        _sync_divisions(app)
        if User.query.count() == 0:
            c = app.config; pw = c["ADMIN_PASSWORD"] or (secrets.token_urlsafe(9) + "aA1!")
            u = User(username=c["ADMIN_USERNAME"], full_name="Administrator", role=Role.query.filter_by(name="Administrator").first(), must_change_pw=True)
            u.set_password(pw); db.session.add(u); db.session.commit()
            app.logger.warning("Admin awal dibuat: %s (wajib ganti password saat login pertama)", u.username)
            print(f"\n=== Admin awal dibuat ===\n  username: {u.username}\n  password: {pw}\n  (wajib diganti saat login pertama)\n")
        for k, v in (("schema_version", "1.1"), ("installed_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))):
            if not db.session.get(AppInfo, k): db.session.add(AppInfo(key=k, value=v))
        db.session.commit()
        miss = verify_schema(db)
        if miss: raise StartupError("E-DB-09", "Tabel belum lengkap: " + ", ".join(miss))
        app.logger.info("Database siap: %d tabel.", len(db.metadata.tables))
