import re
from datetime import datetime, timedelta
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_user, logout_user, login_required, current_user
from sqlalchemy import func
from . import audit
from .models import db, User, Role, AuditLog

bp = Blueprint("auth", __name__)

def perm_required(perm):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if not current_user.can(perm):
                audit.log("AKSES_DITOLAK", menu=request.endpoint, detail=f"Butuh hak akses '{perm}'", category="SECURITY", level="WARN",
                          mitre="T1078", tactic="Defense Evasion / Privilege Escalation (Valid Accounts)")
                abort(403)
            return f(*a, **k)
        return login_required(w)
    return deco

def valid_password(pw):
    if len(pw) < 10: return "Password minimal 10 karakter."
    if not (re.search(r"[a-z]", pw) and re.search(r"[A-Z]", pw) and re.search(r"\d", pw) and re.search(r"[^\w\s]", pw)):
        return "Password harus memuat huruf besar, huruf kecil, angka, dan simbol."
    return None

def ldap_bind(username, password):
    c = current_app.config
    try:
        from ldap3 import Server, Connection, NONE
        from ldap3.utils.dn import escape_rdn
        from ldap3.utils.conv import escape_filter_chars
        srv = Server(c["LDAP_SERVER"], port=c["LDAP_PORT"], use_ssl=c["LDAP_SSL"], get_info=NONE, connect_timeout=5)
        conn = Connection(srv, user=c["LDAP_USER_DN"].format(u=escape_rdn(username)), password=password, auto_bind=True, receive_timeout=8)
        info = {"full_name": username, "email": ""}
        try:
            u = escape_filter_chars(username)
            if conn.search(c["LDAP_BASE_DN"], f"(|(sAMAccountName={u})(uid={u}))", attributes=["cn", "mail"]) and conn.entries:
                e = conn.entries[0]; info = {"full_name": str(e.cn) if "cn" in e else username, "email": str(e.mail) if "mail" in e else ""}
        except Exception: pass
        conn.unbind(); return info
    except Exception as e:
        current_app.logger.warning("LDAP bind gagal: %s", e); return None

def authenticate(username, pw):
    cfg = current_app.config
    user = User.query.filter(func.lower(User.username) == username.lower()).first()
    if user and user.locked_until and user.locked_until > datetime.now():
        return None, "Akun terkunci sementara karena terlalu banyak percobaan gagal. Coba lagi nanti atau hubungi admin."
    ok = False
    if user and user.auth_source == "local": ok = user.check_password(pw)
    elif (user is None or user.auth_source == "ldap") and cfg["LDAP_ENABLED"] and pw:
        info = ldap_bind(username, pw)
        if info:
            if user is None:
                if not cfg["LDAP_AUTO_PROVISION"]: return None, "Akun LDAP Anda belum didaftarkan oleh admin."
                role = Role.query.filter_by(name=cfg["LDAP_DEFAULT_ROLE"]).first()
                user = User(username=username, auth_source="ldap", role=role, **info); db.session.add(user); db.session.commit()
            ok = True
    if ok and not user.active: return None, "Akun nonaktif. Hubungi admin."
    if not ok:
        if user:
            user.failed_login = (user.failed_login or 0) + 1
            if user.failed_login >= cfg["MAX_FAILED_LOGIN"]:
                user.locked_until = datetime.now() + timedelta(minutes=cfg["LOCK_MINUTES"]); user.failed_login = 0
            db.session.commit()
        audit.log("LOGIN_GAGAL", menu="Login", detail=f"Username: {username}", category="SECURITY", level="WARN",
                  username=username, mitre="T1110", tactic="Credential Access (Brute Force)")
        since = datetime.now() - timedelta(minutes=10)
        n = AuditLog.query.filter(AuditLog.action == "LOGIN_GAGAL", AuditLog.ip == request.remote_addr, AuditLog.ts >= since).count()
        if n >= 10 and n % 5 == 0:
            audit.log("BRUTE_FORCE_TERDETEKSI", menu="Login", detail=f"{n} login gagal dari {request.remote_addr} dalam 10 menit",
                      category="SECURITY", level="HIGH", username=username, mitre="T1110.001", tactic="Credential Access (Password Guessing)")
        return None, "Username atau password salah."
    user.failed_login = 0; user.locked_until = None; user.last_login = datetime.now(); db.session.commit()
    return user, None

@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated: return redirect(url_for("main.home"))
    if request.method == "POST":
        user, err = authenticate(request.form.get("username", "").strip()[:80], request.form.get("password", ""))
        if user:
            login_user(user); from flask import session; session.permanent = True
            audit.log("LOGIN", menu="Login", detail=f"Login via {user.auth_source.upper()}")
            return redirect(url_for("main.home"))
        flash(err, "error")
    return render_template("login.html")

@bp.route("/logout")
@login_required
def logout():
    audit.log("LOGOUT", menu="Logout"); logout_user(); return redirect(url_for("auth.login"))

@bp.route("/password", methods=["GET", "POST"])
@login_required
def password():
    if request.method == "POST":
        old, new, new2 = (request.form.get(k, "") for k in ("old", "new", "new2"))
        if current_user.auth_source != "local": flash("Akun LDAP: ubah password melalui direktori perusahaan.", "error")
        elif not current_user.check_password(old): flash("Password lama tidak sesuai.", "error")
        elif new != new2: flash("Konfirmasi password tidak sama.", "error")
        elif valid_password(new): flash(valid_password(new), "error")
        else:
            current_user.set_password(new); current_user.must_change_pw = False; db.session.commit()
            audit.log("GANTI_PASSWORD", menu="Ubah password"); flash("Password berhasil diubah.", "ok")
            return redirect(url_for("main.home"))
    return render_template("password.html")


@bp.route("/lupa-password", methods=["GET", "POST"])
def forgot():
    """Permintaan reset password. Tidak membuka rahasia: jawaban selalu sama, apakah akun ada atau tidak.
    Permintaan dicatat di audit log dan muncul di menu Pengguna untuk ditindaklanjuti administrator."""
    if current_user.is_authenticated: return redirect(url_for("auth.password"))
    sent = False
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()[:80]
        sent = True
        if username:
            since = datetime.now() - timedelta(minutes=10)
            recent = AuditLog.query.filter(AuditLog.action == "PERMINTAAN_RESET_PASSWORD", AuditLog.ip == request.remote_addr, AuditLog.ts >= since).count()
            if recent < 5:  # batasi agar log tidak dibanjiri
                u = User.query.filter(func.lower(User.username) == username.lower()).first()
                state = "tidak terdaftar" if not u else ("akun LDAP (reset di direktori perusahaan)" if u.auth_source != "local" else "akun lokal")
                audit.log("PERMINTAAN_RESET_PASSWORD", menu="Lupa password", detail=f"Akun {username}: {state}", level="WARN", username=username)
    return render_template("forgot.html", sent=sent)
