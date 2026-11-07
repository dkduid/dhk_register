from datetime import datetime
from flask import Blueprint, render_template, request, send_file, flash
from flask_login import current_user
import io
from . import audit
from .auth import perm_required
from .services import P, reg_query, register_table, export, parse_date
from .admin import audit_query

bp = Blueprint("reports", __name__)
FMT = {"xlsx": "Excel", "pdf": "PDF", "csv": "CSV", "docx": "Word"}

def build(args):
    jenis = args.get("jenis", "register")
    if jenis == "audit":
        if not current_user.can("audit"): return None
        rows = audit_query(args).limit(50000).all()
        return ("Laporan audit log", ["Waktu", "User", "IP", "Kategori", "Level", "Aksi", "Menu", "Detail", "MITRE ATT&CK"],
                [[r.ts.strftime("%d/%m/%Y %H:%M:%S"), r.username, r.ip or "", r.category, r.level, r.action, r.menu or "", r.detail or "",
                  f"{r.mitre_id or ''} {r.mitre_tactic or ''}".strip()] for r in rows])
    regs = reg_query(args).limit(50000).all(); h, rows = register_table(regs)
    return "Laporan register pendistribusian dokumen hukum", h, rows

def _meta(args):
    m = [f"Periode: {args.get('dari') or 'awal'} s/d {args.get('sampai') or 'sekarang'}"]
    extra = [f"{k}={v}" for k, v in args.items() if k in ("klasifikasi", "unit_kerja", "kategori", "user", "level", "q") and v]
    if extra: m.append("Filter: " + ", ".join(extra))
    m += [f"Dibuat oleh: {current_user.username}", f"Waktu cetak: {datetime.now():%d/%m/%Y %H:%M:%S}"]
    return m

@bp.route("/laporan")
@perm_required("report")
def reports():
    prev = None
    if request.args.get("lihat"):
        b = build(request.args)
        if b:
            title, h, rows = b; prev = (title, h, rows[:100], len(rows))
            audit.log("GENERATE_LAPORAN", menu="Laporan", detail=f"{title} | {len(rows)} baris | {dict(request.args)}")
    return render_template("reports.html", prev=prev, klas=P("KLASIFIKASI"), units=P("UNIT_KERJA"), FMT=FMT)

@bp.route("/laporan/unduh")
@perm_required("report")
def download():
    fmt = request.args.get("format", "xlsx")
    b = build(request.args)
    if not b or fmt not in FMT: return ("Tidak diizinkan / format tidak valid", 400)
    title, h, rows = b; data, mime, ext = export(fmt, title, h, rows, _meta(request.args))
    name = f"{title.split()[1].capitalize()}_{datetime.now():%Y%m%d_%H%M%S}.{ext}"
    audit.log("UNDUH_LAPORAN", menu="Laporan", detail=f"{title} | format={ext.upper()} | {len(rows)} baris | file={name} | filter={dict(request.args)}")
    return send_file(io.BytesIO(data), mimetype=mime, as_attachment=True, download_name=name)
