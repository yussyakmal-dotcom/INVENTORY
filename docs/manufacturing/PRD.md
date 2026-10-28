# PRD manufaktur INVENTORY

Versi 1.0 · 28 Oktober 2026. Status: aturan utama disetujui; detail teknis di bawah merupakan rancangan implementasi.

## 1. Tujuan dan batas cakupan

Mengembangkan pemakaian bahan menjadi produksi yang dapat direncanakan, ditugaskan per dapur, dihitung pemakaian aktualnya, dan ditelusuri sampai hasil serta distribusinya. Mempertahankan hubungan stok, lot, biaya, dan persetujuan dari central sampai toko/pelanggan.

Termasuk BOM, WIP, paket BOM tetap, MO, WO tanpa routing tahapan, bahan aktual, produk turunan, scrap, surplus, dan expiry. Belum mencakup penjadwalan kapasitas mesin, absensi tenaga kerja, jurnal akuntansi lengkap, maupun perubahan POS/ERP lain.

## 2. Keputusan bisnis yang disetujui

| ID | Ketentuan |
|---|---|
| B01 | Buat D01–D10 dengan nama Dapur 1–Dapur 10. Masing-masing memiliki gudang sendiri. |
| B02 | Dapur packing berdiri sendiri di luar sepuluh dapur; memiliki gudang untuk transit dan perakitan paket. |
| B03 | Gudang central menyuplai gudang dapur. Transfer juga boleh antar-dapur dan menuju packing; hasil dari packing dapat menuju gudang toko atau pelanggan. |
| B04 | Setiap produk memiliki tepat satu dapur produksi aktif pada suatu waktu; penempatannya boleh dipindahkan. |
| B05 | Saat penempatan berubah, MO yang sedang berjalan diselesaikan di dapur lama. MO yang belum dimulai mengikuti dapur baru. |
| B06 | WIP adalah SKU stok tersendiri, dibuat di dapur tertentu, dapat ditransfer dan dipakai dapur lain. |
| B07 | Planning WIP terpisah untuk buffer per gudang dapur. Produksi pemakai mengambil WIP dari stok, tidak harus menunggu WO WIP baru. |
| B08 | Planning menggabungkan pesanan pelanggan, permintaan toko, dan kebutuhan buffer; planner dapat menyesuaikan sebelum persetujuan. |
| B09 | Satu MO untuk satu produk dan target QTY. Beberapa MO dalam dapur sama dapat digabung dalam satu WO. |
| B10 | Satu WO hanya untuk satu dapur, berisi daftar produk dan jumlah; tidak ada WO per tahap adonan/panggang. |
| B11 | MO disetujui mencadangkan stok bahan/WIP. MO boleh dibuat saat stok kurang tetapi WO belum boleh mulai sebelum seluruh kebutuhan tersedia di gudang dapur. |
| B12 | Kekurangan bahan dihitung dari kebutuhan dikurangi stok tersedia. Dapur meminta; central mengirim; dapur tujuan mengonfirmasi penerimaan secara terpisah. |
| B13 | BOM menyatakan bahan untuk hasil standar tertentu, misalnya 40 pcs. Kebutuhan disesuaikan dengan target produksi. |
| B14 | Bahan disiapkan sesuai BOM; saat selesai dicatat pemakaian aktual dan sisa dikembalikan ke stok dapur. Tambahan bahan boleh dicatat dengan alasan dan menambah HPP. |
| B15 | Target 40, bagus 38: stok bagus +38, scrap 2 bertag “Rusak dalam produksi”. Scrap ini tidak mengurangi lagi stok bagus. |
| B16 | Target 40, bagus 41: hasil produksi 40 dan kelebihan produksi 1 tercatat terpisah; keduanya masuk stok dan ikut pembagi HPP. |
| B17 | Produk turunan, misalnya putih telur, masuk sebagai SKU sendiri dengan HPP Rp0 dan dapat memiliki harga jual. Biaya telur dibebankan ke produk utama. |
| B18 | Operator melaporkan hasil; kepala dapur menyetujui sebelum hasil, pemakaian final, dan HPP dibukukan. |
| B19 | Total biaya aktual setiap produk dibagi seluruh hasil bagus produk tersebut, termasuk kelebihan. |
| B20 | Overhead dicantumkan pada BOM dengan nilai Rp0 saat ini. Kemasan dalam BOM ikut biaya aktual. |
| B21 | Nomor batch hasil produksi adalah nomor WO. |
| B22 | Master setiap produk memiliki umur simpan dalam hari. Tanggal produksi adalah tanggal produksi selesai; ED = tanggal produksi + umur simpan. |
| B23 | Paket memakai BOM komposisi tetap. ED paket adalah tanggal paling awal antara ED seluruh komponen yang benar-benar dipakai dan tanggal perakitan + umur simpan paket. |
| B24 | Pengambilan bahan, WIP, dan komponen paket memakai FEFO. Barang kedaluwarsa tidak boleh diproduksi/dipakai sebagai bahan atau dikirim. |

## 3. Master dan BOM

Jenis produk: bahan baku, kemasan, WIP, produk jadi, paket, dan produk turunan. Jenis overhead pada BOM merupakan baris biaya nonstok, bukan SKU persediaan. Sebuah SKU turunan dapat dipakai sebagai bahan produksi berikutnya dengan biaya sumber Rp0; harga jual tidak memengaruhi HPP stok.

Master menyimpan kode, nama, satuan dasar, konversi satuan, umur simpan hari, status aktif, dan dapur produksi aktif untuk produk yang dibuat. Gudang central/toko tidak menjadi dapur produksi. Dapur packing khusus perakitan paket; kode teknis awal yang diusulkan `PACK`, gudang `G-PACK`; gudang dapur `G-D01` sampai `G-D10`. Kode central yang sudah ada dipertahankan.

BOM memiliki versi, produk utama, hasil standar positif, satuan hasil, daftar bahan/kemasan, overhead, dan daftar keluaran turunan. Hanya satu versi BOM aktif per produk pada satu waktu. Aktivasi memvalidasi satuan, produk aktif, tidak ada siklus langsung/tidak langsung, dan umur simpan keluaran terisi. BOM yang sudah dipakai tidak diedit; buat versi baru. MO yang disetujui menyimpan snapshot BOM, kuantitas, umur simpan, dan biaya overhead agar histori tidak berubah saat master diperbarui.

Rasio = target MO / hasil standar BOM. Bahan rencana = kebutuhan per resep × rasio. Pilihan teknis: boleh skala pecahan batch, QTY diskret harus bulat pada satuan diskretnya; pecahan kg/liter diperbolehkan. Sistem tidak boleh membulatkan diam-diam; tampilkan kebutuhan dan konversi untuk direview planner. Kuantitas memakai desimal, bukan float biner.

## 4. Planning, MO, dan WO

Baris planning menyimpan sumber kebutuhan dan alokasi QTY agar pesanan yang sama tidak direncanakan dua kali. WIP tidak dibuat sebagai anak MO wajib dari produk pemakai. Kekurangan WIP menghasilkan rekomendasi transfer atau planning WIP terpisah, bukan dependency yang menahan MO ketika stok tersedia.

Rancangan rumus buffer per produk/gudang:

`proyeksi = stok layak pakai - reservasi aktif + pasokan terkonfirmasi belum diterima`

Jika proyeksi di bawah minimum, rekomendasikan `maks(0, target_buffer - proyeksi)`. Hanya pasokan berstatus pasti yang dihitung; draft tidak dihitung. Jangan menghitung transfer dan MO sumber yang sama dua kali. Jika pemilik dapur WIP berbeda dengan gudang buffer tujuan, rencanakan produksi pada dapur pemilik lalu transfer ke gudang tujuan. Buffer tidak memberikan hak produksi di dapur yang bukan pemilik.

Status MO: `draft → approved → in_progress → awaiting_approval → completed`; `cancelled` hanya sebelum mulai. Kesiapan bahan adalah atribut terhitung `waiting_material` / `ready`, bukan bukti stok pasti saat mulai. Persetujuan boleh mencadangkan sebagian stok yang ada; WO tetap terblokir jika ada kekurangan. Pembatalan melepaskan reservasi.

Status WO: `draft → released → in_progress → awaiting_approval → completed`. Kepala dapur dapat mengembalikan laporan ke `in_progress` dengan alasan. Tidak ada posting sebagian dalam versi awal: semua baris diselesaikan dan disetujui bersama. Satu MO hanya terhubung ke satu WO; satu baris WO per MO. MO produk sama boleh ada lebih dari satu, dengan biaya dan hasil terpisah secara internal.

Mulai WO harus memeriksa ulang stok, ED, reservasi, gudang, assignment, BOM snapshot, serta kelengkapan seluruh MO di dalamnya. Bahan reservasi dipindahkan ke posisi bahan proses (custody WO), bukan langsung dianggap seluruhnya terpakai. Barang yang baru dalam perjalanan bukan stok siap pakai.

Perubahan dapur produk adalah transaksi: MO belum mulai dipindah dan reservasi gudang lama dilepas lalu dihitung ulang di gudang baru. Barisnya dikeluarkan dari WO lama yang belum mulai; WO kosong dibatalkan. MO berjalan tetap memakai snapshot dapur lama. Penempatan aktif baru hanya berlaku untuk MO berikutnya dan MO belum mulai; riwayat tetap tersimpan.

## 5. Bahan aktual dan pembukuan hasil

Untuk setiap baris WO/MO dan lot bahan:

`bahan diterbitkan = pemakaian aktual + pengembalian + kehilangan bahan yang disetujui`

Tambahan bahan merupakan penerbitan tambahan dan wajib alasan; tidak boleh menciptakan stok negatif atau mengambil barang kedaluwarsa. Pengembalian masuk lot asal dengan ED dan biaya yang sama. Pengembalian yang sudah kedaluwarsa tetap dicatat fisiknya tetapi berstatus blokir, tidak kembali menjadi stok layak pakai. Kehilangan bahan, bila terjadi, dicatat sebagai pemakaian/loss yang menanggung biaya produksi dan tidak digandakan dengan scrap hasil.

Pada persetujuan kepala dapur, dalam satu transaksi: tutup custody bahan, bukukan pengembalian, konsumsi aktual, hasil normal, surplus, scrap output, turunan, biaya, reservasi, dan status WO/MO. Draft laporan belum menambah hasil produksi ke stok. Kirim ulang permintaan persetujuan dengan kunci sama tidak boleh membukukan dua kali.

Untuk tiap MO, dengan target `T` dan seluruh hasil bagus aktual `G`:

- hasil normal `N = min(T, G)`;
- scrap output `S = max(T - G, 0)`, tag tetap “Rusak dalam produksi”;
- surplus `E = max(G - T, 0)`;
- kenaikan stok bagus `N + E = G`;
- produk turunan dicatat di luar rekonsiliasi target produk utama.

Scrap output merupakan catatan kehilangan hasil, bukan penerimaan produk bagus yang kemudian dipotong. Jika operator juga melaporkan rusak fisik pada produksi yang hasil bagusnya melebihi target, gunakan catatan observasi rusak terpisah; jangan mengubah rumus shortfall atau menggandakan scrap otomatis.

## 6. HPP

Per MO/baris WO: `C = biaya bahan aktual bersih + kemasan aktual + overhead BOM`. Saat ini overhead selalu 0. Biaya bahan dihitung dari lot yang benar-benar dikonsumsi; bahan kembali tidak menambah C. Tidak membagi total biaya satu WO secara rata antarproduk yang berbeda.

Jika `G > 0`, HPP unit utama = `C / G`, sama untuk hasil normal dan surplus. Produk turunan tetap Rp0; C seluruhnya dibebankan ke produk utama. Contoh biaya aktual Rp380.000:

| Target | Bagus | Normal | Scrap | Surplus | HPP/unit bagus |
|---|---:|---:|---:|---:|---:|
| 40 | 38 | 38 | 2 | 0 | Rp10.000 |
| 40 | 41 | 40 | 0 | 1 | Rp380.000 / 41 |

Gunakan presisi biaya internal, pembulatan tampilan tidak boleh menghilangkan nilai total; selisih pembulatan dialokasikan deterministik ke keluaran terakhir. Untuk `G = 0`, HPP per unit tidak dihitung; semua target menjadi scrap, C menjadi kerugian produksi dengan persetujuan kepala dapur, stok bagus 0. Ini penanganan teknis agar tidak terjadi pembagian nol.

Valuasi lot bahan mengikuti biaya tercatat sistem sumber. FEFO adalah urutan pengambilan fisik; perubahan menjadi moving average tidak termasuk keputusan modul ini. Transfer membawa nilai lot tanpa menambah laba/biaya. Paket mengonsumsi nilai lot komponen dan kemasan; HPP paket juga dibagi hasil bagus aktual.

## 7. Batch, umur simpan, dan FEFO

Nomor batch yang terlihat = nomor WO; ID lot internal tetap unik karena satu WO dapat menghasilkan banyak produk, surplus, dan turunan. Simpan hubungan WO → baris MO → lot asal → lot hasil. Transfer mempertahankan nomor batch, tanggal produksi, ED, dan biaya.

ED dihitung dengan tanggal kalender lokal Asia/Jakarta dan umur simpan snapshot. Pilihan teknis: produk layak sampai akhir tanggal ED (blokir jika ED < tanggal hari ini). Umur simpan 0 berarti habis pada hari produksi. Umur simpan null tidak dianggap 0 dan menghalangi aktivasi produk hasil produksi sampai dilengkapi.

Hasil dan turunan masing-masing memakai umur simpan SKU-nya. Paket memakai minimum ED semua lot komponen yang benar-benar dikonsumsi, termasuk komponen yang dipasok dari banyak batch; bandingkan dengan tanggal selesai perakitan + umur simpan paket. Jika komponen menjadi kedaluwarsa sebelum perakitan selesai, posting diblokir dan laporan harus dikoreksi.

FEFO: ED terdekat → tanggal penerimaan → ID lot. Periksa saat reservasi, mulai, tambahan bahan, posting, dan pengiriman. Stok kedaluwarsa, terblokir, transit, custody WO lain, atau sudah direservasi MO lain tidak tersedia. Reservasi yang melewati ED harus dilepas/dialokasikan ulang dan status kesiapan dihitung ulang. Lot impor tanpa ED diblokir dari produksi/pengiriman sampai datanya dilengkapi.

## 8. Transfer dan packing

Permintaan bahan dan transfer adalah dokumen berbeda dan saling ditautkan. Permintaan tidak memindahkan stok. Kirim transfer: pindahkan sumber ke transit; terima: transit ke tujuan sesuai jumlah diterima. Selisih tetap tercatat sebagai kasus transit sampai diselesaikan, tidak otomatis dianggap scrap produksi. Penerimaan tidak boleh melebihi jumlah kirim tanpa penyesuaian terpisah yang disetujui.

Packing mempunyai dua alur: transit saja (tanpa MO/WO dan tanpa mengubah ED) atau perakitan paket (MO/WO pada PACK memakai BOM paket tetap). Kirim toko melalui transfer; kirim pelanggan melalui pengeluaran pengiriman yang memiliki referensi pelanggan/pesanan. Keduanya hanya memakai stok hasil yang sudah disetujui dan layak kirim. Tidak membuat ulang modul penjualan dalam cakupan ini.

## 9. Hak akses dan laporan

| Peran/capability | Tindakan |
|---|---|
| Admin/master | Kelola dapur, gudang, produk, penempatan, BOM, umur simpan, dan akses |
| Planner | Susun planning dan MO; ajukan persetujuan; kelompokkan WO per dapur |
| Approver planning | Setujui planning/MO dan perubahan target sebelum mulai |
| Gudang central/dapur | Minta, siapkan, kirim, terima bahan sesuai gudang tugas |
| Operator dapur/packing | Mulai WO berizin; catat pemakaian, tambahan, pengembalian, hasil dan turunan |
| Kepala dapur | Review dan setujui/kembalikan laporan WO untuk dapur tugas |
| Auditor/manajemen | Baca jejak batch, pergerakan, selisih BOM/aktual, scrap, surplus, HPP dan buffer |

Role yang sudah ada dipetakan ke capability; hak gudang/dapur diperiksa server, bukan hanya menyembunyikan tombol. Semua persetujuan menyimpan aktor dan waktu. Dokumen selesai tidak diedit/hapus; koreksi melalui reversal terotorisasi yang menautkan dokumen awal, dengan validasi stok hasil belum dipakai/dikirim; bila sudah dipakai, perlu penyelesaian rantai transaksi.

Laporan minimum: kesiapan produksi per dapur; kebutuhan dan kekurangan bahan; stok/buffer WIP per gudang; bahan rencana vs aktual; hasil target vs bagus/scrap/surplus; keluaran turunan; HPP per produk/WO; expiry; dan pelacakan batch dari penerimaan sampai pelanggan/toko.
