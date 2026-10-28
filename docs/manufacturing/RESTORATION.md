# Pemulihan inventory — 28 Oktober 2026

Implementasi memulihkan metadata produk/kategori/merek/jenis, supplier dan lead time, PO diskon/net/subtotal/catatan/penomoran, penerimaan multi-batch/rak, opname blind count pada respons sesi, autosave, Excel terikat token dan recount, draft transfer/reservasi/TTL, approval kehilangan transit, laporan/ekspor, forecast, pengaturan, audit dan pengelolaan akun. Seluruh transaksi memakai ledger fondasi yang sama.

Opname tidak membekukan seluruh gudang: posting menerapkan selisih snapshot terhadap saldo terkini secara atomik dan menolak saldo negatif atau pelanggaran reservasi. Kekurangan transit diputuskan melalui approval scrap tanpa pengurangan stok gudang kedua kali. Migrasi metadata bersifat tambahan dan idempoten; arsip tetap disimpan, tidak diposting ulang sebagai transaksi.

Validasi: 51 tes API SQLite lulus. Browser mencakup alur master, BOM, transfer, PO/cetak, penerimaan, scrap, opname dan mobile. CI juga menjalankan tes pemulihan pada MariaDB.

Belum merupakan sertifikasi kesetaraan seluruh audit: pengelompokan laporan selengkap asli, pilihan batch manual, penyajian riwayat arsip yang sepenuhnya setara, dan seluruh skenario UI tambahan masih perlu pemeriksaan lanjut. Jangan mengalihkan aplikasi induk hanya karena tes fondasi lulus. Planning/MO/WO tetap pekerjaan berikutnya setelah pemulihan tervalidasi.
