# Pemulihan inventory — 28 Oktober 2026

Implementasi memulihkan metadata produk/kategori/merek/jenis, supplier dan lead time, PO diskon/net/subtotal/catatan/penomoran, penerimaan multi-batch/rak, opname blind count pada respons sesi, autosave, Excel terikat token dan recount, draft transfer/reservasi/TTL, approval kehilangan transit, laporan/ekspor, forecast, pengaturan, audit dan pengelolaan akun. Seluruh transaksi memakai ledger fondasi yang sama.

Opname tidak membekukan seluruh gudang: posting menerapkan selisih snapshot terhadap saldo terkini secara atomik dan menolak saldo negatif atau pelanggaran reservasi. Kekurangan transit diputuskan melalui approval scrap tanpa pengurangan stok gudang kedua kali. Migrasi metadata bersifat tambahan dan idempoten; arsip tetap disimpan, tidak diposting ulang sebagai transaksi.

Validasi: 51 tes API SQLite lulus. Browser mencakup alur master, BOM, transfer, PO/cetak, penerimaan, scrap, opname dan mobile. CI juga menjalankan tes pemulihan pada MariaDB.

Belum merupakan sertifikasi kesetaraan seluruh audit: pengelompokan laporan selengkap asli, pilihan batch manual, penyajian riwayat arsip yang sepenuhnya setara, dan seluruh skenario UI tambahan masih perlu pemeriksaan lanjut. Jangan mengalihkan aplikasi induk hanya karena tes fondasi lulus. Planning/MO/WO tetap pekerjaan berikutnya setelah pemulihan tervalidasi.

## Koreksi model dan workspace — 28 Oktober 2026

- Master operasional tunggal: gudang memiliki kemampuan `can_produce` / `can_pack`. Dapur bukan lokasi stok kedua. Gudang biasa juga dapat diberi kemampuan produksi.
- Produk jadi menunjuk `production_warehouse_id` melalui tabel FK `inv_production_locations`; aktivasi BOM memakai penetapan tersebut. Bahan baku/WIP tetap tidak diwajibkan memiliki penetapan produk jadi.
- Upgrade skema 9 memetakan relasi dapur lama ke ID gudang yang sama, tanpa memindah/mengulang saldo dan mutasi. Nama seed yang belum dikustomisasi menjadi D01–D10 / Dapur 1–10. Nama pengguna tetap dipertahankan.
- Tabel/API dapur lama dipertahankan sebagai kompatibilitas selama migrasi, bukan master kedua di UI. Data baru dapat dibuat tanpa baris dapur lama.
- Tambah/ubah/detail, approval dan penerimaan transfer muncul dalam dialog. Daftar tetap menjadi workspace, pencarian dan posisi scroll dipertahankan. Pesan validasi tampil dalam dialog. Menutup form berubah meminta konfirmasi; hitungan opname disimpan dulu.
- Gudang/produk/PO/transfer/scrap/opname dan form master lain memakai pola yang sama. Cetak DO tetap di samping Kirim setelah dokumen tersimpan.
- Verifikasi: 53 tes API SQLite, termasuk upgrade idempoten, konservasi saldo dan guard kemampuan gudang; browser menguji master terpadu, penetapan produk, popup, filter tetap, transfer/cetak/penerimaan, approval PO/scrap, autosave blind count, dan viewport mobile.
- Planning/MO/WO dan eksekusi produksi belum diimplementasikan; model ini mempersiapkan satu gudang mengonsumsi beberapa SKU dan menghasilkan satu atau beberapa SKU melalui BOM.
