"""Deteksi serangan web (dipetakan ke MITRE ATT&CK) + pemindai file upload."""
import io, re, socket, struct, zipfile
from urllib.parse import unquote_plus
from flask import request, current_app, abort, g
from . import audit

def _r(name, rx, tid, tactic, sev):
    return dict(name=name, rx=re.compile(rx), id=tid, tactic=tactic, sev=sev)

RULES = [
    _r("SQL Injection", r"(?i)(\bunion\b\s+(all\s+)?select\b|\bselect\b.{1,80}\bfrom\b.{1,80}\bwhere\b|'\s*or\s+'?\d+'?\s*=\s*'?\d+|;\s*(drop|delete|truncate|insert|update)\s+\w+|\bsleep\s*\(\s*\d|\bwaitfor\s+delay\b|information_schema|pg_sleep\s*\()",
       "T1190", "Initial Access (Exploit Public-Facing Application)", "HIGH"),
    _r("Cross-Site Scripting", r"(?i)(<\s*script|javascript\s*:|\bon(error|load|click|mouseover|focus)\s*=|<\s*iframe|<\s*svg[^>]*\bon\w+\s*=)",
       "T1059.007", "Execution (JavaScript)", "HIGH"),
    _r("Path Traversal / LFI", r"(?i)(\.\./|\.\.\\|%2e%2e|/etc/passwd|boot\.ini|win\.ini|c:\\windows)",
       "T1190", "Initial Access (Exploit Public-Facing Application)", "HIGH"),
    _r("Command Injection", r"(?i)((;|\|\||&&|\|)\s*(cat|ls|wget|curl|powershell|cmd(\.exe)?|bash|nc|whoami)\b|\$\(\s*\w+)",
       "T1059", "Execution (Command and Scripting Interpreter)", "HIGH"),
    _r("LDAP Injection", r"(?i)(\)\s*\(\s*(\||&|!)|\*\)\(|\)\(\s*(uid|cn|objectclass)\s*=)",
       "T1190", "Initial Access (Exploit Public-Facing Application)", "HIGH"),
    _r("Template Injection", r"(\{\{.{1,100}\}\}|\{%.{1,100}%\}|\$\{.{1,100}\})",
       "T1190", "Initial Access (Exploit Public-Facing Application)", "WARN"),
    _r("Null Byte", r"(%00|\x00)", "T1027", "Defense Evasion (Obfuscated Files or Information)", "WARN"),
]
SCANNER_UA = re.compile(r"(?i)(sqlmap|nikto|nmap|masscan|dirbuster|gobuster|acunetix|nessus|burpsuite|zgrab|wpscan|hydra|nuclei)")

def _decode(v):
    s = str(v)
    for _ in range(3):
        n = unquote_plus(s)
        if n == s: break
        s = n
    return s

def inspect_request():
    """Dipanggil before_request: periksa path, query, form, JSON, dan User-Agent."""
    if request.endpoint == "static": return
    items = [("path", request.path), ("query", request.query_string.decode("utf-8", "ignore"))]
    for k, v in request.form.items():
        if "password" not in k and k != "csrf_token": items.append((k, v))
    if request.is_json:
        j = request.get_json(silent=True)
        if isinstance(j, dict): items += [(k, v) for k, v in j.items() if isinstance(v, str)]
    seen, high = set(), False
    for field, val in items:
        s = _decode(val)
        for rule in RULES:
            if rule["name"] in seen or not rule["rx"].search(s): continue
            seen.add(rule["name"]); high |= rule["sev"] == "HIGH"
            audit.log("SERANGAN_TERDETEKSI", menu=request.endpoint, category="SECURITY", level=rule["sev"],
                      detail=f"{rule['name']} pada '{field}': {s[:150]!r}", mitre=rule["id"], tactic=rule["tactic"])
    ua = request.headers.get("User-Agent", "")
    if SCANNER_UA.search(ua):
        high = True
        audit.log("SCANNER_TERDETEKSI", menu=request.endpoint, category="SECURITY", level="HIGH",
                  detail=f"User-Agent alat pemindai: {ua[:120]}", mitre="T1595", tactic="Reconnaissance (Active Scanning)")
    if high and current_app.config["BLOCK_ON_ATTACK"]:
        g.blocked = True
        abort(403)

# ---------------- Pemindai file upload ----------------
ALLOWED = {"pdf": b"%PDF", "docx": b"PK\x03\x04", "xlsx": b"PK\x03\x04", "doc": b"\xd0\xcf\x11\xe0",
           "xls": b"\xd0\xcf\x11\xe0", "jpg": b"\xff\xd8\xff", "jpeg": b"\xff\xd8\xff", "png": b"\x89PNG\r\n\x1a\n", "csv": None}
EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
BAD_INNER = (".exe", ".dll", ".js", ".vbs", ".bat", ".ps1", ".scr", ".jar", ".com", ".cmd")

def _clamd(data):
    cfg = current_app.config
    with socket.create_connection((cfg["CLAMAV_HOST"], cfg["CLAMAV_PORT"]), timeout=15) as s:
        s.sendall(b"zINSTREAM\0")
        for i in range(0, len(data), 8192):
            c = data[i:i + 8192]; s.sendall(struct.pack("!I", len(c)) + c)
        s.sendall(struct.pack("!I", 0))
        return s.recv(4096).decode("utf-8", "ignore").strip("\0\n ")

def scan_file(filename, data):
    """Return dict(status=CLEAN|SUSPICIOUS|INFECTED|REJECTED, detail, mitre, tactic)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    f, status, mitre, tactic = [], "CLEAN", None, None
    def bad(st, msg, m, t):
        nonlocal status, mitre, tactic
        rank = ["CLEAN", "REJECTED", "SUSPICIOUS", "INFECTED"]
        f.append(msg)
        if rank.index(st) > rank.index(status): status, mitre, tactic = st, m, t
    if ext not in ALLOWED:
        return dict(status="REJECTED", detail=f"Ekstensi .{ext or '?'} tidak diizinkan", mitre="T1105", tactic="Command and Control (Ingress Tool Transfer)")
    if not data:
        return dict(status="REJECTED", detail="File kosong", mitre=None, tactic=None)
    sig = ALLOWED[ext]
    if sig and not data.startswith(sig):
        bad("REJECTED", "Isi file tidak sesuai ekstensi (magic bytes)", "T1036", "Defense Evasion (Masquerading)")
    if EICAR in data:
        bad("INFECTED", "Signature EICAR / malware uji terdeteksi", "T1204.002", "Execution (User Execution: Malicious File)")
    if ext in ("docx", "xlsx") and data.startswith(b"PK"):
        try:
            z = zipfile.ZipFile(io.BytesIO(data)); infos = z.infolist()
            if sum(i.file_size for i in infos) > 300 * 1024 * 1024 or (len(data) and sum(i.file_size for i in infos) / len(data) > 150):
                bad("SUSPICIOUS", "Rasio kompresi tidak wajar (indikasi zip bomb)", "T1499", "Impact (Endpoint DoS)")
            for i in infos:
                n = i.filename.lower()
                if n.endswith("vbaproject.bin"): bad("SUSPICIOUS", "Mengandung makro VBA", "T1204.002", "Execution (Malicious File)")
                if n.endswith(BAD_INNER): bad("SUSPICIOUS", f"Berisi file eksekutabel/skrip: {i.filename}", "T1204.002", "Execution (Malicious File)")
                if n.endswith(".rels") and b"attachedTemplate" in z.read(i) and b"External" in z.read(i):
                    bad("SUSPICIOUS", "Template eksternal (template injection)", "T1221", "Defense Evasion (Template Injection)")
        except zipfile.BadZipFile:
            bad("REJECTED", "Struktur dokumen Office rusak", "T1036", "Defense Evasion (Masquerading)")
    if ext in ("doc", "xls") and (b"_VBA_PROJECT" in data or b"VBA" in data[:2_000_000] and b"Macros" in data[:2_000_000]):
        bad("SUSPICIOUS", "Mengandung makro VBA (format OLE)", "T1204.002", "Execution (Malicious File)")
    if ext == "pdf" and re.search(rb"/(JavaScript|JS|Launch|RichMedia)\b", data):
        bad("SUSPICIOUS", "PDF memuat JavaScript / Launch action", "T1204.002", "Execution (Malicious File)")
    if ext in ("jpg", "jpeg", "png") and re.search(rb"(?i)<\?php|<script|<%@", data):
        bad("SUSPICIOUS", "Kode skrip tertanam dalam gambar (polyglot / webshell)", "T1505.003", "Persistence (Web Shell)")
    if ext == "csv":
        if b"\x00" in data: bad("REJECTED", "CSV mengandung byte NULL", "T1036", "Defense Evasion (Masquerading)")
        txt = data.decode("utf-8", "ignore")
        if re.search(r"(?im)(^|[,;\t\"])\s*[=+@-]\s*(cmd|powershell|hyperlink|dde|\w+\|)", txt):
            bad("SUSPICIOUS", "Formula berbahaya (CSV injection)", "T1204.002", "Execution (Malicious File)")
    if current_app.config["CLAMAV_ENABLED"]:
        try:
            r = _clamd(data)
            if r.endswith("FOUND"): bad("INFECTED", f"ClamAV: {r}", "T1204.002", "Execution (Malicious File)")
            else: f.append("ClamAV: bersih")
        except Exception as e:
            if current_app.config["CLAMAV_REQUIRED"]: bad("REJECTED", f"ClamAV tidak dapat dihubungi: {e}", None, None)
            else: f.append("ClamAV tidak tersedia; hanya pemindaian internal")
    return dict(status=status, detail="; ".join(f) or "Lolos pemeriksaan tipe, signature, makro, dan konten aktif", mitre=mitre, tactic=tactic)
