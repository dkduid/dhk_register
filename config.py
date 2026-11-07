import os, sys
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
load_dotenv(BASE / ".env")

def _b(k, d="false"):
    return os.getenv(k, d).strip().lower() in ("1", "true", "yes", "y")

class Config:
    BASE_DIR = BASE
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-ganti-di-produksi")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@localhost:5432/dhk_register")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = ({"pool_pre_ping": True, "connect_args": {"connect_timeout": 5}}
                                 if os.getenv("DATABASE_URL", "postgresql").startswith("postgresql") else {})
    PG_ADMIN_USER = os.getenv("PG_ADMIN_USER", "postgres")
    PG_ADMIN_PASSWORD = os.getenv("PG_ADMIN_PASSWORD", "")   # hanya untuk --init-db; jangan disimpan permanen
    PG_ADMIN_DB = os.getenv("PG_ADMIN_DB", "postgres")
    AUTO_CREATE_DB = _b("AUTO_CREATE_DB", "true")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8443"))
    HTTPS = _b("HTTPS", "true")
    SSL_CERT = os.getenv("SSL_CERT", "")
    SSL_KEY = os.getenv("SSL_KEY", "")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _b("HTTPS", "true")
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.getenv("SESSION_MINUTES", "30")))
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
    LDAP_ENABLED = _b("LDAP_ENABLED")
    LDAP_SERVER = os.getenv("LDAP_SERVER", "")
    LDAP_PORT = int(os.getenv("LDAP_PORT", "389"))
    LDAP_SSL = _b("LDAP_SSL")
    LDAP_USER_DN = os.getenv("LDAP_USER_DN", "{u}")
    LDAP_BASE_DN = os.getenv("LDAP_BASE_DN", "")
    LDAP_AUTO_PROVISION = _b("LDAP_AUTO_PROVISION")
    LDAP_DEFAULT_ROLE = os.getenv("LDAP_DEFAULT_ROLE", "Viewer")
    CLAMAV_ENABLED = _b("CLAMAV_ENABLED")
    CLAMAV_HOST = os.getenv("CLAMAV_HOST", "127.0.0.1")
    CLAMAV_PORT = int(os.getenv("CLAMAV_PORT", "3310"))
    CLAMAV_REQUIRED = _b("CLAMAV_REQUIRED")
    BLOCK_ON_ATTACK = _b("BLOCK_ON_ATTACK", "true")
    MAX_FAILED_LOGIN = int(os.getenv("MAX_FAILED_LOGIN", "5"))
    LOCK_MINUTES = int(os.getenv("LOCK_MINUTES", "15"))
