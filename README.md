# Inventori Multi-Gudang (MVP) — Docker

FastAPI + SQLAlchemy + MariaDB, dengan antarmuka web yang sama seperti prototype.

## Isi paket

- `app/`: kode aplikasi (FastAPI) dan tampilan web.
- `design-app/`: dokumen desain v2.0 (Review PRD, Scaffold, Schemas, Core Logic), sudah diperbarui untuk kategori 3 level, jenis barang, merek, reservasi stok, dan login.
- `docker-compose.yml`, `.env.example`: konfigurasi container. File `.env` lokal tidak diunggah.

## Menjalankan

```bash
cp .env.example .env
# Edit .env: ganti seluruh CHANGE_ME_ dengan kata sandi yang kuat.
docker compose up -d --build
```

Buka **http://IP-SERVER:8000** (port bisa diubah lewat `APP_PORT` di `.env`).
Saat pertama jalan, tunggu ±30 detik sampai MariaDB siap. Cek dengan `docker compose ps` (status app `healthy`).

## Bila build gagal karena koneksi (ReadTimeoutError)

Ulangi saja `docker compose build`; paket yang sudah terunduh disimpan di cache.
Bila tetap lambat, isi `PIP_INDEX_URL` di `.env` dengan mirror PyPI lalu build ulang.

## Menjalankan tanpa sudo

```bash
sudo usermod -aG docker $USER   # lalu logout dan login lagi
```

## Akun awal

| Peran | Username | Password awal |
|---|---|---|
| Admin | `admin` | sesuai `ADMIN_PASSWORD` di `.env` (wajib diganti saat login pertama) |
| Staf Gudang Central | `budi` | sesuai konfigurasi `.env` |
| Staf Cabang Utara | `sari` | sesuai konfigurasi `.env` |
| Purchasing | `dimas` | sesuai konfigurasi `.env` |
| Approver | `wulan` | sesuai konfigurasi `.env` |

Akun dibuat **sekali**, saat tabel `users` masih kosong. Mengubah `ADMIN_PASSWORD` di `.env`
setelah itu tidak mengubah password yang sudah ada; gunakan menu Pengguna & peran.

Untuk pemakaian sungguhan: ganti `ADMIN_PASSWORD` sebelum start pertama, set `SEED_DEMO_USERS=false`
dan `DEMO_DATA=false`, atau nonaktifkan akun demo dari menu Pengguna & peran.

## Konfigurasi (`.env`)

| Variabel | Fungsi |
|---|---|
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Akun admin pertama |
| `SEED_DEMO_USERS`, `DEMO_PASSWORD` | Buat 4 akun demo |
| `DEMO_DATA` | `true` = data contoh F&B, `false` = mulai kosong (hanya Gudang Central + kategori) |
| `DB_ROOT_PASSWORD`, `DB_PASSWORD` | Password MariaDB (sudah diisi acak) |
| `APP_PORT` | Port web |
| `COOKIE_SECURE` | `true` bila diakses lewat HTTPS |
| `SESSION_HOURS` | Lama sesi login |

## Data & backup

- Database: volume `mariadb_data`. Backup:
  `docker compose exec mariadb sh -c 'mariadb-dump -uroot -p"$MARIADB_ROOT_PASSWORD" inventory_db' > backup.sql`
- Audit log JSON Lines: volume `audit_logs`, file `/var/log/inventory/audit_log.jsonl`.
  Lihat: `docker compose exec app tail -f /var/log/inventory/audit_log.jsonl`
- API docs: `http://IP-SERVER:8000/api/docs`

## Reset total

```bash
docker compose down -v   # menghapus database & audit log!
docker compose up -d --build
```

## Lupa password admin

```bash
docker compose exec app python -c "import main; db=main.SessionLocal(); u=db.query(main.User).filter_by(username='admin').first(); u.password_hash=main.hash_pw('GANTI_DENGAN_PASSWORD_SEMENTARA'); u.must_change_password=True; u.is_active=True; db.commit(); print('ok')"
```

## Pembaruan: kategori 3 level, merek, jenis barang

Data lama dimigrasikan otomatis saat pertama kali dibuka setelah update: kategori lama menjadi
subkategori di bawah grup "Belum dikelompokkan", dan semua produk diberi jenis "Bahan baku".
Setelah itu susun ulang lewat menu Master data. Langkah update:

```bash
sudo docker compose build app && sudo docker compose up -d
```

## Pembaruan: ikon & tema

Tombol palet di kanan atas membuka pengaturan Tampilan & tema: mode Terang/Gelap/Sistem, 5 palet warna
(Pinus, Samudra, Anggur, Bata, Grafit), dan kepadatan Nyaman/Ringkas. Pilihan tersimpan per perangkat.
Ikon disematkan langsung di aplikasi (SVG), jadi tetap tampil tanpa akses internet.

## Catatan arsitektur (MVP)

- Login: session cookie HttpOnly, password di-hash PBKDF2-SHA256, kunci 5 menit setelah 5 kali gagal.
- Data operasional disimpan sebagai satu dokumen JSON ber-versi di tabel `app_state`.
  Bila dua orang menyimpan bersamaan, yang kedua mendapat pemberitahuan dan data dimuat ulang (tidak ada data tertimpa diam-diam).
- Aturan bisnis (FIFO, reservasi TTL, hak akses per peran) dijalankan di browser. Server memverifikasi login,
  mencatat siapa yang menyimpan, dan menulis audit log dengan identitas dari sesi. Untuk produksi skala besar,
  langkah berikutnya adalah memindahkan aturan ini ke endpoint server dan tabel ternormalisasi.

## Rancangan modul manufaktur

Spesifikasi yang disusun dari keputusan 28 Oktober 2026 tersedia di [docs/manufacturing](docs/manufacturing/README.md): PRD, struktur database DBML, alur layar, rencana implementasi, dan skenario penerimaan.

Implementasi tahap pertama tersedia di `/manufacturing`: master dapur/produk, BOM versi, dan stok server dengan FEFO. Mode ini diaktifkan melalui migrasi terkontrol; tidak otomatis menggantikan stok lama. Baca [panduan tahap 1](docs/manufacturing/PHASE1.md) untuk penggunaan di salinan pengujian, batas fitur, dan rollback. Planning/MO/WO dan pencatatan hasil produksi belum tersedia.

