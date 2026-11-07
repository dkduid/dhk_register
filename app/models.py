from datetime import datetime
from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import deferred
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

PERMS = {
    "dashboard": "Dashboard",
    "register_view": "Melihat register",
    "register_edit": "Menambah / mengubah register",
    "register_delete": "Menghapus register",
    "register_import": "Import template",
    "document_upload": "Upload dokumen",
    "document_download": "Mengunduh dokumen",
    "report": "Reporting",
    "param": "Kelola parameter",
    "user": "Kelola pengguna",
    "role": "Kelola hak akses",
    "audit": "Audit log & peringatan keamanan",
}

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255), default="")
    permissions = db.Column(db.JSON, default=list)
    users = db.relationship("User", back_populates="role")

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(150), default="")
    email = db.Column(db.String(150), default="")
    password_hash = db.Column(db.String(255), default="")
    auth_source = db.Column(db.String(10), default="local")  # local | ldap
    role_id = db.Column(db.Integer, db.ForeignKey("role.id"))
    active = db.Column(db.Boolean, default=True)
    failed_login = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    last_login = db.Column(db.DateTime)
    must_change_pw = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    role = db.relationship("Role", back_populates="users")

    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return bool(self.password_hash) and check_password_hash(self.password_hash, pw)
    @property
    def is_active(self): return bool(self.active)
    def can(self, perm): return bool(self.active and self.role and perm in (self.role.permissions or []))

class Parameter(db.Model):
    __table_args__ = (db.UniqueConstraint("category", "label"),)
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(40), nullable=False, index=True)
    label = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, default="")
    sort_order = db.Column(db.Integer, default=0)
    active = db.Column(db.Boolean, default=True)
    meta = db.Column(db.JSON, default=dict)  # klasifikasi: color, level, req_wm, req_pw, req_nda

class Register(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tanggal_permintaan = db.Column(db.Date, index=True)
    unit_kerja = db.Column(db.String(150), default="")
    pic = db.Column(db.String(150), default="")
    dokumen_hukum = db.Column(db.String(500), default="")
    klasifikasi = db.Column(db.String(150), default="")
    pihak_ketiga = db.Column(db.String(300), default="")
    tujuan = db.Column(db.String(300), default="")
    media = db.Column(db.String(150), default="")
    watermark = db.Column(db.Boolean, default=False)
    isi_watermark = db.Column(db.String(300), default="")
    password = db.Column(db.Boolean, default=False)
    cara_kirim_password = db.Column(db.String(150), default="")
    data_pribadi = db.Column(db.Boolean, default=False)
    redaksi = db.Column(db.Boolean, default=False)
    nda = db.Column(db.Boolean, default=False)
    tanggal_pengiriman = db.Column(db.Date)
    pic_dhk = db.Column(db.String(150), default="")
    keterangan = db.Column(db.Text, default="")
    created_by = db.Column(db.String(80)); updated_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    attachments = db.relationship("Attachment", back_populates="register", cascade="all, delete-orphan")

class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    register_id = db.Column(db.Integer, db.ForeignKey("register.id"), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=False)
    register = db.relationship("Register", back_populates="attachments")
    versions = db.relationship("AttachmentVersion", back_populates="attachment", cascade="all, delete-orphan",
                               order_by="AttachmentVersion.version.desc()")
    @property
    def current(self): return self.versions[0] if self.versions else None

class AttachmentVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    attachment_id = db.Column(db.Integer, db.ForeignKey("attachment.id"), nullable=False, index=True)
    version = db.Column(db.Integer, nullable=False)
    filename = db.Column(db.String(255)); mime = db.Column(db.String(120))
    size = db.Column(db.Integer); sha256 = db.Column(db.String(64))
    scan_status = db.Column(db.String(20)); scan_detail = db.Column(db.Text, default="")
    note = db.Column(db.String(250), default="")
    uploaded_by = db.Column(db.String(80)); uploaded_at = db.Column(db.DateTime, default=datetime.now)
    content = deferred(db.Column(db.LargeBinary))
    attachment = db.relationship("Attachment", back_populates="versions")

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=datetime.now, index=True)
    user_id = db.Column(db.Integer); username = db.Column(db.String(80), index=True)
    ip = db.Column(db.String(64)); user_agent = db.Column(db.String(255))
    method = db.Column(db.String(10)); path = db.Column(db.String(300))
    category = db.Column(db.String(12), index=True)  # ACTIVITY | APPLICATION | SECURITY
    level = db.Column(db.String(8), default="INFO")  # INFO | WARN | HIGH | ERROR
    action = db.Column(db.String(60), index=True); menu = db.Column(db.String(80))
    detail = db.Column(db.Text, default="")
    mitre_id = db.Column(db.String(16)); mitre_tactic = db.Column(db.String(60))


class AppInfo(db.Model):
    """Metadata aplikasi/skema (versi skema, waktu instalasi)."""
    key = db.Column(db.String(60), primary_key=True)
    value = db.Column(db.String(255))
