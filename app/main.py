import hashlib, io, mimetypes
from collections import Counter
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, abort
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from . import audit
from .auth import perm_required
from .models import db, Register, Attachment, AttachmentVersion, AuditLog
from .security import scan_file
from .services import (COLS, compliance, klas_map, reg_query, fill, import_file, make_template, parse_date, P, scope_unit, scope_filter, in_scope)

bp = Blueprint("main", __name__)
MONTHS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]

@bp.route("/health")
def health():
    """Tanpa login, tanpa rincian internal. Dipakai installer dan monitoring."""
    from sqlalchemy import text
    try:
        db.session.execute(text("SELECT 1"))
        return {"status": "ok"}, 200
    except Exception:
        try: db.session.rollback()
        except Exception: pass
        return {"status": "error", "db": "down"}, 503

def _guard(r):
    """Cegah akses register divisi lain lewat ID (IDOR). Dicatat sebagai kejadian keamanan."""
    if not in_scope(current_user, r):
        audit.log("AKSES_DIVISI_DITOLAK", menu="Register", category="SECURITY", level="WARN",
                  detail=f"Register #{r.id} milik '{r.unit_kerja}'; divisi pengguna '{current_user.unit_kerja or '-'}'",
                  mitre="T1213", tactic="Collection (Data from Information Repositories)")
        abort(403)

@bp.route("/")
@login_required
def home():
    return redirect(url_for("main.dashboard" if current_user.can("dashboard") else "main.register_list"))

@bp.route("/dashboard")
@perm_required("dashboard")
def dashboard():
    regs, kmap, today = scope_filter(Register.query, current_user).all(), klas_map(), date.today()
    ym = []
    y, m = today.year, today.month
    for i in range(11, -1, -1):
        mm, yy = m - i, y
        while mm <= 0: mm += 12; yy -= 1
        ym.append((yy, mm))
    cnt = Counter((r.tanggal_permintaan.year, r.tanggal_permintaan.month) for r in regs if r.tanggal_permintaan)
    kl = Counter(r.klasifikasi or "Belum diklasifikasi" for r in regs)
    un = Counter(r.unit_kerja or "-" for r in regs).most_common(8)
    ctrl = [("Watermark", "watermark"), ("Password", "password"), ("Redaksi/Masking", "redaksi"), ("NDA", "nda")]
    bad = [(r, compliance(r, kmap)) for r in regs]; bad = [(r, i) for r, i in bad if i]
    charts = {
        "bulan": {"labels": [f"{MONTHS[b - 1]} {a % 100}" for a, b in ym], "values": [cnt.get(k, 0) for k in ym]},
        "klas": {"labels": list(kl.keys()), "values": list(kl.values()), "colors": [(kmap.get(k) or {}).get("color", "#94a3b8") for k in kl]},
        "unit": {"labels": [u for u, _ in un], "values": [n for _, n in un]},
        "kontrol": {"labels": [l for l, _ in ctrl], "ya": [sum(1 for r in regs if getattr(r, f)) for _, f in ctrl],
                    "tidak": [sum(1 for r in regs if not getattr(r, f)) for _, f in ctrl]},
    }
    kpi = {"total": len(regs), "bulan_ini": cnt.get((today.year, today.month), 0),
           "data_pribadi": sum(r.data_pribadi for r in regs), "belum_kirim": sum(1 for r in regs if not r.tanggal_pengiriman),
           "tidak_sesuai": len(bad), "tanpa_nda": sum(1 for r in regs if not r.nda)}
    sec = []
    if current_user.can("audit"):
        sec = AuditLog.query.filter(AuditLog.category == "SECURITY", AuditLog.ts >= datetime.now() - timedelta(days=7)) \
            .order_by(AuditLog.ts.desc()).limit(6).all()
    top = Counter(r.pihak_ketiga for r in regs if r.pihak_ketiga).most_common(6)
    return render_template("dashboard.html", charts=charts, kpi=kpi, recent=sorted(regs, key=lambda r: r.id, reverse=True)[:7],
                           bad=bad[:6], sec=sec, top=top, kmap=kmap)

@bp.route("/register")
@perm_required("register_view")
def register_list():
    page = request.args.get("page", 1, type=int)
    pg = reg_query(request.args, current_user).paginate(page=page, per_page=15, error_out=False)
    kmap = klas_map()
    return render_template("register_list.html", pg=pg, kmap=kmap, comp={r.id: compliance(r, kmap) for r in pg.items},
                           klas=P("KLASIFIKASI"), units=P("UNIT_KERJA"))

def _form_ctx(r):
    return dict(r=r, klas=P("KLASIFIKASI"), units=P("UNIT_KERJA"), media=P("MEDIA"), cara=P("CARA_KIRIM_PASSWORD"),
                tujuan=P("TUJUAN"), kmap_json={k: v for k, v in klas_map().items()}, scope=scope_unit(current_user))

def _save(r, new):
    before = {c: getattr(r, c) for c, _, _ in COLS}
    fill(r, request.form)
    su = scope_unit(current_user)
    if su == "":
        flash("Akun Anda belum dikaitkan dengan divisi; hubungi administrator.", "error"); return False
    if su is not None: r.unit_kerja = su   # pengguna per divisi: unit kerja selalu divisinya sendiri
    miss = [l for c, l, _ in COLS if c in ("tanggal_permintaan", "unit_kerja", "dokumen_hukum", "pihak_ketiga") and not getattr(r, c)]
    if miss:
        flash("Lengkapi kolom wajib: " + ", ".join(miss), "error"); return False
    r.updated_by = current_user.username
    if new: r.created_by = current_user.username; db.session.add(r)
    db.session.commit()
    chg = [l for c, l, _ in COLS if before[c] != getattr(r, c)]
    audit.log("TAMBAH_REGISTER" if new else "UBAH_REGISTER", menu="Register", detail=f"#{r.id} {r.dokumen_hukum[:80]}" + ("" if new else f" | kolom diubah: {', '.join(chg) or '-'}"))
    return True

@bp.route("/register/new", methods=["GET", "POST"])
@perm_required("register_edit")
def register_new():
    r = Register(tanggal_permintaan=date.today())
    if request.method == "POST":
        r = Register()
        if _save(r, True): flash("Register tersimpan.", "ok"); return redirect(url_for("main.register_detail", rid=r.id))
    return render_template("register_form.html", **_form_ctx(r))

@bp.route("/register/<int:rid>/edit", methods=["GET", "POST"])
@perm_required("register_edit")
def register_edit(rid):
    r = db.get_or_404(Register, rid); _guard(r)
    if request.method == "POST" and _save(r, False):
        flash("Perubahan tersimpan.", "ok"); return redirect(url_for("main.register_detail", rid=r.id))
    return render_template("register_form.html", **_form_ctx(r))

@bp.route("/register/<int:rid>")
@perm_required("register_view")
def register_detail(rid):
    r = db.get_or_404(Register, rid); _guard(r); kmap = klas_map()
    return render_template("register_detail.html", r=r, issues=compliance(r, kmap), meta=kmap.get(r.klasifikasi) or {}, COLS=COLS)

@bp.route("/register/<int:rid>/delete", methods=["POST"])
@perm_required("register_delete")
def register_delete(rid):
    r = db.get_or_404(Register, rid); _guard(r); info = f"#{r.id} {r.dokumen_hukum[:80]} ({r.pihak_ketiga[:60]})"
    db.session.delete(r); db.session.commit()
    audit.log("HAPUS_REGISTER", menu="Register", detail=info, level="WARN"); flash("Register dihapus.", "ok")
    return redirect(url_for("main.register_list"))

@bp.route("/register/<int:rid>/upload", methods=["POST"])
@perm_required("document_upload")
def upload(rid):
    r = db.get_or_404(Register, rid); _guard(r); aid = request.form.get("attachment_id", type=int); note = request.form.get("note", "")[:250]
    done = 0
    for f in request.files.getlist("files"):
        if not f or not f.filename: continue
        name = secure_filename(f.filename) or "dokumen"; data = f.read()
        res = scan_file(name, data)
        if res["status"] != "CLEAN":
            audit.log("UPLOAD_DITOLAK", menu="Dokumen", category="SECURITY", level="HIGH" if res["status"] in ("INFECTED", "SUSPICIOUS") else "WARN",
                      detail=f"{name} → {res['status']}: {res['detail']}", mitre=res["mitre"], tactic=res["tactic"])
            flash(f"{name} ditolak ({res['status']}): {res['detail']}", "error"); continue
        att = db.session.get(Attachment, aid) if aid else Attachment.query.filter_by(register_id=r.id, name=name).first()
        if att is None or att.register_id != r.id:
            att = Attachment(register_id=r.id, name=name); db.session.add(att); db.session.flush()
        ver = max([v.version for v in att.versions] or [0]) + 1
        db.session.add(AttachmentVersion(attachment_id=att.id, version=ver, filename=name, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                         mime=mimetypes.guess_type(name)[0] or "application/octet-stream", scan_status="CLEAN",
                                         scan_detail=res["detail"], note=note, uploaded_by=current_user.username, content=data))
        db.session.commit(); done += 1
        audit.log("UPLOAD_DOKUMEN", menu="Dokumen", detail=f"Register #{r.id}: {name} v{ver} ({len(data)//1024} KB, lolos pemindaian)")
    if done: flash(f"{done} dokumen tersimpan setelah lolos pemindaian.", "ok")
    return redirect(url_for("main.register_detail", rid=rid))

@bp.route("/dokumen/<int:vid>")
@perm_required("document_download")
def download(vid):
    v = db.get_or_404(AttachmentVersion, vid); _guard(v.attachment.register)
    audit.log("UNDUH_DOKUMEN", menu="Dokumen", detail=f"Register #{v.attachment.register_id}: {v.filename} v{v.version}")
    return send_file(io.BytesIO(v.content), download_name=v.filename, mimetype=v.mime, as_attachment=True)

@bp.route("/register/import", methods=["GET", "POST"])
@perm_required("register_import")
def register_import():
    result = None
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename: flash("Pilih file template (.xlsx atau .csv).", "error")
        else:
            name = secure_filename(f.filename); data = f.read(); res = scan_file(name, data)
            if not name.lower().endswith((".xlsx", ".csv")): flash("Hanya .xlsx atau .csv.", "error")
            elif res["status"] != "CLEAN":
                audit.log("IMPORT_DITOLAK", menu="Import", category="SECURITY", level="HIGH", detail=f"{name}: {res['detail']}", mitre=res["mitre"], tactic=res["tactic"])
                flash(f"File ditolak ({res['status']}): {res['detail']}", "error")
            else:
                try: ok, errs = import_file(name, data, current_user)
                except Exception as e: db.session.rollback(); ok, errs = 0, [f"File tidak dapat dibaca: {e}"]
                audit.log("IMPORT_REGISTER", menu="Import", detail=f"{name}: {ok} baris masuk, {len(errs)} ditolak")
                result = (ok, errs)
    return render_template("import.html", result=result)

@bp.route("/register/template.xlsx")
@perm_required("register_import")
def template_xlsx():
    audit.log("UNDUH_TEMPLATE", menu="Import")
    return send_file(io.BytesIO(make_template()), download_name="Template_Register_DHK.xlsx", as_attachment=True,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
