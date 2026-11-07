"""Pemeriksaan kesehatan dari luar proses (dipakai installer & diagnose)."""
import json
import ssl
import urllib.request


def check(Config, timeout=8):
    scheme = "https" if Config.HTTPS else "http"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(f"{scheme}://127.0.0.1:{Config.PORT}/health", timeout=timeout, context=ctx) as r:
            body = json.loads(r.read().decode("utf-8", "ignore") or "{}")
            return r.status == 200 and body.get("status") == "ok", f"HTTP {r.status} {body}"
    except Exception as e:  # noqa: BLE001
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")[:100]  # HTTPError 503
        except Exception:
            pass
        return False, f"{type(e).__name__}: {str(e)[:120]} {body}".strip()
