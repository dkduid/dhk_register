import re
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from sqlalchemy import or_
from . import audit
from .auth import perm_required, valid_password
from .models import db, Parameter, User, Role, Register, AuditLog, PERMS
from .services import CATMAP, CAT_LABEL, P
from .services import parse_date

bp = Blueprint("admin", __name__, url_prefix="/admin")

# ---------- Parameter ----------
@bp.route("/parameter")
@perm_required("param")
def parameters():
    cats = [c for (c,) in db.session.query(Parameter.category).distinct().order_by(Parameter.category)]
    ORDER = ["KLASIFIKASI", "UNIT_KERJA", "MEDIA", "TUJUAN", "CARA_KIRIM_PASSWORD"]
    cats = sorted(cats, key=lambda c: (ORDER.index(c) if c in ORDER else 99, c))
    cat = request.args.get("cat") or (cats[0] if cats else "KLASIFIKASI")
    items = Parameter.query.filter_by(category=cat).order_by(Parameter.sort_order, Parameter.label).all()
    edit = db.session.get(Parameter, request.args.get("edit", type=int)) if request.args.get("edit") else None
    return render_template("parameters.html", cats=cats, cat=cat, items=items, edit=edit, CAT_LABEL=CAT_LABEL, CATMAP=CATMAP)

@bp.route("/parameter/save", methods=["POST"])
@perm_required("param")
def parameter_save():
    f = request.form; pid = f.get("id", type=int)
    cat = re.sub(r"\W+", "_", (f.get("new_category") or f.get("category") or "").strip().upper()).strip("_")[:40]
    label = (f.get("label") or "").strip()[:150]
    if not cat or not label: flash("Kategori dan nama wajib diisi.", "error"); return redirect(url_for("admin.parameters", cat=cat))
    meta = {"color": f.get("color") or "#64748b", "level": f.get("level", type=int) or 0,
            "req_wm": f.get("req_wm") == "1", "req_pw": f.get("req_pw") == "1", "req_nda": f.get("req_nda") == "1"}
    dup = Parameter.query.filter_by(category=cat, label=label).first()
    if dup and dup.id != pid: flash("Nama sudah ada di kategori ini.", "error"); return redirect(url_for("admin.parameters", cat=cat))
    p = db.session.get(Parameter, pid) if pid else Parameter(category=cat)
    old = p.label if pid else None
    p.label, p.description, p.sort_order, p.meta = label, (f.get("description") or "")[:1000], f.get("sort_order", type=int) or 0, meta
    p.active = f.get("active", "1") == "1"
    if not pid: db.session.add(p)
    if pid and old != label and cat in CATMAP:  # rename → ikut memperbarui data register
        Register.query.filter(getattr(Register, CATMAP[cat]) == old).update({CATMAP[cat]: label})
    db.session.commit()
    audit.log("UBAH_PARAMETER" if pid else "TAMBAH_PARAMETER", menu="Parameter", detail=f"{cat}: {old + ' → ' if old and old != label else ''}{label}")
    flash("Parameter tersimpan.", "ok"); return redirect(url_for("admin.parameters", cat=cat))

@bp.route("/parameter/<int:pid>/<act>", methods=["POST"])
@perm_required("param")
def parameter_act(pid, act):
    p = db.get_or_404(Parameter, pid); cat = p.category
    if act == "toggle": p.active = not p.active
    elif act == "delete": db.session.delete(p)
    else: abort(404)
    db.session.commit(); audit.log(f"{act.upper()}_PARAMETER", menu="Parameter", detail=f"{cat}: {p.label}", level="WARN" if act == "delete" else "INFO")
    return redirect(url_for("admin.parameters", cat=cat))

# ---------- Pengguna ----------
@bp.route("/pengguna")
@perm_required("user")
def users():
    edit = db.session.get(User, request.args.get("edit", type=int)) if request.args.get("edit") else None
    users = User.query.order_by(User.username).all()
    # permintaan reset password 7 hari terakhir yang belum ditindaklanjuti
    since = datetime.now() - timedelta(days=7)
    resets = AuditLog.query.filter(AuditLog.action == "RESET_PASSWORD", AuditLog.ts >= since).order_by(AuditLog.ts.desc()).all()
    reqs, seen = [], set()
    for r in AuditLog.query.filter(AuditLog.action == "PERMINTAAN_RESET_PASSWORD", AuditLog.ts >= since).order_by(AuditLog.ts.desc()).all():
        key = (r.username or "").lower()
        if key in seen: continue
        seen.add(key)
        u = next((x for x in users if x.username.lower() == key), None)
        if u and any(x.ts > r.ts and u.username in (x.detail or "") for x in resets): continue
        if u and u.last_login and u.last_login > r.ts: continue  # sudah berhasil login setelah permintaan
        reqs.append((r, u))
    return render_template("users.html", users=users, roles=Role.query.order_by(Role.name).all(), edit=edit, now=datetime.now(), reqs=reqs, units=P("UNIT_KERJA"))

@bp.route("/pengguna/save", methods=["POST"])
@perm_required("user")
def user_save():
    f = request.form; uid = f.get("id", type=int); u = db.session.get(User, uid) if uid else User()
    username = (f.get("username") or "").strip()[:80]
    if not uid:
        if not username or User.query.filter(User.username.ilike(username)).first(): flash("Username kosong atau sudah dipakai.", "error"); return redirect(url_for("admin.users"))
        u.username = username
    u.full_name, u.email = (f.get("full_name") or "")[:150], (f.get("email") or "")[:150]
    u.role_id = f.get("role_id", type=int); u.active = f.get("active") == "1"
    unit = (f.get("unit_kerja") or "").strip()[:150]
    u.unit_kerja = unit if (not unit or Parameter.query.filter_by(category="UNIT_KERJA", label=unit).first()) else ""
    if not uid: u.auth_source = f.get("auth_source") if f.get("auth_source") in ("local", "ldap") else "local"
    pw = f.get("password", "")
    if u.auth_source == "local" and (pw or not uid):
        err = valid_password(pw)
        if err: flash(err, "error"); return redirect(url_for("admin.users", edit=uid))
        u.set_password(pw); u.must_change_pw = True
    if not uid: db.session.add(u)
    db.session.commit(); audit.log("UBAH_USER" if uid else "TAMBAH_USER", menu="Pengguna", detail=f"{u.username} ({u.auth_source}) role={u.role.name if u.role else '-'} divisi={u.unit_kerja or '-'} aktif={u.active}")
    role = db.session.get(Role, u.role_id) if u.role_id else None
    if role and "all_divisions" not in (role.permissions or []) and not u.unit_kerja:
        flash(f"Pengguna tersimpan, tetapi divisi belum diisi: {u.username} tidak akan melihat data register apa pun sampai divisinya diatur.", "error")
    else: flash("Pengguna tersimpan.", "ok")
    return redirect(url_for("admin.users"))

@bp.route("/pengguna/<int:uid>/buka-kunci", methods=["POST"])
@perm_required("user")
def user_unlock(uid):
    u = db.get_or_404(User, uid); u.locked_until, u.failed_login = None, 0; db.session.commit()
    audit.log("BUKA_KUNCI_USER", menu="Pengguna", detail=u.username); return redirect(url_for("admin.users"))

@bp.route("/pengguna/<int:uid>/reset", methods=["POST"])
@perm_required("user")
def user_reset(uid):
    """Password sementara acak, tampil sekali. Pengguna wajib menggantinya saat login."""
    import secrets
    u = db.get_or_404(User, uid)
    if u.auth_source != "local":
        flash("Akun LDAP: password diatur di direktori perusahaan, bukan di aplikasi.", "error"); return redirect(url_for("admin.users"))
    pw = secrets.token_urlsafe(9) + "aA1!"
    u.set_password(pw); u.must_change_pw = True; u.failed_login = 0; u.locked_until = None
    db.session.commit()
    audit.log("RESET_PASSWORD", menu="Pengguna", detail=f"{u.username} (password sementara dibuat oleh admin)", level="WARN")
    flash(f"Password sementara untuk {u.username}: {pw}  (tampil sekali; sampaikan lewat saluran aman. Wajib diganti saat login.)", "ok")
    return redirect(url_for("admin.users"))

@bp.route("/pengguna/<int:uid>/hapus", methods=["POST"])
@perm_required("user")
def user_delete(uid):
    """Hapus akun yang NONAKTIF. Jejak audit tetap ada (audit menyimpan username, bukan relasi)."""
    from flask_login import current_user
    u = db.get_or_404(User, uid)
    if u.id == current_user.id:
        flash("Tidak dapat menghapus akun yang sedang dipakai.", "error"); return redirect(url_for("admin.users"))
    if u.active:
        flash("Nonaktifkan akun terlebih dahulu (menu Ubah > Status Nonaktif), baru dapat dihapus.", "error"); return redirect(url_for("admin.users"))
    name, src = u.username, u.auth_source
    db.session.delete(u); db.session.commit()
    audit.log("HAPUS_USER", menu="Pengguna", detail=f"{name} ({src}) dihapus", level="WARN")
    flash(f"Pengguna {name} dihapus. Riwayat auditnya tetap tersimpan.", "ok")
    return redirect(url_for("admin.users"))

# ---------- Hak akses ----------
@bp.route("/hak-akses")
@perm_required("role")
def roles():
    edit = db.session.get(Role, request.args.get("edit", type=int)) if request.args.get("edit") else None
    return render_template("roles.html", roles=Role.query.order_by(Role.name).all(), edit=edit, PERMS=PERMS)

@bp.route("/hak-akses/save", methods=["POST"])
@perm_required("role")
def role_save():
    f = request.form; rid = f.get("id", type=int); r = db.session.get(Role, rid) if rid else Role()
    name = (f.get("name") or "").strip()[:80]
    if not name: flash("Nama role wajib diisi.", "error"); return redirect(url_for("admin.roles"))
    if Role.query.filter(Role.name == name, Role.id != (rid or 0)).first(): flash("Nama role sudah ada.", "error"); return redirect(url_for("admin.roles"))
    r.name, r.description = name, (f.get("description") or "")[:255]; r.permissions = [p for p in f.getlist("perms") if p in PERMS]
    if not rid: db.session.add(r)
    db.session.commit(); audit.log("UBAH_ROLE" if rid else "TAMBAH_ROLE", menu="Hak akses", detail=f"{r.name}: {', '.join(r.permissions)}", level="WARN")
    flash("Role tersimpan.", "ok"); return redirect(url_for("admin.roles"))

@bp.route("/hak-akses/<int:rid>/hapus", methods=["POST"])
@perm_required("role")
def role_delete(rid):
    r = db.get_or_404(Role, rid)
    if r.users: flash("Role masih dipakai pengguna.", "error")
    else: db.session.delete(r); db.session.commit(); audit.log("HAPUS_ROLE", menu="Hak akses", detail=r.name, level="WARN")
    return redirect(url_for("admin.roles"))

# ---------- Audit log ----------
def audit_query(args, cat=None):
    q = AuditLog.query
    cat = cat or args.get("kategori")
    if cat: q = q.filter(AuditLog.category == cat)
    if args.get("user"): q = q.filter(AuditLog.username.ilike(f"%{args['user']}%"))
    if args.get("level"): q = q.filter(AuditLog.level == args["level"])
    if args.get("q"):
        like = f"%{args['q']}%"; q = q.filter(or_(AuditLog.action.ilike(like), AuditLog.detail.ilike(like), AuditLog.menu.ilike(like), AuditLog.ip.ilike(like)))
    d1, d2 = parse_date(args.get("dari")), parse_date(args.get("sampai"))
    if d1: q = q.filter(AuditLog.ts >= datetime.combine(d1, datetime.min.time()))
    if d2: q = q.filter(AuditLog.ts < datetime.combine(d2 + timedelta(days=1), datetime.min.time()))
    return q.order_by(AuditLog.id.desc())

@bp.route("/audit")
@perm_required("audit")
def audit_view():
    pg = audit_query(request.args).paginate(page=request.args.get("page", 1, type=int), per_page=25, error_out=False)
    since = datetime.now() - timedelta(hours=24)
    stats = {"sec24": AuditLog.query.filter(AuditLog.category == "SECURITY", AuditLog.ts >= since).count(),
             "high24": AuditLog.query.filter(AuditLog.level == "HIGH", AuditLog.ts >= since).count(),
             "login_gagal": AuditLog.query.filter(AuditLog.action == "LOGIN_GAGAL", AuditLog.ts >= since).count()}
    return render_template("audit.html", pg=pg, stats=stats)
