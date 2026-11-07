# -*- mode: python -*-
# Build:  pyinstaller dhk_register.spec --noconfirm --clean    (dijalankan oleh build_exe.bat)
from PyInstaller.utils.hooks import collect_submodules
hidden = (collect_submodules("cheroot") + collect_submodules("ldap3") + collect_submodules("psycopg2")
          + ["sqlalchemy.dialects.postgresql", "sqlalchemy.dialects.postgresql.psycopg2", "cryptography.hazmat.backends.openssl",
             "docx", "openpyxl", "reportlab.pdfbase._fontdata", "app.errors", "app.dbsetup", "app.healthcheck"])
a = Analysis(["run.py"], pathex=["."], datas=[("app/templates", "app/templates"), ("app/static", "app/static"), (".env.example", ".")],
             hiddenimports=hidden, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DHKRegister", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="DHKRegister")
