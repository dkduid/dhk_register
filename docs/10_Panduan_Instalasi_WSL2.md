# Panduan Instalasi Register DHK di WSL2

Alternatif dari installer `.exe`: aplikasi berjalan sebagai service Linux (systemd) di dalam Ubuntu pada WSL2, dengan PostgreSQL di distro yang sama. Seluruh data (database, unggahan, log) berada di dalam distro, di `/opt/dhk_register`.

## 1. Prasyarat
- Windows 11 (atau Windows 10 22H2) dengan virtualisasi aktif di BIOS.
- Hak Administrator dan akses internet (paket apt, pip, dan unduhan Ubuntu).
- Paket sumber lengkap (hasil clone repo atau zip), **bukan** folder `dist\DHKRegister`.

## 2. Instalasi otomatis (disarankan)
1. Buka folder `wsl` di dalam paket sumber.
2. Klik kanan `Install_WSL.bat`, pilih **Run as administrator**. Untuk akses dari komputer lain di jaringan: jalankan `Install_WSL.bat -Lan`.
3. Skrip memasang Ubuntu-24.04 bila belum ada (bila diminta restart, restart lalu ulangi langkah 2), mengaktifkan systemd, lalu menjalankan `install_wsl.sh` di dalam WSL: memasang PostgreSQL dan Python, membuat `.env` (SECRET_KEY dan password database acak, mode 600), membuat database dan tabel, dan mendaftarkan service `dhk-register`.
4. **Catat password admin** yang tampil di ringkasan (username `admin`, wajib diganti saat login pertama).
5. Buka `https://localhost:8443` dan terima peringatan sertifikat self-signed.

Scheduled Task `DHK Register WSL` menjaga distro tetap hidup dan berjalan saat boot, sehingga service ikut aktif.

## 3. Instalasi manual di dalam WSL
Di terminal Ubuntu (systemd harus aktif; periksa `/etc/wsl.conf` berisi `[boot]` dan `systemd=true`):

```
sudo bash /mnt/c/<lokasi-paket>/wsl/install_wsl.sh /mnt/c/<lokasi-paket>
```

Skrip idempoten: `.env` yang sudah ada dipertahankan, berkas aplikasi disinkronkan ulang (kode diperbarui, data dan `.env` tidak ditimpa).

## 4. Operasional
| Keperluan | Perintah (di Windows) |
|---|---|
| Status dan 20 baris log terakhir | `Status_WSL.bat` |
| Restart aplikasi | `wsl -d Ubuntu-24.04 -u root -- systemctl restart dhk-register` |
| Diagnosa penuh | `wsl -d Ubuntu-24.04 -u dhk -- /opt/dhk_register/venv/bin/python /opt/dhk_register/run.py --diagnose` |
| Reset password admin | `wsl -d Ubuntu-24.04 -u dhk -- /opt/dhk_register/venv/bin/python /opt/dhk_register/run.py --reset-admin` |
| Log aplikasi | `\\wsl$\Ubuntu-24.04\opt\dhk_register\logs` |
| Log instalasi | `/var/log/dhk_install_wsl.log` (di WSL) dan `wsl\logs\install_wsl_*.log` |
| Cadangan database | `wsl -d Ubuntu-24.04 -u root -- sudo -u postgres pg_dump dhk_register > dhk_register.sql` |

Pembaruan aplikasi: ganti isi paket sumber dengan versi baru, lalu jalankan ulang `Install_WSL.bat`.

## 5. Akses dari jaringan
- Windows 11 22H2 ke atas: opsi `-Lan` mengaktifkan *mirrored networking* di `%UserProfile%\.wslconfig` dan membuat aturan firewall port 8443 (profil Domain dan Private).
- Windows yang lebih lama: `-Lan` membuat `netsh portproxy` ke IP WSL. IP itu bisa berubah setelah restart; jalankan ulang `Install_WSL.bat -Lan` bila LAN tidak tembus.

## 6. Kode kesalahan
| Kode | Arti | Perbaikan |
|---|---|---|
| WI-01 | Bukan Administrator | Jalankan sebagai Administrator |
| WI-02 | `wsl.exe` tidak ada | Gunakan Windows 10 22H2 / 11, aktifkan fitur WSL |
| WI-03 | `run.py` tidak ditemukan | Jalankan dari paket sumber lengkap |
| WI-04 / WI-05 | Pemasangan atau pendaftaran distro gagal | Aktifkan virtualisasi di BIOS, `wsl --update`, restart Windows |
| WI-06 | `install_wsl.sh` gagal | Lihat kode `W-xx` dan `/var/log/dhk_install_wsl.log` |
| W-03 | apt gagal | Periksa internet atau proxy di dalam WSL |
| W-04 | PostgreSQL tidak berjalan | `pg_lsclusters`, `sudo service postgresql start` |
| W-05 | pip gagal | Periksa akses ke pypi.org |
| W-06 / W-07 | Pembuatan database atau `--init-db` gagal | `logs/error.log`, `run.py --diagnose` |
| W-08 | systemd belum aktif | Isi `/etc/wsl.conf`, lalu `wsl --shutdown` dan ulangi |
| W-09 | Aplikasi tidak menjawab `/health` | `journalctl -u dhk-register -n 50` dan `logs/STARTUP_ERROR.txt` |

## 7. Catatan keamanan
- `.env` hanya dapat dibaca user `dhk`. Jangan menyalin `.env` ke luar distro.
- Sertifikat HTTPS bawaan self-signed; ganti dengan sertifikat perusahaan lewat `SSL_CERT` dan `SSL_KEY` di `.env` bila diperlukan.
- Berkas di `/mnt/c` terbuka bagi pengguna Windows; aplikasi sengaja disalin ke `/opt/dhk_register` (ext4) dan tidak dijalankan dari `/mnt/c`.

## 8. Pencopotan
```
wsl -d Ubuntu-24.04 -u root -- systemctl disable --now dhk-register
schtasks /Delete /TN "DHK Register WSL" /F
wsl --unregister Ubuntu-24.04     # HAPUS seluruh distro termasuk database. Cadangkan lebih dulu.
```
