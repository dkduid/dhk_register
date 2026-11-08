# Register DHK — Pendistribusian Dokumen Hukum kepada Pihak Ketiga

Aplikasi web (Python/Flask + PostgreSQL) untuk mencatat, mengklasifikasi, dan mengaudit pengiriman dokumen hukum ke pihak ketiga.

## Menjalankan (pengembangan)
1. Buat database: `CREATE DATABASE dhk_register;` dan user PostgreSQL.
2. `copy .env.example .env` lalu isi `DATABASE_URL`, `SECRET_KEY`.
3. `pip install -r requirements.txt`
4. `python run.py` → buka https://localhost:8443 (sertifikat self-signed dibuat otomatis; ganti dengan sertifikat perusahaan via `SSL_CERT`/`SSL_KEY`).
   Tabel dan data awal dibuat otomatis. Password admin awal ditampilkan di console (wajib diganti saat login pertama).

## Membuat paket instalasi untuk server/laptop lain (Windows)
`build_exe.bat` -> menguji, membuat `DHKRegister.exe`, menyertakan penginstal PostgreSQL (folder `installers\`), skrip, dan dokumentasi -> `DHKRegister_Paket.zip`.
Di mesin tujuan: ekstrak, klik kanan `Install.bat` > Run as administrator. Skrip memasang PostgreSQL bila belum ada, membuat database dan 8 tabel, `.env`, firewall, dan auto-start, lalu memeriksa kesehatan.
Bila gagal: baca `logs\STARTUP_ERROR.txt`, `logs\install_error.log`, atau jalankan `Diagnose.bat`.
Migrasi server: `pg_dump` -> `pg_restore` (lihat docs\04_Dokumentasi_Konfigurasi.docx).

## Dokumentasi (folder docs)
01 Pembuatan | 02 Manual Pengguna | 03 Manual Admin | 04 Konfigurasi | 05 Instalasi | 06 SDLC | 07 Coding | 08 Arsitektur | 09 Kamus Data

## Fitur → lokasi
| Kebutuhan | Menu / berkas |
|---|---|
| Parameter dapat dikelola (klasifikasi, unit kerja, media, cara kirim password, tujuan, kategori baru) | Administrasi → Parameter |
| Klasifikasi Sangat Rahasia/Rahasia/Terbatas/Publik + kontrol wajib (watermark/password/NDA) | Parameter → Klasifikasi informasi |
| Isi manual atau import template Excel/CSV | Tambah register · Import template |
| Upload PDF/Word/JPEG/PNG/Excel/CSV, versi terbaru + riwayat | Detail register |
| Pindai sebelum simpan (tipe, magic bytes, makro, JS di PDF, polyglot, zip bomb, EICAR, ClamAV opsional) | `app/security.py` |
| Grafik & tabel | Dashboard · Register |
| Hak akses (role × menu) | Administrasi → Hak akses, Pengguna |
| Audit log (aktivitas, keamanan, application log) | Administrasi → Audit log |
| Laporan berfilter periode, unduh Excel/PDF/CSV/Word, tercatat di audit log | Laporan |
| Login admin-terdaftar atau LDAP | `.env` → `LDAP_*` |
| Deteksi serangan ↔ MITRE ATT&CK | `app/security.py`, `app/auth.py` |

## Pemetaan MITRE ATT&CK
| Deteksi | Teknik |
|---|---|
| SQL injection, path traversal, LDAP injection, template injection | T1190 Exploit Public-Facing Application |
| XSS | T1059.007 JavaScript |
| Command injection | T1059 Command and Scripting Interpreter |
| Login gagal berulang / brute force | T1110, T1110.001 |
| Akses menu tanpa hak | T1078 Valid Accounts |
| Alat pemindai (sqlmap, nikto, dll.) | T1595 Active Scanning |
| File berbahaya / makro / EICAR | T1204.002 User Execution: Malicious File |
| Ekstensi tidak sesuai isi | T1036 Masquerading |
| Webshell di gambar | T1505.003 Web Shell |
| Template injection Office | T1221 |
| Token CSRF gagal | T1185 Browser Session Hijacking |
Kejadian risiko tinggi memberi lencana merah di menu Audit log dan tampil di Dashboard (early warning).

## Catatan keamanan
- Ganti `SECRET_KEY`; gunakan sertifikat TLS resmi; batasi akses jaringan ke PostgreSQL.
- Pemindai internal bersifat heuristik; untuk antivirus penuh aktifkan ClamAV (`CLAMAV_ENABLED=true`).
- Backup database rutin; audit log sebaiknya diarsipkan berkala (kebijakan retensi sesuai ketentuan).


## Pemasangan di WSL2 (alternatif .exe)
Jalankan `wsl\Install_WSL.bat` sebagai Administrator (tambahkan `-Lan` untuk akses jaringan). Rincian: `docs/10_Panduan_Instalasi_WSL2.md`.
