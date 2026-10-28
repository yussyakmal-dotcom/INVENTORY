# Rencana implementasi dan kriteria penerimaan

Dokumen rancangan; belum mengubah aplikasi atau menjalankan migrasi database. Semua endpoint berikut adalah kontrak yang direncanakan, bukan API yang sudah tersedia.

## 1. Pendekatan arsitektur

Gunakan FastAPI, SQLAlchemy dan MariaDB yang sudah ada. Pindahkan aturan produksi, FEFO, RBAC, dan posting ke layanan server dengan tabel relasional pada `schema.dbml`. Frontend mengirim perintah, bukan seluruh snapshot stok yang dianggap benar oleh server.

Satu sumber kebenaran stok wajib berlaku untuk penerimaan, transfer, pemakaian, opname, scrap, produksi dan pengiriman. Endpoint lama `PUT /api/state` harus berhenti menerima perubahan koleksi operasional yang sudah dimigrasikan. Data UI/tema dapat tetap di browser atau state nonoperasional. Menyembunyikan tombol pemakaian lama tidak cukup untuk mencegah bypass stok.

Gunakan akun sesi yang sudah ada. Audit actor selalu dari sesi; scope gudang/dapur diperiksa server. Tidak mengubah deployment pengguna secara otomatis dalam pekerjaan spesifikasi ini.

## 2. Kontrak perintah yang direncanakan

| Kelompok | Perintah/kueri |
|---|---|
| Master | `GET /api/manufacturing/kitchens`, kelola umur simpan dan `POST /api/products/{id}/change-kitchen` |
| BOM | Buat/edit draft versi, validasi, aktivasi `POST /api/boms/{id}/activate` |
| Planning | Preview kebutuhan dan buffer, simpan rencana, approve, generate MO dengan alokasi sumber |
| MO | Buat, approve, readiness, reserve/reallocate, cancel, ubah draft sebelum mulai |
| WO | Buat dari daftar MO, release, start; penugasan satu dapur |
| Bahan | Buat permintaan, approve; issue tambahan dengan alasan; draft actual/return |
| Laporan | Simpan revision, submit, return-for-correction, approve-and-post |
| Transfer | Create, reserve FEFO, ship, receive, settle discrepancy |
| Pengiriman | Dispatch pelanggan dengan FEFO, gudang sumber, dan referensi pesanan |
| Laporan baca | Kebutuhan bahan, buffer, variance, HPP, scrap/surplus, expiry, trace batch |

Mutasi kritis menerima `Idempotency-Key` dan versi dokumen. Respons validasi menyebut SKU/gudang/lot yang bermasalah. Gunakan 409 untuk konflik versi/stock race; 403 untuk scope; 422 untuk ketidaksesuaian bisnis. Hash payload disimpan; kunci sama dengan payload berbeda ditolak.

## 3. Transaksi stok

Persetujuan MO mengunci MO serta produk/bahan terkait dan posisi stok dalam urutan ID konsisten. Hitung stok bebas dari saldo layak dikurangi reservasi aktif; buat reservasi parsial jika kurang. Perintah mulai WO mengunci semua MO, reservasi, lot, dan posisi stok terkait; cek ulang kesiapan semua baris. Pindahkan saldo bahan gudang ke custody WO dan tandai reservasi issued. Jangan membebankan konsumsi penuh pada saat issue.

Tambahan bahan dipindah dari gudang ke custody dengan baris issue yang ditautkan ke MO/baris WO. Hal ini memungkinkan produk berbeda dalam WO yang sama memakai SKU/lot sama tanpa menggandakan pemakaian dan biaya. Setiap issue harus direkonsiliasi pada laporan final.

Persetujuan hasil dalam satu transaksi:

1. Kunci WO, MO, report revision, issue, lot, posisi stok dan idempotency key; cek aktor, status, versi, dan semua hasil.
2. Validasi setiap issue: tidak negatif; konsumsi + kembali + kehilangan = issued. Semua issue harus masuk; tambahan punya alasan dan sudah diterbitkan.
3. Validasi tanggal, umur simpan snapshot, ED bahan/komponen dan FEFO. Tidak ada hasil dari bahan kedaluwarsa; sisa yang kini kedaluwarsa kembali terblokir.
4. Tutup custody: konsumsi/loss mengurangi stok proses, sisa memindah ke gudang/lot asal. Biaya konsumsi/loss memakai biaya issue snapshot.
5. Hitung C per baris WO, normal/scrap/surplus, turunan biaya 0, dan ED hasil. Jika G=0, C menjadi kerugian produksi dan tidak dibagi nol.
6. Buat lot serta output normal/surplus/turunan, saldo, movement, cost detail, dan scrap shortfall tanpa pengurangan stok kedua. Terapkan rekonsiliasi pembulatan nilai.
7. Tutup reservasi tersisa, MO, WO, report; simpan approver dan audit dalam transaksi; simpan hasil idempotency; commit.

Jika langkah mana pun gagal, rollback seluruh posting; tidak boleh hasil masuk tanpa konsumsi atau sebaliknya. Journal mutasi harus append-only. Kunci dokumen dan unique posting key mencegah posting ganda bahkan dengan idempotency key berbeda.

FEFO diaplikasikan ulang pada reservasi dan issue; jangan mengambil reservasi MO lain. Transfer reservasi dan produksi harus memakai mekanisme saldo/lock yang sama. Perubahan dapur produk mengunci produk dan MO yang terpengaruh; jika MO sudah dimulai oleh transaksi lain, biarkan di dapur lama. Rencana pengalihan dan histori dibukukan atomik.

## 4. Migrasi dan kompatibilitas

1. Backup database, `app_state`, audit, dan inventaris volume. Jalankan migrasi pada salinan staging dahulu. Jangan reset volume produksi.
2. Buat tabel target melalui migrasi ber-versi. Selaraskan tipe PK/FK `users` dengan tabel autentikasi nyata (saat ini Integer); DBML konseptual memakai bigint. Pertahankan akun, hash, dan sesi; jangan seed ulang akun.
3. Import master/gudang/produk/konversi dan lot dari snapshot JSON konsisten; simpan peta ID lama→baru dan versi sumber. Jangan mengasumsikan ID gudang tertentu adalah central.
4. Rekonsiliasi kuantitas/nilai per gudang/SKU/lot; impor reservasi, transfer terbuka, scrap/opname pending serta hubungan dokumen. Saldo transit harus dipertahankan, tidak dihitung sebagai stok siap pakai.
5. Seed D01–D10 dan PACK secara idempotent menggunakan kode unik, tanpa mengganti gudang lama. Minta admin melengkapi penempatan, umur simpan, dan BOM sebelum mengaktifkan produk manufaktur; jangan mengarang expiry data lama.
6. Pertahankan histori movement lama sebagai arsip baca-saja. Saldo awal relasional menjadi titik cutover yang dapat direkonsiliasi dengan arsip; jangan impor histori sebagai delta saldo kedua kali.
7. Migrasikan seluruh jalur tulis stok dan matikan penulisan koleksi stok di `/api/state` dalam satu cutover terkontrol. UI lama boleh dibaca selama transisi; tidak boleh menulis dua sumber stok.
8. Validasi ulang saldo/nilai, pending documents, scope dan audit; aktifkan fitur secara bertahap. Rollback sebelum ada transaksi baru dapat memakai backup; setelah transaksi baru terjadi perlu rekonsiliasi/reversal atau replay terkontrol, bukan menimpa dengan snapshot lama.

## 5. Tahapan pengembangan

| Tahap | Hasil yang harus tersedia |
|---|---|
| A — Fondasi stok | Tabel, migrasi staging, lot/posisi/movement tunggal, FEFO, lock, idempotency, akses server; jalur stok lama beralih |
| B — Master/BOM | Seed dapur/packing, assignment dan histori, umur simpan, versi BOM, overhead 0, turunan |
| C — Planning | Sumber demand dan alokasi, buffer per gudang, MO, persetujuan, reservasi, permintaan central |
| D — Eksekusi | WO satu dapur, custody bahan, tambahan, return, laporan aktual, persetujuan atomik, HPP, scrap/surplus |
| E — Packing/distribusi | BOM paket, ED minimum komponen, transit, transfer toko, dispatch pelanggan, trace lot |
| F — Penerimaan | Skenario bisnis dan konkurensi di bawah, rekonsiliasi cutover, panduan operator |

## 6. Skenario penerimaan

| ID | Skenario dan hasil yang wajib |
|---|---|
| A01 | Seed ulang tetap menghasilkan tepat D01–D10 + PACK dan satu gudang per dapur; data lama tidak diganti. |
| A02 | BOM 40 pcs, target 80: kebutuhan dua kali resep; konversi satuan tepat dan kebutuhan pecahan tampil jelas. |
| A03 | Satu WO berisi dua produk satu dapur diterima; kombinasi dapur berbeda ditolak server. |
| A04 | MO target 40, bagus 38, C=380.000: normal +38, scrap 2 bertag benar, HPP 10.000; tidak ada stok bagus -2 tambahan. |
| A05 | Target 40, bagus 41: normal +40, surplus +1; biaya dibagi 41; nilai output total = C setelah pembulatan. |
| A06 | Telur utuh dikonsumsi untuk kuning telur: putih telur QTY aktual masuk SKU sendiri, biaya 0, ED sendiri, batch WO; biaya telur pada produk utama; harga jual dapat >0. |
| A07 | Issue tepung 10 kg, konsumsi 9,5, kembali 0,5: saldo gudang turun bersih 9,5; HPP memakai 9,5; lot/ED/biaya return tetap asal. |
| A08 | Tambahan 1 kg beralasan menambah issue dan HPP; tanpa stok/otorisasi/alasan ditolak. Rekonsiliasi issue yang tidak seimbang ditolak. |
| A09 | Buffer WIP gudang D02 tidak dijumlahkan dengan gudang D03; rekomendasi memperhitungkan reservasi dan pasokan pasti tanpa ganda. |
| A10 | WIP tersedia di D02 dapat dipakai langsung walaupun tidak ada WO WIP baru. WIP hanya di D01 belum memenuhi kesiapan D02 sampai diterima transfer. |
| A11 | MO kurang WIP boleh dibuat/approved, cadangan parsial ada, WO tidak bisa mulai; setelah penerimaan dan realokasi cukup, start berhasil. |
| A12 | Assignment berpindah D01→D02: MO berjalan tetap D01; MO belum mulai pindah D02 dan reservasi lama dilepas; WO lama tidak mengandung MO lintas dapur. |
| A13 | Dua operator mulai WO berbeda yang berebut lot: total issued tidak melebihi stok, satu gagal/menunggu; stok tidak negatif. |
| A14 | Klik approve dua kali atau retry sesudah timeout: satu posting, satu rangkaian stok/cost, satu status selesai. |
| A15 | Kegagalan di tengah posting rollback konsumsi, return, output, biaya dan status seluruh WO. |
| A16 | Satu WO menghasilkan dua SKU berumur simpan berbeda: nomor batch sama, ID lot berbeda, ED masing-masing sesuai snapshot. |
| A17 | Produksi 28-10-2026, umur simpan 3 hari → ED 31-10-2026. Perhitungan memakai tanggal Jakarta, bukan tanggal UTC. |
| A18 | Paket selesai 28-10, umur 5 hari, komponen ED 30-10 dan 02-11 → ED paket 30-10. Transfer transit saja tidak mengubah ED. |
| A19 | FEFO memilih ED terdekat; stok expired/blocked/tanpa ED/transit/custody lain/reservasi MO lain tidak tersedia; cek ulang saat posting/kirim. |
| A20 | Stok reservasi menjadi expired sebelum start: start ditolak, realokasi memilih lot valid atau status waiting. |
| A21 | Kirim 100, terima 98: tujuan +98, 2 masih kasus transit; tidak otomatis menjadi scrap produksi. Terima 101 ditolak. |
| A22 | Staf D01 tidak bisa memulai, approve, issue atau transfer dari gudang D02 tanpa capability. Pengujian lewat API langsung juga ditolak. |
| A23 | WO dua produk dengan biaya berbeda menghitung HPP masing-masing, bukan membagi biaya total WO dengan total pcs semua produk. |
| A24 | Hasil bagus 0: stok output 0, scrap=target, total biaya menjadi kerugian disetujui, tidak ada pembagian nol. |
| A25 | Master BOM/umur simpan berubah setelah persetujuan: MO existing memakai snapshot; aktivasi BOM melingkar/dua versi aktif ditolak. |
| A26 | Report dikembalikan untuk diperbaiki belum menambah stok hasil. Hanya revision final yang disetujui dapat diposting. |
| A27 | Paket dan barang transit hanya dapat dikirim setelah stok diterima/disetujui; dispatch pelanggan menyimpan referensi pelanggan/order. |
| A28 | Restore/migrasi staging cocok kuantitas dan nilai sumber; endpoint state lama tidak dapat mengubah stok yang sudah dimigrasikan. |

## 7. Pilihan teknis yang dinyatakan eksplisit

Detail berikut adalah default rancangan, bukan keputusan bisnis baru: kode PACK/G-PACK, posting WO sekaligus, expiry berlaku sampai akhir hari ED, umur 0 berarti hari yang sama, skala pecahan batch dengan validasi satuan, idempotency dan row locking, pengakuan kerugian saat hasil bagus nol, serta blokir lot lama tanpa ED. Batas integrasi sumber pesanan/permintaan toko disiapkan melalui reference/adaptor; implementasi awal dapat menerima input/import sumber tersebut tanpa mengasumsikan koneksi POS tertentu sudah tersedia.
