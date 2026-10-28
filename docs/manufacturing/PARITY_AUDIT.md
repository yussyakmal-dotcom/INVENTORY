# Audit kesetaraan aplikasi asli dan fondasi

Tanggal: 28 Oktober 2026. Baseline fondasi: `ec40847d24c167574eda5bffb603682ef4086fdb`.

## Kesimpulan dan batas pemeriksaan

Fondasi **belum setara dengan aplikasi asli dan belum layak menggantikannya untuk operasional penuh**. Penguatan transaksi di server dan fitur manufaktur tidak menggantikan kelengkapan alur operasional yang hilang. Standar perbaikan: kemampuan lama dipertahankan, kebutuhan baru ditambahkan, perubahan aturan bisnis dinyatakan secara eksplisit.

Audit ini membaca implementasi asli di `app/static/index.html` dan server bersama `app/main.py`, lalu membandingkan model, layanan, dan UI fondasi di `app/inventory_models.py`, `app/inventory.py`, `app/inventory_operations.py`, `app/static/manufacturing.js`, dan `manufacturing.html`. Ini pemeriksaan statis kode, bukan pengujian ulang seluruh skenario pengguna atau sertifikasi hasil migrasi. Nomor baris berikut mengacu pada baseline tersebut; nama fungsi menjadi rujukan utama jika baris bergeser.

Aplikasi asli sudah menyimpan state bersama di server dengan version check dan mempunyai autentikasi serta audit. Jadi fondasi tidak tepat disebut peralihan dari aplikasi lokal tanpa server. Peningkatannya adalah pemindahan validasi dan mutasi bisnis ke transaksi server per operasi.

## Matriks temuan

| Area | Kemampuan asli | Kondisi fondasi / kekurangan |
| --- | --- | --- |
| Dashboard | Nilai stok, stok minimum, kedaluwarsa, transit, pekerjaan menunggu, grafik per gudang | Halaman setup belum menggantikan dashboard operasional |
| Master produk | Kategori 3 tingkat, merek, jenis, satuan/konversi, satuan beli default, supplier, stok minimum, harga referensi, TTL; impor/ekspor Excel | Ada jenis manufaktur, umur simpan, dapur dan konversi; banyak atribut lama dan impor/ekspor belum ada. Jenis manufaktur bukan pengganti kategori/merek/jenis lama |
| Supplier | Kode/nama, telepon, lead time default | Kontak tersedia; lead time untuk perencanaan belum tersedia |
| Gudang | Master gudang dan tepat satu gudang central aktif; rak dipakai transaksi | CRUD dapur/gudang tersedia; rak belum tersedia dan batas satu central tidak dipertahankan |
| PO | Nomor otomatis, satuan beli default, harga terakhir/referensi, diskon per baris, subtotal/total saat input, catatan, prioritas barang supplier, lead time, tab status, forecast ke PO | Tanggal PO, satuan beli, approval dan cetak tersedia. Alat bantu pembelian lama di samping kiri belum setara; terutama diskon, harga otomatis dan total langsung pada form |
| Penerimaan | PO/manual, banyak barang/batch, supplier/SJ, rak, harga net diskon, pemeriksaan ED/harga, nomor GRN, riwayat dokumen lengkap | PO dan penerimaan langsung terpisah; penerimaan langsung satu barang, tidak memiliki kelengkapan dokumen/rak/peringatan lama. UI penerimaan PO belum membagi satu produk ke beberapa batch dalam satu pengisian |
| Stok | Ringkasan dan per batch; pencarian/filter kategori/merek/jenis; pengelompokan, nilai/HPP, minimum, reservasi/tersedia, peringatan ED | Lot, saldo dan FEFO tersedia; ringkasan dan alat analisis stok lama belum setara |
| Transfer | Draft, reservasi stok, TTL, batal draft, pratinjau alokasi, pilihan batch dan konfirmasi penyimpangan FIFO | Dokumen/tanggal/petugas/kendaraan/satuan/cetak DO bertambah; langsung kirim FEFO, draft/reservasi/pratinjau lama belum tersedia. Penutupan kehilangan transit belum lengkap |
| Pemakaian | Satuan/konversi, pratinjau batch dan biaya, nomor USE, rincian hasil/HPP dan riwayat | Mutasi FEFO tersedia; form masih satuan dasar dan belum memiliki pratinjau serta rincian hasil/riwayat setara |
| Opname | Blind count di UI, per rak, Excel dengan kunci sesi, autosave hitungan, progres, recount sesi sama, selisih qty/nilai | Form membuka qty sistem, membekukan seluruh gudang; belum ada rak, Excel, autosave hitungan, recount, progres dan selisih nilai setara |
| Scrap | Alasan terstruktur, sumber manual/transit, estimasi/total nilai kerugian, tab menunggu/riwayat | Approval dan penahanan stok tersedia; klasifikasi transit/manual, penyelesaian selisih transit, tampilan total kerugian dan tab belum setara |
| Forecast pembelian | Pemakaian rata-rata, lead time, stok dalam pesanan, ROP, safety/cover days, pembulatan satuan beli, rekomendasi ke PO per supplier | Belum tersedia; planning manufaktur tidak menggantikan fungsi ini |
| Laporan | Valuasi, kartu stok, HPP pemakaian, anomali harga, scrap/selisih; filter/pengelompokan dan Excel | Daftar 300 mutasi terakhir bukan pengganti laporan tersebut |
| Audit | Filter aksi/pengguna/pencarian, rincian sebelum/sesudah, ekspor JSON Lines | Audit transaksi tersimpan di DB, tetapi UI dan ekspor setara belum ada |
| Pengguna | Tambah/ubah peran dan lingkup, reset password, nonaktif; ganti password sendiri | Penambahan akun dan akses gudang tambahan tersedia; UI pengelolaan akun belum selengkap asli, meskipun sebagian API lama tetap tersedia |
| Pengaturan | Identitas perusahaan, tampilan/kepadatan, batas ED, toleransi harga, safety/cover days | Belum tersedia sebagai pengaturan operasional setara |
| Cetak | PO/DO dengan identitas, penghitung salinan dan audit permintaan cetak | Layout PO terbaru dan lokasi tombol DO mengikuti permintaan pengguna; penghitung/audit cetak belum setara |

## Bukti kode yang bisa ditelusuri

| Area | Asli: `app/static/index.html` | Fondasi |
| --- | --- | --- |
| Dashboard / stok | `V.dashboard` sekitar 1154; `V.stock` sekitar 1190; helper stok 351–393 | `renderSetup`, `renderStock`; `inventory.py:stock_rows`, `fefo` |
| PO / forecast | Helper 671–727; UI forecast 1499; UI PO 1514–1567 | `renderPurchasing`, `renderPoDetail`, `printPurchaseOrder`; `inventory_operations.py:save_po`, `receive_po` |
| Penerimaan | Helper 618–667; UI 1224–1280 | `renderStock`, `receiptUnitOptions`, `renderPoDetail`; `receive_stock`, `receive_po` |
| Transfer | Helper 494–570; UI 1293–1381 | `renderTransfers`, `renderTransferReceipt`, `printDeliveryOrder`; `ship`, `receive_transfer` |
| Pemakaian / scrap | Helper 574–615; UI 1383–1443 | `consume`; `renderScrap`, `request_scrap`, `decision` |
| Opname | Helper 730–760; UI 1445–1490; Excel 1807–1822 | `renderOpname`; `start_opname`, `submit_opname`, `decision`, `freeze` |
| Master / Excel | Helper 776–844; UI master mulai 1584; impor produk 1826–1858 | `renderProducts`, `renderKitchens`; `save_product`, `save_location`, `save_supplier` |
| Laporan / audit / cetak | `reportData`, `V.reports`, `V.audit`, `auditDiff`, cetak 1761–1785 | `renderMovements`; audit di `inventory.py:execute`; fungsi cetak fondasi |
| Pengaturan / akun | UI 1680–1694; override akun server 1965–1985 | `renderAccess`; API akun bersama di `main.py` |
| Migrasi | Struktur state asli dan override penyimpanan server di bagian akhir file | `inventory.py:migration_preview`, `migrate` (386–435) |

## Risiko migrasi: arsip bukan pengganti akses operasional

Migrasi sekarang membawa gudang, sebagian atribut produk, dan lot bersaldo positif beserta biaya/ED ke fondasi. Semua produk hasil migrasi mula-mula bertipe `raw`. State lengkap lama diarsipkan, penulisan lama dikunci, lalu UI diarahkan ke fondasi.

Kategori, merek/jenis, supplier dan relasi produk, satuan beli default, minimum, harga referensi, TTL, rak, lead time, pengaturan serta riwayat dokumen PO/penerimaan/transfer/pemakaian/scrap/opname belum dipromosikan menjadi data operasional fondasi yang setara. Data tersebut tidak berarti dihapus, tetapi arsip tidak dapat dipakai seperti halaman kerja dan laporan lama.

**Penghalang integrasi:** perlu pemetaan seluruh master dan status dokumen, akses riwayat yang dapat dicari, rekonsiliasi saldo serta nilai per gudang/produk/batch, dan penanganan dokumen terbuka/reservasi/transit. Jangan menganggap penyalinan saldo positif saja cukup untuk cutover.

## Perubahan aturan yang harus dipisahkan dari regresi

1. **FIFO → FEFO:** FEFO merupakan kebutuhan baru yang telah diminta. Pertahankan FEFO dan pengamanan ED, sambil memulihkan kemudahan pratinjau/alokasi lama dengan aturan yang sesuai.
2. **Penerimaan PO:** asli menutup PO setelah penerimaan, termasuk kurang; fondasi mendukung parsial dan tutup sisa. Ini perubahan aturan, bukan sekadar perubahan tampilan. Sisa, status dan tindakan tutup harus jelas; jangan mengembalikan penutupan otomatis tanpa menilai kebutuhan terkini.
3. **Penerimaan transfer:** asli mengizinkan kelebihan dan membuat scrap transit otomatis untuk kekurangan; fondasi menolak kelebihan dan mempertahankan sisa transit untuk penerimaan lanjut. Perlu aturan akhir untuk barang hilang/retur agar transit tidak menggantung. Jangan menyalin mekanisme lama tanpa menjaga agar stok tidak dikurangi dua kali.
4. **Opname:** freeze seluruh gudang bukan perilaku asli. Solusi konflik mutasi harus disesuaikan dengan lingkup hitung/rak. Blind count harus ditegakkan pada respons server bagi petugas penghitung, bukan hanya menyembunyikan kolom. Algoritme lama yang membatasi saldo negatif ke nol juga tidak boleh disalin bila menghilangkan selisih secara diam-diam.
5. **Gudang central:** aturan asli satu central aktif berubah. Pertahankan aturan lama sebagai baseline sampai ada kebutuhan eksplisit berbeda.
6. **Approval/cetak:** persetujuan PO dan cetak setelah disetujui sudah menjadi kebutuhan percakapan. Layout cetak PO terbaru serta cetak DO sesudah penyimpanan di samping Kirim FEFO tetap dipertahankan.

## Tambahan fondasi yang harus dipertahankan

- Validasi perintah di server, role/lingkup gudang, transaksi atomik, Decimal, idempotensi dan pemeriksaan revisi.
- Master dapur/gudang, jenis manufaktur, umur simpan, aturan dapur produk jadi, serta validasi BOM untuk produk yang memenuhi jenisnya.
- FEFO, larangan penggunaan lot tidak layak, biaya dan ED lot yang tetap terbawa saat transfer.
- Satuan beserta faktor konversi tersimpan pada dokumen; perubahan master kemudian tidak mengubah makna dokumen lama.
- Penahanan stok untuk scrap menunggu persetujuan, pelepasan saat ditolak/dibatalkan, serta pencatatan barang temuan opname.
- Nomor/tanggal kirim, petugas/kendaraan, tanggal/petugas penerima dan cetak sesuai permintaan pengguna.

Planning manufaktur, MO/WO dan pencatatan hasil produksi belum tersedia dalam lingkup implementasi yang ditinjau; keberadaan BOM/master tidak berarti alur produksi sudah selesai. Itu backlog kebutuhan baru, terpisah dari pemulihan fitur asli.

## Urutan pemulihan dan syarat lulus

1. **Master pendukung:** pulihkan klasifikasi, supplier/lead time, satuan beli default, harga/minimum/rak serta pengaturan yang diperlukan. Jenis manufaktur menjadi atribut tambahan. Uji impor/ekspor dan pembaruan tanpa kehilangan data.
2. **PO dan penerimaan:** gunakan alur/form asli sebagai baseline, tambahkan tanggal dan kebutuhan yang sudah disepakati. Uji harga terakhir, satuan, diskon, subtotal/total, catatan, supplier, penerimaan beberapa batch, riwayat, persetujuan dan cetak. Harga net per satuan dasar harus konsisten sampai nilai stok.
3. **Opname:** pulihkan blind count, per rak, template/import Excel terikat sesi, simpan bertahap, progres dan recount. Uji nilai nol vs belum dihitung, reload, file sesi salah, role penghitung/approver, konflik mutasi, selisih nilai dan posting sekali saja.
4. **Stok/pemakaian/transfer/scrap:** pulihkan pencarian, filter, nilai, peringatan, pratinjau, satuan dan riwayat. Selesaikan alur transit serta penanganan stok yang sedang ditahan tanpa pengurangan ganda.
5. **Dashboard, forecast, laporan, audit, akun dan pengaturan:** kembalikan keluasan informasi dan tindakan asli, termasuk ekspor, dengan pembatasan akses server yang sesuai.
6. **Migrasi dan integrasi:** lakukan uji dengan salinan data representatif, dokumen terbuka, lot kedaluwarsa, konversi pecahan dan beberapa gudang. Rekonsiliasi kuantitas/nilai dan pastikan riwayat dapat dipakai sebelum mengalihkan operasional.

Untuk setiap modul, skenario yang sama harus dijalankan pada asli dan fondasi: input, kemudahan pengisian, hasil perhitungan, status, riwayat, cetak/ekspor dan hak akses. Perbedaan hanya boleh berasal dari kebutuhan baru yang dinyatakan. Tes API/browser fondasi yang sudah ada membuktikan bagian yang dites bekerja, **bukan bukti seluruh fitur asli sudah setara**.

Audit ini tidak mengubah kode operasional. Daftar di atas merupakan dasar perbaikan dan penerimaan hasil berikutnya.
