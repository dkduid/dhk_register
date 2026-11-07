import csv, io, re
from datetime import date, datetime
from dateutil import parser as dparser
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from sqlalchemy import or_
from .models import db, Register, Parameter

COLS = [("tanggal_permintaan", "Tanggal Permintaan", "date"), ("unit_kerja", "Unit Kerja", None), ("pic", "PIC", None),
        ("dokumen_hukum", "Dokumen Hukum", None), ("klasifikasi", "Klasifikasi", None), ("pihak_ketiga", "Pihak Ketiga", None),
        ("tujuan", "Tujuan", None), ("media", "Media", None), ("watermark", "Watermark (Y/T)", "bool"),
        ("isi_watermark", "Isi Watermark", None), ("password", "Password (Y/T)", "bool"),
        ("cara_kirim_password", "Cara Kirim Password", None), ("data_pribadi", "Data Pribadi (Y/T)", "bool"),
        ("redaksi", "Redaksi/Masking (Y/T)", "bool"), ("nda", "NDA (Y/T)", "bool"),
        ("tanggal_pengiriman", "Tanggal Pengiriman", "date"), ("pic_dhk", "PIC DHK", None), ("keterangan", "Keterangan", None)]
CATMAP = {"KLASIFIKASI": "klasifikasi", "UNIT_KERJA": "unit_kerja", "MEDIA": "media",
          "CARA_KIRIM_PASSWORD": "cara_kirim_password", "TUJUAN": "tujuan"}
CAT_LABEL = {"KLASIFIKASI": "Klasifikasi informasi", "UNIT_KERJA": "Unit kerja", "MEDIA": "Media pengiriman",
             "CARA_KIRIM_PASSWORD": "Cara kirim password", "TUJUAN": "Tujuan distribusi"}

def P(cat): return Parameter.query.filter_by(category=cat, active=True).order_by(Parameter.sort_order, Parameter.label).all()
def klas_map(): return {p.label: (p.meta or {}) for p in Parameter.query.filter_by(category="KLASIFIKASI")}

def parse_bool(v):
    return str(v).strip().lower() in ("y", "ya", "yes", "1", "true", "✓", "v", "x")

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%y")

def parse_date(v):
    """ISO (yyyy-mm-dd, dari <input type=date>) dan dd/mm/yyyy (template Excel/CSV) dibaca dengan format eksplisit.
    JANGAN memakai dateutil dayfirst untuk ISO: '2026-04-12' akan terbaca 4 Desember."""
    if v in (None, ""): return None
    if isinstance(v, datetime): return v.date()
    if isinstance(v, date): return v
    s = str(v).strip().replace("T", " ").split(" ")[0]
    for f in _DATE_FORMATS:
        try: return datetime.strptime(s, f).date()
        except ValueError: pass
    try: return dparser.parse(str(v).strip(), dayfirst=True).date()
    except Exception: return None

def yt(b): return "Y" if b else "T"

def compliance(r, kmap):
    out, m = [], kmap.get(r.klasifikasi) or {}
    if m.get("req_wm") and not r.watermark: out.append(f"Watermark wajib untuk klasifikasi {r.klasifikasi}")
    if m.get("req_pw") and not r.password: out.append(f"Password wajib untuk klasifikasi {r.klasifikasi}")
    if m.get("req_nda") and not r.nda: out.append(f"NDA wajib untuk klasifikasi {r.klasifikasi}")
    if r.data_pribadi and not (r.redaksi or r.nda): out.append("Memuat data pribadi tanpa redaksi/masking maupun NDA")
    if r.watermark and not r.isi_watermark: out.append("Isi watermark belum diisi")
    if r.password and not r.cara_kirim_password: out.append("Cara kirim password belum diisi")
    return out

def reg_query(args):
    q, s = Register.query, (args.get("q") or "").strip()
    if s:
        like = f"%{s}%"
        q = q.filter(or_(*[getattr(Register, c).ilike(like) for c in
                           ("unit_kerja", "pic", "dokumen_hukum", "pihak_ketiga", "tujuan", "pic_dhk", "keterangan")]))
    for f in ("klasifikasi", "unit_kerja"):
        if args.get(f): q = q.filter(getattr(Register, f) == args[f])
    for f in ("nda", "data_pribadi", "watermark", "password"):
        if args.get(f) in ("Y", "T"): q = q.filter(getattr(Register, f) == (args[f] == "Y"))
    d1, d2 = parse_date(args.get("dari")), parse_date(args.get("sampai"))
    if d1: q = q.filter(Register.tanggal_permintaan >= d1)
    if d2: q = q.filter(Register.tanggal_permintaan <= d2)
    return q.order_by(Register.tanggal_permintaan.desc(), Register.id.desc())

def fill(r, form):
    for c, _, t in COLS:
        v = (form.get(c) or "").strip()
        if t == "bool": setattr(r, c, v == "Y")
        elif t == "date": setattr(r, c, parse_date(v))
        else: setattr(r, c, v[:500])

def display(r, c, t):
    v = getattr(r, c)
    return yt(v) if t == "bool" else (v.strftime("%d/%m/%Y") if v else "") if t == "date" else (v or "")

def register_table(regs):
    kmap = klas_map()
    headers = ["No"] + [l for _, l, _ in COLS] + ["Kepatuhan"]
    rows = []
    for r in regs:
        iss = compliance(r, kmap)
        rows.append([r.id] + [display(r, c, t) for c, _, t in COLS] + ["Sesuai" if not iss else "; ".join(iss)])
    return headers, rows

# ---------- Import / template ----------
def _norm(h): return re.sub(r"[^a-z]", "", str(h or "").lower())
HEAD = {}
for _c, _l, _t in COLS:
    HEAD[_norm(_l)] = _c; HEAD[_norm(_l).removesuffix("yt")] = _c

def make_template():
    wb = Workbook(); ws = wb.active; ws.title = "Register"
    heads = [l for _, l, _ in COLS]
    ws.append(heads)
    for i, h in enumerate(heads, 1):
        c = ws.cell(1, i); c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F3A5F")
        c.alignment = Alignment(wrap_text=True, vertical="center"); ws.column_dimensions[get_column_letter(i)].width = 22
    ws.row_dimensions[1].height = 32; ws.freeze_panes = "A2"
    def dv(formula, field):
        idx = [c for c, _, _ in COLS].index(field) + 1; col = get_column_letter(idx)
        v = DataValidation(type="list", formula1=formula, allow_blank=True); ws.add_data_validation(v); v.add(f"{col}2:{col}2000")
    for f in ("watermark", "password", "data_pribadi", "redaksi", "nda"): dv('"Y,T"', f)
    ref = wb.create_sheet("Referensi"); n = 0
    for j, (cat, field) in enumerate(CATMAP.items(), 1):
        ref.cell(1, j, CAT_LABEL[cat]).font = Font(bold=True)
        items = [p.label for p in P(cat)]
        for i, it in enumerate(items, 2): ref.cell(i, j, it)
        if items and cat in ("KLASIFIKASI", "UNIT_KERJA", "MEDIA", "CARA_KIRIM_PASSWORD", "TUJUAN"):
            L = get_column_letter(j); dv(f"=Referensi!${L}$2:${L}${len(items) + 1}", field)
        ref.column_dimensions[get_column_letter(j)].width = 28
    g = wb.create_sheet("Panduan")
    for line in ["Panduan pengisian", "Kolom Y/T: isi Y (ya) atau T (tidak).",
                 "Watermark: apakah dokumen diberi watermark. Isi Watermark contoh: Confidential - PT ABC - Due Diligence.",
                 "Password: apakah dokumen dilindungi password. Cara Kirim Password: telepon, WhatsApp, email terpisah, atau media lain.",
                 "Data Pribadi: Y bila dokumen memuat data pribadi. Redaksi/Masking: Y bila sebagian informasi disamarkan.",
                 "NDA: status Non-Disclosure Agreement dengan pihak ketiga.",
                 "Tanggal: format dd/mm/yyyy. Kolom wajib: Dokumen Hukum dan Pihak Ketiga.",
                 "Klasifikasi, Unit Kerja, Media dan lainnya mengacu pada sheet Referensi (dapat diubah admin di menu Parameter)."]:
        g.append([line])
    g["A1"].font = Font(bold=True, size=13); g.column_dimensions["A"].width = 120
    bio = io.BytesIO(); wb.save(bio); return bio.getvalue()

def _read_rows(name, data):
    if name.lower().endswith((".xlsx", ".xlsm")):
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    txt = data.decode("utf-8-sig", "ignore") if True else ""
    try: dialect = csv.Sniffer().sniff(txt[:4000], delimiters=",;\t")
    except Exception: dialect = csv.excel
    return list(csv.reader(io.StringIO(txt), dialect))

def import_file(name, data, user, max_rows=5000):
    rows = _read_rows(name, data)
    hi, mapping = None, {}
    for i, row in enumerate(rows[:15]):
        m = {j: HEAD.get(_norm(h)) or HEAD.get(_norm(h).removesuffix("yt")) for j, h in enumerate(row) if h}
        m = {j: f for j, f in m.items() if f}
        if len(m) >= 3: hi, mapping = i, m; break
    if hi is None: return 0, ["Header kolom tidak dikenali. Gunakan template resmi."]
    types = {c: t for c, _, t in COLS}; ok, errs = 0, []
    for n, row in enumerate(rows[hi + 1: hi + 1 + max_rows], start=hi + 2):
        if not any(row): continue
        vals = {f: row[j] if j < len(row) else None for j, f in mapping.items()}
        if not str(vals.get("dokumen_hukum") or "").strip() or not str(vals.get("pihak_ketiga") or "").strip():
            errs.append(f"Baris {n}: Dokumen Hukum dan Pihak Ketiga wajib diisi"); continue
        r = Register(created_by=user.username, updated_by=user.username)
        for f, v in vals.items():
            t = types[f]
            setattr(r, f, parse_bool(v) if t == "bool" else parse_date(v) if t == "date" else str(v if v is not None else "").strip()[:500])
        db.session.add(r); ok += 1
    db.session.commit(); return ok, errs

# ---------- Export ----------
def _safe(v):
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v

def export(fmt, title, headers, rows, meta):
    if fmt == "csv":
        s = io.StringIO(); w = csv.writer(s)
        w.writerow([title]); [w.writerow([m]) for m in meta]; w.writerow([]); w.writerow(headers)
        for r in rows: w.writerow([_safe(c) for c in r])
        return s.getvalue().encode("utf-8-sig"), "text/csv", "csv"
    if fmt == "xlsx":
        wb = Workbook(); ws = wb.active; ws.title = "Laporan"[:30]
        ws.append([title]); ws["A1"].font = Font(bold=True, size=14)
        for m in meta: ws.append([m])
        ws.append([]); hr = ws.max_row + 1; ws.append(headers)
        for i in range(1, len(headers) + 1):
            c = ws.cell(hr, i); c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="1F3A5F")
        for r in rows: ws.append([_safe(c) for c in r])
        for i in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(i)].width = min(45, max(12, max([len(str(headers[i - 1]))] + [len(str(r[i - 1])) for r in rows[:200]]) + 2))
        ws.freeze_panes = ws.cell(hr + 1, 1)
        b = io.BytesIO(); wb.save(b)
        return b.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    if fmt == "pdf":
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A3, A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
        wide = len(headers) > 10; fs = 5.8 if wide else 7.5
        st = getSampleStyleSheet(); cell = ParagraphStyle("c", parent=st["Normal"], fontSize=fs, leading=fs + 1.6)
        hd = ParagraphStyle("h", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
        esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        data = [[Paragraph(esc(h), hd) for h in headers]] + [[Paragraph(esc(c), cell) for c in r] for r in rows]
        b = io.BytesIO(); doc = SimpleDocTemplate(b, pagesize=landscape(A3 if wide else A4), leftMargin=20, rightMargin=20, topMargin=24, bottomMargin=24)
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F3A5F")), ("GRID", (0, 0), (-1, -1), .25, colors.grey),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F6FA")])]))
        doc.build([Paragraph(esc(title), st["Title"])] + [Paragraph(esc(m), st["Normal"]) for m in meta] + [Spacer(1, 8), t])
        return b.getvalue(), "application/pdf", "pdf"
    if fmt == "docx":
        from docx import Document
        from docx.enum.section import WD_ORIENT
        from docx.shared import Pt
        d = Document(); s = d.sections[0]; s.orientation = WD_ORIENT.LANDSCAPE; s.page_width, s.page_height = s.page_height, s.page_width
        d.add_heading(title, 1)
        for m in meta: d.add_paragraph(m)
        t = d.add_table(rows=1, cols=len(headers)); t.style = "Light Grid Accent 1"
        for i, h in enumerate(headers): t.rows[0].cells[i].text = h
        for r in rows:
            cells = t.add_row().cells
            for i, c in enumerate(r): cells[i].text = str(c)
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    for run in p.runs: run.font.size = Pt(6.5)
        b = io.BytesIO(); d.save(b)
        return b.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"
    raise ValueError("Format tidak didukung")
