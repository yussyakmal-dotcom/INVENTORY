# Modul manufaktur INVENTORY

Versi 1.0 · 28 Oktober 2026 · spesifikasi untuk implementasi, belum merupakan fitur yang berjalan.

Dokumen ini merangkum keputusan Yusi dalam pembahasan modul manufaktur INVENTORY. Ketentuan bisnis yang disetujui dipisahkan dari pilihan teknis agar pengembang tidak menganggap rancangan teknis sebagai perubahan aturan bisnis.

| Dokumen | Isi |
|---|---|
| [PRD](PRD.md) | Aturan bisnis, hitungan stok/HPP, status, hak akses, dan contoh |
| [Struktur database](schema.dbml) | Rancangan relasi dan kolom database, bukan migrasi siap dijalankan |
| [Alur layar](SCREENS.md) | Menu, formulir, tindakan, dan validasi yang dilihat pengguna |
| [Implementasi dan penerimaan](IMPLEMENTATION.md) | Transaksi server, migrasi dari MVP, tahapan kerja, dan skenario uji |

## Cakupan

10 dapur D01–D10 dengan gudang masing-masing; packing terpisah; BOM produksi dan paket; planning dari pesanan, toko, dan buffer WIP; MO; WO per dapur dengan banyak produk; reservasi; permintaan bahan central; bahan aktual dan pengembalian; scrap; surplus; produk turunan; HPP; nomor batch WO; umur simpan dan FEFO.

## Kondisi aplikasi saat spesifikasi disusun

Versi repository yang ditinjau: `ae002ed6e399ca02069c82b06dee6fc30a6aff91`.
Backend sekarang menyimpan data operasional dalam `app_state` JSON. Aturan stok dan FIFO terutama berada di `app/static/index.html`; backend memiliki autentikasi dan penyimpanan state ber-versi. Tabel pada DBML adalah target arsitektur, tidak menggambarkan tabel yang sudah tersedia.

Implementasi perlu memindahkan kendali stok ke server dan menyatukan sumber data stok. Jangan menjalankan stok manufaktur dalam tabel baru sementara transfer lama masih menulis stok terpisah di JSON.
