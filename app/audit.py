import logging
from flask import request, has_request_context, current_app
from flask_login import current_user
from .models import db, AuditLog

def log(action, menu=None, detail="", category="ACTIVITY", level="INFO", mitre=None, tactic=None, username=None):
    """Catat ke audit log. Tidak pernah melempar exception ke pemanggil."""
    try:
        rc = has_request_context()
        u = current_user if (rc and current_user.is_authenticated) else None
        db.session.add(AuditLog(
            user_id=u.id if u else None, username=(u.username if u else username) or "-",
            ip=request.remote_addr if rc else None,
            user_agent=request.headers.get("User-Agent", "")[:250] if rc else None,
            method=request.method if rc else None, path=request.path[:300] if rc else None,
            category=category, level=level, action=action, menu=menu, detail=str(detail)[:4000],
            mitre_id=mitre, mitre_tactic=tactic))
        db.session.commit()
    except Exception:
        try: db.session.rollback()
        except Exception: pass
        # DB tidak tersedia: simpan ke file agar jejak tidak hilang
        try:
            logging.getLogger("dhk.audit_fallback").error("%s | %s | %s | %s | %s | %s", category, level, action, username or "-", menu or "-", str(detail)[:500])
            logging.getLogger("dhk").error("Gagal menulis audit log ke database (aksi=%s); dicatat ke audit_fallback.log", action)
        except Exception: pass
