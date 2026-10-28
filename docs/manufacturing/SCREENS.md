# Alur layar manufaktur

Status: rancangan layar dan interaksi, belum berupa UI yang dipasang pada aplikasi.

## Menu dan alur utama

Master → BOM → Planning → Persetujuan MO → Kesiapan bahan/permintaan central → WO per dapur → Produksi → Laporan hasil → Persetujuan kepala dapur → Stok hasil → Transfer/packing/pengiriman.

Planning WIP adalah jalur tersendiri dari monitor buffer. MO pemakai memakai stok WIP tersedia dan tidak bergantung pada nomor WO WIP baru.

## 1. Dapur dan gudang

Daftar kolom: kode dapur, nama, jenis produksi/packing, gudang, status, jumlah produk aktif. Seed D01–D10 dan PACK; tidak mengubah nama gudang lama. Klik dapur membuka gudang dan daftar produk yang ditugaskan.

## 2. Master produk

Form: kode/nama, jenis, satuan dasar/konversi, umur simpan hari, harga jual (termasuk produk turunan), dapur produksi aktif, status. Tombol “Pindahkan dapur” menampilkan preview MO belum mulai yang ikut pindah, reservasi yang akan dilepas, WO yang berubah, serta MO berjalan yang tetap di dapur lama. Konfirmasi mencatat riwayat dan melakukan perubahan atomik.

## 3. BOM dan versi

Header: produk hasil, dapur aktif (baca saja), versi, hasil standar, satuan hasil, status draft/active/retired. Tabel bahan: SKU, jenis bahan/kemasan, QTY, satuan, konversi, QTY dasar. Tabel overhead: nama, basis per batch, nilai 0. Tabel produk turunan: SKU, estimasi QTY, satuan, HPP 0.

Tindakan: simpan draft, validasi, aktifkan versi, salin versi. Panel simulasi target memperlihatkan rasio batch dan kebutuhan bahan. Aktivasi ditolak jika BOM melingkar, hasil standar <= 0, satuan tidak valid, atau umur simpan hasil/turunan belum diisi.

## 4. Planning

Filter tanggal/dapur/jenis sumber. Grid: sumber kebutuhan dan referensi, produk, QTY kebutuhan, stok layak, reservasi, pasokan terkonfirmasi, rekomendasi, target disesuaikan, dapur produksi, tanggal rencana, status persetujuan.

Tab “Buffer WIP”: gudang tujuan, WIP, minimum, target, proyeksi, kekurangan, rekomendasi produksi/transfer. Tampilkan dapur produksi WIP dan gudang tujuan secara terpisah. Tombol “Buat MO” memeriksa sumber/alokasi yang sudah ada agar tidak menggandakan kebutuhan.

## 5. Detail MO dan kesiapan

Header: nomor MO, sumber, produk, target, BOM snapshot, dapur, gudang, tanggal rencana, status, WO terkait. Tabel bahan: kebutuhan, reservasi MO ini, stok bebas, kekurangan, ED lot terpilih. Tampilan “Menunggu bahan” tetap mengizinkan simpan dan persetujuan; tombol mulai hanya tersedia lewat WO yang siap.

Tindakan: setujui, cadangkan ulang FEFO, buat permintaan central, gabung WO satu dapur, batalkan sebelum mulai. Perubahan QTY/BOM sebelum mulai membatalkan persetujuan lama dan menghitung reservasi ulang. Tidak tersedia edit target saat berjalan.

## 6. Permintaan dan transfer bahan

Permintaan berisi dapur/gudang tujuan, referensi kebutuhan MO, SKU, QTY kekurangan, QTY disetujui, QTY sudah dikirim/diterima. Central dapat membuat satu atau beberapa transfer yang ditautkan ke baris permintaan.

Halaman kirim menampilkan lot FEFO dan QTY; halaman terima menampilkan QTY kirim, diterima, sisa transit, status ED dan selisih. Konfirmasi terima tidak boleh menambah QTY di luar kiriman. Selisih punya tindak lanjut kembali/rusak/hilang/koreksi, bukan otomatis masuk scrap produksi.

## 7. Daftar dan detail WO

Daftar: nomor WO (sekaligus nomor batch), dapur, tanggal rencana, status, jumlah produk, kesiapan. Detail: daftar MO, produk, target, bahan, kekurangan, status. Hanya MO satu dapur yang bisa dipilih. Tombol “Mulai WO” menjalankan validasi stok server dan menampilkan penerbitan bahan ke proses.

## 8. Pelaksanaan dan laporan hasil

Tab per baris produk/MO agar biaya dan bahan tidak tercampur antarproduk.

| Panel | Isian/tampilan |
|---|---|
| Bahan | Lot, satuan, rencana, sudah dikeluarkan, tambahan + alasan, aktual dipakai, sisa kembali, kehilangan + alasan |
| Hasil | Target terkunci, bagus aktual, tanggal selesai, hasil normal otomatis, scrap otomatis/tag tetap, surplus otomatis |
| Turunan | SKU dari BOM, QTY aktual (boleh 0), satuan, batch WO, umur simpan/ED otomatis, HPP 0 |
| Biaya | Nilai bahan aktual per lot, kemasan, overhead 0, total C, pembagi G, estimasi HPP |
| ED | Tanggal selesai + umur simpan snapshot; khusus paket tampilkan pembatas ED per lot komponen |

Tombol simpan draft tidak menambah stok hasil. “Ajukan hasil” memvalidasi rekonsiliasi bahan dan seluruh baris WO. Hasil 0 menampilkan kerugian produksi dan tidak menghitung HPP unit. Tambahan pemakaian membutuhkan stok dan alasan. Sisa bahan tidak boleh diperlakukan sebagai surplus produk.

## 9. Persetujuan kepala dapur

Ringkasan rencana vs aktual, seluruh penyimpangan, scrap, surplus, turunan, biaya, ED, dan pengembalian bahan. Tombol “Kembalikan untuk diperbaiki” wajib alasan. Tombol “Setujui dan bukukan” menghasilkan satu transaksi atomik; hasil baru boleh ditransfer setelah berhasil. Klik/kirim ulang tidak menghasilkan duplikasi. Bila validasi stok/ED berubah, tampilkan alasan konkret tanpa posting sebagian.

## 10. Packing

Tab “Transit” menampilkan produk dari dapur dan tindak lanjut ke toko/pelanggan tanpa mengubah SKU/ED. Tab “Perakitan paket” memakai layar MO/WO sama, dapur PACK dan BOM paket tetap. Saat memilih komponen, tampilkan batch dan ED; preview ED paket menunjukkan komponen pembatas. Paket hasil hanya tersedia setelah persetujuan.

## 11. Laporan dan batch

Filter WO/batch, SKU, dapur/gudang, rentang tanggal, sumber kebutuhan. Klik batch menampilkan bahan asal, konsumsi per MO, hasil normal/surplus/turunan, scrap, perpindahan, dan tujuan kirim. Laporan HPP tetap memisahkan setiap produk dalam WO. Monitor WIP menampilkan minimum/target/stok bebas/pasokan dan rekomendasi.
