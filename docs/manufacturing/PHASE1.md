# Tahap 1: fondasi stok, dapur dan BOM

Implementasi pada branch pengembangan ini menambah mode fondasi di `/manufacturing`. Startup membuat tabel `inv_*` dan menyiapkan D01–D10 + PACK beserta gudangnya. Startup **tidak** memindahkan/menghapus stok lama atau mengaktifkan mode baru otomatis.

## Fitur yang tersedia

- Master 10 dapur dan packing terpisah, 1 gudang masing-masing.
- Master produk: jenis, satuan dasar, konversi, sifat diskret, umur simpan, dapur aktif, harga jual, dan status aktif.
- Pengalihan dapur produk dengan alasan dan audit. Penanganan MO berjalan/belum mulai akan ditambahkan bersama modul MO; tahap ini belum memiliki MO.
- BOM versi draft/active/retired, bahan/kemasan, overhead Rp0, dan produk turunan HPP Rp0. BOM aktif tidak diedit; aktivasi memeriksa siklus tidak langsung dan satuan.
- Simulasi kebutuhan bahan untuk target produksi berdasarkan BOM.
- Pencatatan server untuk penerimaan di central, pemakaian FEFO, kirim dan terima transfer (termasuk penerimaan sebagian).
- Identitas lot, biaya, dan ED tetap sama selama transfer. Barang dalam perjalanan tidak tersedia untuk pemakaian.
- Scope gudang di server; Staf Gudang tanpa penugasan tidak otomatis mendapat seluruh gudang. Admin dapat menambah akses gudang dan pengguna.
- Mutasi atomik dan idempotency key; pencegahan saldo negatif dan audit transaksi dalam database.
- Preview migrasi, pengecekan versi sumber, arsip JSON lama, saldo awal bernilai, dan penguncian jalur tulis JSON lama sesudah cutover.

## Cara menguji di server salinan

1. Checkout branch/commit pengembangan ini pada salinan server dengan volume database terpisah. Pertahankan `.env` lokal; kode ini tidak menyertakan kredensial.
2. Jalankan `docker compose build app` lalu `docker compose up -d`. Image memuat `inventory.py` dan `inventory_models.py` selain aplikasi lama.
3. Login melalui halaman lama. Buka tautan **Fondasi manufaktur** atau `/manufacturing`.
4. Sebelum aktivasi, inventori lama tetap berfungsi. Halaman Persiapan menampilkan versi, jumlah master/lot, nilai stok, dan penghalang migrasi.
5. Selesaikan/batalkan PO, transfer, reservasi, scrap dan opname yang masih terbuka lewat aplikasi lama. Tahap 1 menolak migrasi transaksi terbuka; tidak mengarang penyelesaiannya.
6. Buat backup database/volume. Pada salinan pengujian, aktifkan fondasi dari halaman Persiapan. Saldo dipindahkan sekali, arsip dipertahankan, dan jalur tulis lama dikunci.
7. Lengkapi jenis produk (impor awal diberi `raw` sampai diklasifikasikan), umur simpan, dapur, dan BOM. Lot impor tanpa ED diblokir; Admin dapat melengkapi ED sesuai dokumen sumber dengan alasan.
8. Uji penerimaan, FEFO, transfer central→dapur→packing/antar-dapur, receipt sebagian dan akses pengguna.

## Batas tahap ini

Planning, MO, WO, reservasi MO, perhitungan HPP hasil produksi, scrap/surplus hasil, penerimaan produk turunan, perakitan paket dan perhitungan ED hasil **belum diimplementasikan**. Kolom master dan BOM menyiapkan datanya; bukan klaim bahwa produksi sudah berjalan.

Mode fondasi awal belum memiliki purchasing/PO, opname, approval scrap, master kategori/supplier dan pengiriman pelanggan dari UI lama. Data lamanya tetap berada pada arsip, tetapi tidak bisa diedit setelah cutover. Karena itu gunakan salinan pengujian; penggantian penuh operasional menunggu modul lanjutan. Penerimaan tahap ini menyimpan referensi dokumen, belum melakukan rekonsiliasi PO.

Transfer mempunyai penerimaan sebagian dan sisa transit. Penyelesaian hilang/rusak/retur transit akan ditambahkan; sisa tidak otomatis dijadikan scrap. Pengiriman dari lot yang kedaluwarsa ditolak. Bila lot kedaluwarsa di perjalanan, penerimaan fisik tetap boleh dicatat, tetapi stok tidak layak dipakai/dikirim.

Ini adalah migrasi aditif versi 1 dengan marker `schema_version`, bukan implementasi semua tabel DBML. Riwayat stok lama tidak diimpor ulang sebagai delta; `OPENING` merupakan saldo cutover. Struktur master tetap relasional; daftar baris BOM versi disimpan dalam dokumen immutable tervalidasi server untuk tahap awal. Model ini akan diperluas bersama MO/WO.

Semua mutasi stok memakai gate baris database yang sama. Ini sengaja menserialisasi transaksi agar aman antar-worker; optimasi lock per gudang/lot menyusul setelah profiling. Setiap mutasi memiliki idempotency key dan pemeriksaan izin; perubahan UI tidak bisa melewati validasi server.

## Pengujian pengembang

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests/test_foundation.py
node --check app/static/manufacturing.js
```

Default memakai SQLite sementara. Untuk tes database MariaDB 10.11 pada database uji terpisah bernama `inventory_test`, set `TEST_DATABASE_URL` ke URL database uji tersebut sebelum menjalankan pytest. Suite menghapus tabel uji dan menolak database non-SQLite yang namanya bukan `inventory_test`.

Workflow GitHub Actions menguji SQLite dan MariaDB 10.11. Hasil lokal dan hasil workflow perlu dibedakan; lulus SQLite bukan bukti transaksi MariaDB telah diuji.

Pengujian browser: pasang paket Node `playwright` dan Chromium untuk Playwright, kemudian jalankan `python tests/run_ui_smoke.py`. Runner membuat instance SQLite sementara, sesi admin sementara, lalu menguji aktivasi, 11 dapur, produk/BOM, simulasi, penerimaan, transfer sebagian/penuh, dan lebar layar ponsel. Tidak memakai akun atau database pengguna. Jika Chromium sudah tersedia di lokasi lain, tentukan `INVENTORY_SMOKE_CHROMIUM`.

## Rollback

Sebelum cutover, aplikasi lama tetap memakai datanya dan branch lama dapat dipakai kembali. Setelah cutover dan ada transaksi baru, jangan menyalakan versi aplikasi lama pada database yang sama: JSON lama sudah menjadi arsip dan tidak memuat transaksi baru. Rollback harus memakai backup salinan serta rekonsiliasi/replay mutasi setelah cutover; jangan menghapus volume atau menonaktifkan marker secara manual.


## Koreksi kategori produk

Penetapan dapur di master hanya berlaku untuk Produk jadi. WIP, bahan baku, kemasan dan produk turunan tidak mempunyai penetapan dapur. BOM hanya boleh dimiliki Produk jadi dan WIP; paket adalah subjenis Produk jadi untuk mempertahankan BOM paket tetap. Aturan ini menggantikan cakupan penetapan dapur pada spesifikasi sebelumnya.

Upgrade schema v2 melepas penetapan dapur yang keliru pada produk nonjadi dan mengarsipkan BOM kategori yang tidak diperbolehkan, dengan audit tanpa menghapus stok atau histori.
