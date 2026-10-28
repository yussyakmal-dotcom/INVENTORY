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

## CRUD Gudang dan Dapur

Menu **Dapur** menyediakan daftar, tambah, ubah, dan hapus Gudang serta Dapur. Mutasi master hanya untuk Admin; pengguna lain dapat membaca daftar.

- Gudang: kode unik, nama, jenis Central/Toko/Gudang dapur/Gudang packing, dan status aktif.
- Dapur: kode unik, nama, jenis Produksi/Packing, serta satu gudang eksklusif dengan jenis yang sesuai. Buat gudangnya terlebih dahulu. Status operasional dapur mengikuti gudang.
- Hapus hanya untuk master tanpa dependensi. Gudang yang terhubung dapur, akses pengguna, data lama, saldo atau riwayat transfer tidak dapat dihapus. Dapur yang terkait produk atau riwayat transaksi gudangnya juga tidak dapat dihapus.
- Gudang boleh dinonaktifkan bila stok kosong, seluruh transfer selesai, dan tidak ada produk aktif di dapurnya. Minimal satu Central tetap aktif. Riwayat dipertahankan.
- Nama/kode dapat dikoreksi. Perubahan jenis/gudang dibatasi bila sudah digunakan agar arti riwayat tidak berubah.
- Semua perubahan memakai transaksi, audit, idempotency key, dan token versi untuk menolak perubahan dari formulir lama.
- Schema versi 3 menjalankan seed D01–D10/PACK hanya sekali. Restart tidak membuat ulang master yang sudah dihapus atau diganti kodenya.

API: `save-warehouse`, `delete-warehouse`, `save-kitchen`, `delete-kitchen` melalui endpoint command yang sama. Update/delete wajib menyertakan `id` dan `version` dari catalog.

## Dokumen kirim dan penerimaan transfer

- Pengiriman wajib mencatat nomor dokumen unik (disimpan huruf besar) dan tanggal kirim. Satu dokumen dapat memuat beberapa barang; FEFO memecah barang menjadi baris lot/batch agar ketertelusuran tetap terjaga.
- Penerimaan dipanggil berdasarkan nomor dokumen pada menu Transfer. Layar menampilkan tanggal kirim, gudang asal/tujuan, nama barang, batch, satuan, qty kirim, qty sudah diterima, dan sisa.
- Tanggal penerimaan diisi sesuai kejadian fisik, default hari ini (Asia/Jakarta). Tanggal tidak boleh sebelum kirim atau di masa depan.
- Qty terima default sama dengan sisa kiriman (penerimaan pertama sama dengan qty kirim), dapat dikurangi atau diisi nol per baris. Minimal satu baris positif. Jumlah melebihi sisa ditolak; kekurangan tetap dalam perjalanan.
- Setiap penerimaan sebagian memiliki tanggal dan detail qty sendiri. Idempotency key mencegah pengulangan mutasi saat permintaan yang sama dicoba lagi. Tanggal dokumen terpisah dari timestamp pencatatan sistem; tanggal mundur tidak menghitung ulang saldo historis.
- Schema versi 4 menambahkan tabel dokumen dan riwayat penerimaan tanpa mengubah saldo. Transfer lama mendapat nomor `TRF-ID` dan tanggal kirim dari timestamp pencatatan (WIB); referensi lama tetap tersimpan. Tanggal penerimaan lama tidak direkayasa.

API `ship`: `document_number`, `shipped_date`, `source_id`, `destination_id`, `lines: [{product_id, qty}]`. Bentuk satu barang `product_id`/`qty` juga diterima, tetapi tanggal dan nomor dokumen tetap wajib. API `receive-transfer`: `id`, `received_date`, `lines: [{id, qty}]`, dengan `id` baris transfer (lot). Catalog transfer menyertakan detail barang dan `receipts` untuk seluruh riwayat penerimaan setelah pembaruan.

## Petugas, kendaraan, dan cetak Delivery Order

Pengiriman baru wajib mengisi `sender_name` (nama petugas pengirim, maksimal 150 karakter) dan `vehicle_number` (nomor kendaraan, maksimal 50 karakter, disimpan huruf besar). Penerimaan baru wajib mengisi `receiver_name` (maksimal 150 karakter) untuk setiap penerimaan sebagian. Nama petugas fisik terpisah dari akun pengguna yang mencatat transaksi; keduanya tetap tersimpan.

Pilih nomor dokumen di menu Transfer lalu tekan **Cetak DO**. Dialog cetak browser dapat digunakan untuk printer atau Simpan sebagai PDF. Format A4 memuat nomor/tanggal DO, gudang asal/tujuan, pengirim, kendaraan, barang per batch, satuan, qty kirim, tempat tanda tangan, dan riwayat penerimaan beserta nama petugas jika sudah ada. Cetak tidak mengubah stok maupun status dokumen.

Schema versi 5 menambahkan tabel identitas pengiriman dan penerimaan tanpa mengubah transaksi lama. Identitas yang belum pernah dicatat ditampilkan sebagai **Belum tercatat**, bukan diambil otomatis dari akun pengguna.
