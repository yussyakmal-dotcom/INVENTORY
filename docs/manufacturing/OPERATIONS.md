# Purchasing/PO, stock opname, dan approval scrap

Dikerjakan di branch pengembangan. Belum menggabungkan atau mengaktifkan mode ini pada aplikasi induk/produksi.

## Hak akses

| Tindakan | Admin | Purchasing | Staf Gudang | Approver |
|---|---|---|---|---|
| Lihat dokumen | Semua gudang | Gudang ditugaskan | Gudang ditugaskan | Gudang ditugaskan |
| Tambah/ubah/nonaktifkan supplier | Ya | Ya | Tidak | Tidak |
| Draft/ajukan/batalkan/tutup sisa PO | Ya | Sesuai gudang | Tidak | Tidak |
| Terima barang PO | Ya | Tidak | Sesuai gudang | Tidak |
| Mulai/hitung/batalkan opname, ajukan/batalkan scrap | Ya | Tidak | Sesuai gudang | Tidak |
| Setujui/tolak PO, opname, scrap | Ya | Tidak | Tidak | Sesuai gudang |

Atur penugasan gudang di **Pengguna & akses**, termasuk untuk Purchasing dan Approver. Admin dapat mengajukan dan menyetujui untuk operasi awal; pemisahan dua orang tidak diwajibkan oleh sistem. Akun pembuat dan akun pemberi keputusan dicatat terpisah.

## Purchasing / PO

1. Tambahkan supplier (kode, nama, kontak/alamat, aktif). Supplier lama dapat dinonaktifkan; histori tidak dihapus.
2. Buat PO: nomor unik, tanggal, supplier, Gudang Central, daftar barang, qty beli, satuan beli dari master produk, dan harga per **satuan beli**. Satuan dasar selalu tersedia; satuan alternatif tampil bersama faktor konversinya. Nilai PO adalah jumlah qty beli × harga beli. Pajak, diskon, ongkir, invoice dan pembayaran belum termasuk.
3. Simpan draft. Draft dapat diubah, diajukan, atau dibatalkan. Draft belum menambah stok.
4. Admin/Approver memberi keputusan dengan catatan. PO disetujui tidak dapat diedit; supplier dan produk harus aktif saat pengajuan/persetujuan.
5. Pada PO disetujui, Gudang menerima barang. Catat nomor dokumen supplier, tanggal fisik, petugas penerima, qty, batch, dan ED. Qty nol dilewati; batch/ED wajib untuk baris positif. Barang kedaluwarsa ditolak. Penerimaan bisa memakai satuan beli PO atau satuan dasar. Faktor konversi dari snapshot PO mengubah qty ke satuan dasar. HPP lot = harga satuan beli / faktor konversi, dibulatkan 8 desimal; nilai komersial PO tetap qty beli × harga beli. Selisih pembulatan biaya sangat kecil dapat terjadi bila pembagian tidak habis.
6. Penerimaan sebagian menghasilkan status **Diterima sebagian**, menyimpan tiap kejadian, dan menyisakan qty yang belum dipenuhi. Qty melebihi pesanan dan nomor penerimaan berulang pada PO yang sama ditolak. Satu produk dapat diterima dalam beberapa batch melalui beberapa penerimaan atau beberapa baris API.
7. Seluruh barang diterima → **Diterima seluruhnya**. Untuk sisa pesanan yang tidak dilanjutkan, pilih **Tutup sisa PO** dan isi alasan. Penutupan tidak mengubah stok atau menghapus sisa historis.

Penolakan/batal tidak memindahkan stok. PO yang ditolak dibuat ulang dengan nomor baru. Mutasi penerimaan mengacu nomor PO dan dokumen supplier. Penerimaan langsung pada menu Stok tetap tersedia untuk transaksi tanpa PO; tidak otomatis mengurangi sisa PO.

## Stock opname

1. Pilih gudang, isi nomor/tanggal, lalu **Mulai hitung & kunci gudang**. Sistem mengambil saldo seluruh lot yang tercatat pada gudang (termasuk saldo nol) sebagai snapshot.
2. Selama opname berstatus Draft/Menunggu persetujuan, penerimaan, pemakaian, pengiriman keluar, penerimaan transfer, dan pengajuan scrap pada gudang tersebut ditolak server. Pengiriman dari gudang lain menuju gudang ini tetap boleh berada dalam transit, tetapi belum bisa diterima. Gudang lain tetap beroperasi.
3. Setiap lot wajib diisi qty fisiknya, termasuk nol. Tidak ada default yang dianggap sudah dihitung. Selisih dihitung terhadap snapshot, bukan saldo yang dikirim browser.
4. Barang yang ditemukan tetapi batchnya belum tercatat ditambahkan melalui **Tambah lot temuan** dengan produk, batch, ED, qty fisik dan HPP. Barang kedaluwarsa boleh dicatat sebagai fisik, tetapi tidak layak FEFO. Lot temuan diberi identitas internal sendiri saat disetujui.
5. Isi nama petugas dan alasan/catatan, lalu ajukan. Sebelum disetujui saldo tetap sama dan gudang tetap terkunci.
6. Admin/Approver memeriksa selisih dan HPP temuan. **Setujui** memposting selisih ke lot yang sesuai, membuat lot temuan, mencatat mutasi `OPNAME`, dan membuka kunci gudang secara atomik. **Tolak** atau **Batalkan** membuka kunci tanpa mengubah saldo. Untuk koreksi hasil yang ditolak, mulai opname baru.

Selesaikan scrap tertunda sebelum memulai opname. Tanggal dokumen dapat berbeda dari waktu sistem, tetapi snapshot selalu diambil saat mulai; ini bukan rekonstruksi saldo historis. Tidak ada perubahan HPP lot lama. Pengubahan kategori/satuan yang memengaruhi dokumen terkait dibatasi oleh master produk.

## Scrap stok

1. Pilih gudang dan lot, isi qty serta alasan kerusakan/kedaluwarsa. Lot kedaluwarsa/diblokir juga dapat diajukan scrap.
2. Pengajuan menahan qty dari pemakaian dan pengiriman FEFO. Stok fisik belum berkurang; halaman Stok menampilkan **Ditahan scrap** dan **Tersedia**.
3. Admin/Approver menyetujui dengan catatan: saldo dikurangi dan mutasi `SCRAP` dicatat pada lot/HPP asal. Permintaan berulang tidak memposting dua kali.
4. Penolakan/pembatalan melepas penahanan tanpa mutasi stok.

Ini adalah scrap barang yang sudah ada dalam stok. Scrap hasil produksi tetap mengikuti modul WO yang akan dikembangkan; tidak dihitung sebagai pengurangan ganda dari hasil baik.

## Integritas dan pengujian

Semua perintah melalui gate transaksi database. Setiap dokumen memiliki revision, nomor unik, identitas pembuat/pemberi keputusan, timestamp sistem, serta audit. Request idempotency key yang sama mengembalikan hasil semula. Perubahan dari form lama ditolak. Dokumen historis tidak dihapus; gudang dengan dokumen terkait dan satuan produk yang sudah digunakan dilindungi.

Model schema 6: `inv_suppliers`, `inv_operations`. Header memakai foreign key ke gudang/supplier; detail tervalidasi dan snapshot nama/satuan/harga disimpan dalam dokumen JSON, sesuai pola BOM fondasi. Transaksi/supplier dari arsip lama belum diimpor ulang.

Pengujian mencakup PO draft/persetujuan/penolakan, penerimaan parsial/penuh/berlebih, rollback penerimaan tidak valid, idempotency, penutupan sisa PO, kunci opname, lot temuan kedaluwarsa, penahanan scrap, pembatalan/penolakan, persetujuan bersamaan, scope gudang, dan proteksi master. Browser menguji supplier → PO → terima sebagian/penuh → scrap → opname dengan lot temuan.

## Satuan pada PO

Contoh: satuan dasar kg, konversi sak=25. Pesan 2 sak seharga Rp300.000/sak: total PO Rp600.000, setara 50 kg, HPP Rp12.000/kg. Penerimaan pertama 1 sak menambah 25 kg; berikutnya bisa 1 sak atau 25 kg. Sisa/kelebihan diperiksa dalam satuan dasar.

UI menampilkan Qty beli, Satuan beli, Harga/satuan beli, dan Setara stok dasar. Perubahan produk/satuan mengosongkan harga agar harga satuan sebelumnya tidak terbawa tanpa diperiksa. PO menyimpan `purchase_uom`, `conversion_factor`, `purchase_qty`, `purchase_price`; `qty`/`unit_price`/`received_qty` tetap dalam satuan dasar untuk kompatibilitas. PO lama tanpa field ini dibaca dengan faktor 1 dan satuan dasar, tanpa perubahan saldo. API save-po menerima qty/harga dalam purchase_uom; receive-po menerima uom pilihan PO atau dasar (jika uom tidak dikirim, default dasar).
