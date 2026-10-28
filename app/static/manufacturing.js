'use strict';
let catalog, setup, stock = [], transfers = [], movements = [], users = [], accesses = [];
let operations={suppliers:[],documents:[]},selectedOperation=null,editPo=null,editSupplier=null,poLines=[{}],opnameExtras=[],scrapLines=[{}],scrapWarehouse=null;
let tab = 'setup', editProduct = null, editBom = null, busy = false;
let editWarehouse = null, editKitchen = null;
let selectedTransfer = null, shipmentLines = [{}], savedShipment = null;
const localToday = () => new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Jakarta',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
let bomMaterials = [], bomByproducts = [], bomOverheads = [];
const $ = s => document.querySelector(s);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const nameOf = (items, id) => items.find(p => p.id === Number(id))?.name || `#${id}`;
const kinds = {raw:'Bahan baku',packaging:'Kemasan',wip:'WIP',finished:'Produk jadi',package:'Produk jadi · Paket',byproduct:'Produk turunan'};
const isAdmin = () => catalog?.user.role === 'admin';
const canWrite = () => ['admin','gudang'].includes(catalog?.user.role);
const options = (items, selected, blank = 'Pilih…') => `<option value="">${esc(blank)}</option>` + items.map(p => `<option value="${p.id}" ${Number(selected) === p.id ? 'selected' : ''}>${esc(p.code ? p.code+' · '+p.name : p.name)}</option>`).join('');
const select = (name, items, selected, required = true) => `<select name="${name}" ${required?'required':''}>${options(items,selected)}</select>`;
const field = (title, html) => `<label>${title}${html}</label>`;
const input = (name, value = '', type = 'text', extra = '') => `<input name="${name}" type="${type}" value="${esc(value)}" ${extra}>`;
const qtyInput = (name, value = '') => input(name,value,'number','min="0.000001" step="0.000001" required');
const table = (heads, rows) => `<div class="scroll"><table><thead><tr>${heads.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('') || `<tr><td colspan="${heads.length}" class="empty">Belum ada data.</td></tr>`}</tbody></table></div>`;
const writableWarehouses = () => catalog.warehouses.filter(w => w.active && (catalog.warehouse_access === null || catalog.warehouse_access.includes(w.id)));
const products = () => catalog.products.filter(p=>p.active);
function message(text, error = false) { $('#message').textContent = text; $('#message').className = error ? 'error' : ''; }
async function api(path, body, key) {
  const response = await fetch(path,{method:body === undefined?'GET':'POST',credentials:'same-origin',headers:body === undefined?{}:{'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},body:body === undefined?undefined:JSON.stringify(body)});
  const data = await response.json();
  if(response.status===401){location.href='/';throw Error('Silakan masuk kembali.');}
  if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:`Permintaan gagal (${response.status}).`);
  return data;
}
function requestKey(){return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;}
async function command(operation, body, form) {
  // A transport failure retains the same key on the form for a safe retry.
  const encoded=JSON.stringify(body);
  if(form && form.dataset.payload!==encoded){form.dataset.key=requestKey();form.dataset.payload=encoded;}
  const result=await api(`/api/manufacturing/commands/${operation}`,body,form?.dataset.key || requestKey());
  if(form){delete form.dataset.key;delete form.dataset.payload;}
  return result;
}
async function refresh() {
  [catalog,setup]=await Promise.all([api('/api/manufacturing/catalog'),api('/api/manufacturing/setup')]);
  if(catalog.active){
    [stock,transfers,movements]=await Promise.all([api('/api/manufacturing/stock'),api('/api/manufacturing/transfers'),api('/api/manufacturing/movements')]);
    operations=await api('/api/manufacturing/operations');
    if(isAdmin()) [users,accesses]=await Promise.all([api('/api/users'),api('/api/manufacturing/access')]);
  }
  $('#identity').innerHTML=`${esc(catalog.user.name)}<br><button data-action="logout">Keluar</button>`;
}
function render() {
  $('#do-print')?.remove();
  const menu=[['setup','Persiapan'],['kitchens','Dapur'],['products','Produk'],['boms','BOM'],['stock','Stok & pemakaian'],['transfers','Transfer'],['purchasing','Purchasing / PO'],['opname','Opname'],['scrap','Scrap'],['movements','Riwayat']];
  if(isAdmin())menu.push(['access','Pengguna & akses']);
  $('#navigation').innerHTML=menu.map(([id,title])=>`<button data-tab="${id}" ${id===tab?'aria-current="page"':''} ${!catalog.active && !['setup','kitchens'].includes(id)?'disabled':''}>${title}</button>`).join('');
  const renders={purchasing:renderPurchasing,opname:renderOpname,scrap:renderScrap,setup:renderSetup,kitchens:renderKitchens,products:renderProducts,boms:renderBoms,stock:renderStock,transfers:renderTransfers,movements:renderMovements,access:renderAccess};
  $('#content').innerHTML=renders[tab]();
  syncKitchen();
  receiptUnitOptions();
}
function syncKitchen(){
 const f=document.querySelector('[data-form=product]');if(!f)return;
 const enabled=['finished','package'].includes(f.elements.kind.value);
 f.elements.kitchen_id.disabled=!enabled;f.elements.kitchen_id.required=enabled;
 f.elements.kitchen_id.closest('label').hidden=!enabled;
 if(!enabled)f.elements.kitchen_id.value='';
}
function renderSetup(){
  if(catalog.active)return `<section><h2>Fondasi server aktif</h2><p>Stok, transfer, produk dan BOM kini dicatat melalui halaman ini. Data aplikasi sebelumnya tersimpan sebagai arsip.</p><div class="grid"><div><span class="stat">${catalog.kitchens.length}</span><p class="muted">Dapur termasuk packing</p></div><div><span class="stat">${catalog.products.length}</span><p class="muted">Produk</p></div><div><span class="stat">${catalog.boms.filter(b=>b.status==='active').length}</span><p class="muted">BOM aktif</p></div></div><div class="notice">Tahap ini menyediakan master dan stok dasar. Planning/MO/WO, hasil produksi, perakitan paket dan pengiriman pelanggan belum tersedia di layar baru. Riwayat lama tetap tersimpan.</div>${isAdmin()?'<button data-action="archive">Unduh arsip sebelum migrasi</button>':''}</section>`;
  if(!isAdmin())return '<section><h2>Persiapan manufaktur</h2><p>Admin belum mengaktifkan fondasi. Aplikasi inventori lama masih dapat dipakai.</p><a href="/">Kembali ke inventori</a></section>';
  const p=setup.preview;
  return `<section><h2>Persiapan manufaktur</h2><p>Dapur dan tabel baru sudah disiapkan. Data operasional lama belum dipindahkan.</p><div class="notice">Aktivasi memindahkan saldo ke server dan mengunci perubahan pada aplikasi lama. Setelah aktivasi, gunakan layar ini untuk master, penerimaan, pemakaian, dan transfer. Planning/MO/WO, hasil produksi dan perakitan paket belum tersedia di mode baru. Lakukan pada salinan pengujian terlebih dahulu.</div><div class="grid"><div><span class="stat">${p.products}</span><p class="muted">Produk lama</p></div><div><span class="stat">${p.lots}</span><p class="muted">Lot bersaldo</p></div><div><span class="stat">${esc(p.stock_value)}</span><p class="muted">Nilai stok sumber</p></div></div>${p.missing_expiry?`<p class="danger">${p.missing_expiry} lot tanpa ED akan diblokir sampai tanggalnya dilengkapi.</p>`:''}${p.blockers.length?`<h3>Perlu diselesaikan pada aplikasi lama</h3><ul>${p.blockers.map(s=>`<li>${esc(s)}</li>`).join('')}</ul>`:'<p>Transaksi sumber siap untuk dipindahkan.</p>'}<form data-form="activate"><label><input type="checkbox" name="ack" required> Saya sudah membuat backup database dan memahami perubahan mode aplikasi.</label><div class="actions"><button class="primary" ${p.blockers.length?'disabled':''}>Aktifkan fondasi server</button><a href="/">Kembali ke inventori lama</a></div></form></section>`;
}
const warehouseKinds = {central:'Central',store:'Toko',kitchen:'Gudang dapur',packing:'Gudang packing'};
function locationActions(type, item){return isAdmin()?`<button data-action="edit-${type}" data-id="${item.id}">Ubah</button> <button data-action="delete-${type}" data-id="${item.id}">Hapus</button>`:'';}
function locationForm(type, item){
  const kitchen=type==='kitchen', title=kitchen?'dapur':'gudang';
  const types=kitchen?{production:'Produksi',packing:'Packing'}:warehouseKinds;
  return `<section><h3>${item?'Ubah':'Tambah'} ${title}</h3><form data-form="${type}"><div class="grid">${field('Kode',input('code',item?.code,'text',`required maxlength="${kitchen?10:50}"`))}${field('Nama',input('name',item?.name,'text',`required maxlength="${kitchen?100:200}"`))}${field('Jenis',`<select name="kind">${Object.entries(types).map(([v,l])=>`<option value="${v}" ${item?.kind===v?'selected':''}>${l}</option>`).join('')}</select>`)}${kitchen?field('Gudang milik dapur',select('warehouse_id',catalog.warehouses.filter(w=>w.active&&['kitchen','packing'].includes(w.kind)&&!catalog.kitchens.some(k=>k.warehouse_id===w.id&&k.id!==item?.id)),item?.warehouse_id)):''}</div>${!kitchen?`<p><label><input type="checkbox" name="active" ${item?.active!==false?'checked':''}> Gudang aktif</label></p>`:''}<div class="actions"><button class="primary">Simpan ${title}</button>${item?`<button type="button" data-action="cancel-${type}">Batal ubah</button>`:''}</div></form></section>`;
}
function renderKitchens(){
  const k=catalog.kitchens.find(x=>x.id===editKitchen),w=catalog.warehouses.find(x=>x.id===editWarehouse);
  return `<section><h2>Dapur & gudang</h2><p class="muted">Setiap dapur memiliki satu gudang sendiri. Buat gudang berjenis Gudang dapur atau Gudang packing, lalu pilih saat menambah dapur. Status operasional dapur mengikuti status gudangnya.</p>${table(['Kode','Nama dapur','Jenis','Gudang','Produk jadi',''],catalog.kitchens.map(k=>`<tr class="kitchen"><td>${esc(k.code)}</td><td>${esc(k.name)}</td><td>${k.kind==='packing'?'Packing':'Produksi'}</td><td>${esc(nameOf(catalog.warehouses,k.warehouse_id))}${catalog.warehouses.find(w=>w.id===k.warehouse_id)?.active?'':' (Nonaktif)'}</td><td>${catalog.products.filter(p=>p.kitchen_id===k.id).length}</td><td>${locationActions('kitchen',k)}</td></tr>`))}</section>${isAdmin()?locationForm('kitchen',k):''}<section><h2>Master gudang</h2><p class="muted">Hapus hanya tersedia untuk data yang belum digunakan. Gudang tanpa stok dan transfer berjalan dapat dinonaktifkan setelah produk aktif dipindahkan.</p>${table(['Kode','Nama gudang','Jenis','Status',''],catalog.warehouses.map(w=>`<tr><td>${esc(w.code)}</td><td>${esc(w.name)}</td><td>${esc(warehouseKinds[w.kind]||w.kind)}</td><td>${w.active?'Aktif':'Nonaktif'}</td><td>${locationActions('warehouse',w)}</td></tr>`))}</section>${isAdmin()?locationForm('warehouse',w):''}`;
}
function renderProducts(){
  const p=catalog.products.find(p=>p.id===editProduct);
  let form='';
  if(isAdmin())form=`<section><h3>${p?'Ubah produk':'Produk baru'}</h3><form data-form="product"><div class="grid">${field('Kode',input('code',p?.code,'text','required maxlength="50"'))}${field('Nama',input('name',p?.name,'text','required maxlength="200"'))}${field('Kategori / jenis',`<select name="kind">${Object.entries(kinds).map(([v,l])=>`<option value="${v}" ${p?.kind===v?'selected':''}>${l}</option>`).join('')}</select>`)}${field('Satuan dasar',input('base_uom',p?.base_uom||'pcs','text','required maxlength="20"'))}${field('Konversi satuan (sak=25; dus=10)',input('uoms',Object.entries(p?.uoms||{}).map(([k,v])=>`${k}=${v}`).join('; ')))}${field('Umur simpan (hari)',input('shelf_life_days',p?.shelf_life_days??'','number','min="0" step="1"'))}${field('Dapur produksi aktif',select('kitchen_id',catalog.kitchens,p?.kitchen_id,false))}${field('Harga jual',input('selling_price',p?.selling_price||0,'number','min="0" step="0.01"'))}${field('Alasan perubahan dapur',input('change_reason'))}</div><label><input name="discrete" type="checkbox" ${p?.discrete?'checked':''}> Jumlah dalam satuan dasar harus bulat</label><p><label><input name="active" type="checkbox" ${p?.active!==false?'checked':''}> Produk aktif</label></p><div class="actions"><button class="primary">Simpan produk</button>${p?'<button type="button" data-action="cancel-product">Batal ubah</button>':''}</div></form></section>`;
  return `<section><h2>Master produk</h2><p class="muted">Hanya produk jadi memiliki penetapan dapur. BOM hanya untuk Produk jadi dan WIP. Paket termasuk produk jadi. Harga jual produk turunan terpisah dari HPP nolnya.</p>${table(['Kode / produk','Jenis','Satuan','Umur simpan','Dapur',''],catalog.products.map(p=>`<tr><td>${esc(p.code)}<br><strong>${esc(p.name)}</strong>${!p.active?'<small>Nonaktif</small>':''}</td><td>${esc(kinds[p.kind])}</td><td>${esc(p.base_uom)}</td><td>${p.shelf_life_days===null?'Belum diisi':p.shelf_life_days+' hari'}</td><td>${esc(p.kitchen_id?nameOf(catalog.kitchens,p.kitchen_id):'—')}</td><td>${isAdmin()?`<button data-action="edit-product" data-id="${p.id}">Ubah</button>`:''}</td></tr>`))}</section>${form}`;
}
function bomLineRows(lines,kind){return lines.map((m,i)=>`<tr><td><select name="${kind}-product-${i}" required>${options(products().filter(p=>kind!=='byproduct'||p.kind==='byproduct'),m.product_id)}</select></td><td>${qtyInput(`${kind}-qty-${i}`,m.qty||'')}</td>${kind==='material'?`<td>${input(`${kind}-uom-${i}`,m.uom||'','text','placeholder="Satuan dasar jika kosong"')}</td>`:''}<td><button type="button" data-action="remove-${kind}" data-id="${i}">Hapus</button></td></tr>`).join('');}
function renderBoms(){
  const b=catalog.boms.find(b=>b.id===editBom);
  return `<section><h2>BOM & versi resep</h2><p class="muted">Resep untuk hasil standar; overhead Rp0 dan produk turunan HPP Rp0. BOM aktif tidak dapat diedit: buat versi baru.</p>${table(['Produk','Versi','Hasil standar','Status',''],catalog.boms.map(b=>`<tr><td>${esc(nameOf(catalog.products,b.product_id))}</td><td>${b.version}</td><td>${esc(b.output_qty)}</td><td><span class="chip ${b.status==='draft'?'warn':''}">${esc(b.status)}</span></td><td><button data-action="simulate" data-id="${b.id}">Hitung kebutuhan</button> ${isAdmin()?`<button data-action="edit-bom" data-id="${b.id}">${b.status==='draft'?'Ubah draft':'Salin ke versi baru'}</button> ${b.status==='draft'?`<button data-action="activate-bom" data-id="${b.id}">Aktifkan</button>`:''}`:''}</td></tr>`))}<div id="simulation"></div></section>${isAdmin()?`<section><h3>${b?'Ubah draft versi '+b.version:'BOM baru'}</h3><form data-form="bom"><div class="grid">${field('Produk hasil',select('product_id',products().filter(p=>['wip','finished','package'].includes(p.kind)),b?.product_id))}${field('Hasil standar (satuan dasar)',qtyInput('output_qty',b?.output_qty||''))}</div><h3>Bahan & kemasan</h3>${table(['Produk','Qty per resep','Satuan',''],[bomLineRows(bomMaterials,'material')])}<button type="button" data-action="add-material">Tambah bahan</button><h3 style="margin-top:24px">Produk turunan · HPP Rp0</h3>${table(['Produk turunan','Perkiraan hasil (satuan dasar)',''],[bomLineRows(bomByproducts,'byproduct')])}<button type="button" data-action="add-byproduct">Tambah turunan</button><h3 style="margin-top:24px">Overhead · Rp0</h3>${table(['Nama biaya','Nilai',''],bomOverheads.map((o,i)=>`<tr><td>${input('overhead-name-'+i,o.name,'text','required')}</td><td>Rp0</td><td><button type="button" data-action="remove-overhead" data-id="${i}">Hapus</button></td></tr>`))}<button type="button" data-action="add-overhead">Tambah overhead</button><div class="actions"><button class="primary">Simpan draft BOM</button><button type="button" data-action="cancel-bom">Bersihkan form</button></div></form></section>`:''}`;
}
function renderStock(){
  const rows=stock.map(s=>`<tr><td>${esc(nameOf(catalog.products,s.product_id))}</td><td>${esc(nameOf(catalog.warehouses,s.warehouse_id))}</td><td>${esc(s.batch_number)}</td><td>${esc(s.qty)} ${esc(catalog.products.find(p=>p.id===s.product_id)?.base_uom)}${Number(s.reserved_scrap)>0?`<small>Ditahan scrap: ${esc(s.reserved_scrap)} · Tersedia: ${esc(s.available_qty)}</small>`:''}</td><td>${esc(s.expiry_date||'Belum diisi')}</td><td><span class="chip ${s.usable?'':'warn'}">${s.usable?'Layak pakai':'Diblokir / kedaluwarsa'}</span></td><td>${esc(s.unit_cost)}${isAdmin()&&!s.expiry_date?`<br><button data-action="correct-lot" data-id="${s.lot_id}">Lengkapi ED</button>`:''}</td></tr>`);
  return `<section><h2>Stok per gudang & lot</h2><p class="muted">FEFO memilih lot dengan kedaluwarsa terdekat. Semua jumlah menggunakan satuan dasar produk.</p>${table(['Produk','Gudang','Batch','Qty','ED','Status','HPP/unit'],rows)}</section>${canWrite()?`<section><h3>Penerimaan pembelian</h3><form data-form="receipt"><div class="grid">${field('Gudang Central',select('warehouse_id',writableWarehouses().filter(w=>w.kind==='central')))}${field('Produk',select('product_id',products()))}${field('Qty terima',qtyInput('qty'))}${field('Satuan terima','<select name="uom" required><option value="">Pilih produk dahulu</option></select>')}${field('Batch pemasok',input('batch_number','','text','required maxlength="100"'))}${field('Kedaluwarsa',input('expiry_date','','date','required'))}${field('Harga per satuan terima',input('unit_cost','','number','required min="0" step="0.00000001"'))}${field('Referensi dokumen',input('reference','','text','required maxlength="150"'))}</div><p id="receipt-conversion" class="muted">Pilih produk dan satuan untuk melihat konversi stok.</p><button class="primary">Catat penerimaan</button></form></section><section><h3>Pemakaian bahan dasar</h3><p class="muted">Untuk pemakaian inventori saat ini. Pemakaian untuk WO dan hasil produksi akan tersedia pada tahap eksekusi manufaktur.</p><form data-form="usage"><div class="grid">${field('Gudang',select('warehouse_id',writableWarehouses()))}${field('Produk',select('product_id',products()))}${field('Qty satuan dasar',qtyInput('qty'))}${field('Alasan/referensi',input('reference','','text','required maxlength="150"'))}</div><button class="primary">Catat pemakaian FEFO</button></form></section>`:''}`;
}
function renderTransferReceipt(){
  const t=transfers.find(t=>t.id===selectedTransfer);if(!t)return '<p>Pilih nomor dokumen kirim untuk menampilkan barang.</p>';
  const allowed=canWrite()&&writableWarehouses().some(w=>w.id===t.destination_id)&&!['received','closed'].includes(t.status);
  return `<div class="card"><h3>${esc(t.document_number)}</h3><p>Petugas pengirim: <strong>${esc(t.sender_name||'Belum tercatat')}</strong><br>Kendaraan: <strong>${esc(t.vehicle_number||'Belum tercatat')}</strong><br>Tanggal kirim: <strong>${esc(t.shipped_date)}</strong><br>${esc(nameOf(catalog.warehouses,t.source_id))} → ${esc(nameOf(catalog.warehouses,t.destination_id))}<br>Status: ${esc(t.status)}</p>${t.legacy?'<p class="muted">Dokumen lama: nomor TRF dan tanggal kirim berasal dari pencatatan sistem. Tanggal penerimaan sebelum pembaruan ini belum dicatat terpisah.</p>':''}<form data-form="receive-transfer" data-transfer="${t.id}">${field('Tanggal terima sesuai penerimaan fisik',input('received_date',localToday(),'date',`required min="${t.shipped_date}" max="${localToday()}" ${allowed?'':'disabled'}`))}${field('Nama petugas penerima',input('receiver_name','','text',`required maxlength="150" ${allowed?'':'disabled'}`))}${table(['Barang / batch','Satuan','Qty kirim','Sudah diterima','Sisa kiriman','Qty terima sekarang','Satuan terima'],t.lines.map(l=>`<tr><td>${esc(l.product_code)} · ${esc(l.product_name)}<small>Batch ${esc(l.batch_number)} · ED ${esc(l.expiry_date||'—')}</small></td><td>${esc(l.uom)}</td><td>${esc(l.shipped_qty)}</td><td>${esc(l.received_qty)}</td><td>${esc(l.remaining)}</td><td>${input('line-'+l.id,l.remaining,'number',`required min="0" step="0.000001" ${allowed?'':'disabled'}`)}</td><td>${snapshotUnitSelect('transfer-uom-'+l.id,l.units,l.uom,l.uom,!allowed)}</td></tr>`))}${allowed?'<p class="muted">Qty terima otomatis sama dengan sisa kiriman dalam satuan dasar. Satuan alternatif memakai konversi saat kirim; pilih satuan lalu isi qty fisik; kekurangan tetap tercatat dalam perjalanan.</p><button class="primary">Konfirmasi penerimaan</button>':''}</form><h3>Riwayat penerimaan</h3>${table(['Tanggal terima','Petugas penerima','Barang / batch','Qty terima'],t.receipts.flatMap(r=>r.lines.map(l=>{const item=t.lines.find(x=>x.id===l.id);return `<tr><td>${esc(r.received_date)}</td><td>${esc(r.receiver_name||'Belum tercatat')}</td><td>${esc(item?.product_name)} · ${esc(item?.batch_number)}</td><td>${esc(l.input_qty??l.qty)} ${esc(l.input_uom||item?.uom)}<small>Stok: ${esc(l.qty)} ${esc(item?.uom)}</small></td></tr>`;})))}</div>`;
}
function printDeliveryOrder(id){
  const t=transfers.find(t=>t.id===id);if(!t)throw Error('Dokumen tidak ditemukan.');
  let area=$('#do-print');if(!area){area=document.createElement('article');area.id='do-print';document.body.append(area);}
  area.className='';
  area.innerHTML=`<h1>DELIVERY ORDER (DO)</h1><h2>${esc(t.document_number)}</h2><div class="do-meta"><p><strong>Tanggal kirim:</strong> ${esc(t.shipped_date)}<br><strong>Gudang asal:</strong> ${esc(nameOf(catalog.warehouses,t.source_id))}<br><strong>Gudang tujuan:</strong> ${esc(nameOf(catalog.warehouses,t.destination_id))}</p><p><strong>Petugas pengirim:</strong> ${esc(t.sender_name||'Belum tercatat')}<br><strong>Nomor kendaraan:</strong> ${esc(t.vehicle_number||'Belum tercatat')}</p></div>${t.shipment_units?`<p>${Object.entries(t.shipment_units).map(([pid,u])=>esc(nameOf(catalog.products,pid))+': '+esc(u.qty)+' '+esc(u.uom)+' = '+esc(u.base_qty)+' '+esc(u.base_uom)).join('<br>')}</p>`:''}${table(['No.','Kode / barang','Batch / ED','Satuan','Qty kirim'],t.lines.map((l,i)=>`<tr><td>${i+1}</td><td>${esc(l.product_code)}<br>${esc(l.product_name)}</td><td>${esc(l.batch_number)}<br>${esc(l.expiry_date||'—')}</td><td>${esc(l.uom)}</td><td>${esc(l.shipped_qty)}</td></tr>`))}<div class="do-signatures"><div><p>Petugas pengirim</p><div class="signature-space"></div><p>${esc(t.sender_name||'________________________')}</p></div><div><p>Petugas penerima</p><div class="signature-space"></div><p>Nama: ________________________<br>Tanggal: ______________________</p></div></div>${t.receipts.length?`<h3>Riwayat penerimaan tercatat</h3>${table(['Tanggal terima','Petugas penerima','Barang / batch','Qty terima'],t.receipts.flatMap(r=>r.lines.map(l=>{const item=t.lines.find(x=>x.id===l.id);return `<tr><td>${esc(r.received_date)}</td><td>${esc(r.receiver_name||'Belum tercatat')}</td><td>${esc(item?.product_name)} · ${esc(item?.batch_number)}</td><td>${esc(l.input_qty??l.qty)} ${esc(l.input_uom||item?.uom)}<small>Stok: ${esc(l.qty)} ${esc(item?.uom)}</small></td></tr>`;})))}`:''}<p class="do-note">Dicetak dari dokumen pengiriman yang tersimpan. Qty kirim tetap menunjukkan jumlah pengiriman awal.</p>`;
  window.print();
}
function snapshotUnitSelect(name,units,base,selected,disabled=false){return `<select name="${name}" required ${disabled?'disabled':''}>${Object.entries(units).map(([u,f])=>`<option value="${esc(u)}" ${u===selected?'selected':''}>${esc(u)}${u===base?' (dasar)':' = '+esc(f)+' '+esc(base)}</option>`).join('')}</select>`;}
function shipmentRows(){return table(['Barang','Qty kirim','Satuan kirim','Setara stok dasar',''],shipmentLines.map((l,i)=>{
 const p=catalog.products.find(p=>p.id===l.product_id),u=l.uom||p?.base_uom;
 return `<tr><td>${select('ship-product-'+i,products(),l.product_id)}</td><td>${qtyInput('ship-qty-'+i,l.qty||'')}</td><td>${p?snapshotUnitSelect('ship-uom-'+i,poUnits(p),p.base_uom,u):'<small>Pilih barang dahulu</small>'}</td><td id="ship-conversion-${i}">${p&&l.qty?esc(Number(l.qty)*Number(poUnits(p)[u]))+' '+esc(p.base_uom):'—'}</td><td><button type="button" data-action="shipment-remove" data-id="${i}">Hapus baris</button></td></tr>`;
}));}
function collectShipment(){
 const f=$('[data-form=ship]');if(!f)return;
 const d=new FormData(f);shipmentLines=shipmentLines.map((_,i)=>({product_id:Number(d.get('ship-product-'+i)),qty:d.get('ship-qty-'+i),uom:d.get('ship-uom-'+i)}));
}
function shipmentPreview(i){const f=$('[data-form=ship]');const p=catalog.products.find(p=>p.id===Number(f?.elements['ship-product-'+i]?.value));if(!p)return;const u=f.elements['ship-uom-'+i].value,q=f.elements['ship-qty-'+i].value;$('#ship-conversion-'+i).textContent=q?`${Number(q)*Number(poUnits(p)[u])} ${p.base_uom}`:'—';}
function receiptUnitOptions(){const f=$('[data-form=receipt]');if(!f)return;const p=catalog.products.find(p=>p.id===Number(f.elements.product_id.value));f.elements.uom.innerHTML=p?Object.entries(poUnits(p)).map(([u,v])=>`<option value="${esc(u)}">${esc(u)}${u===p.base_uom?' (dasar)':' = '+esc(v)+' '+esc(p.base_uom)}</option>`).join(''):'<option value="">Pilih produk dahulu</option>';receiptPreview();}
function receiptPreview(){const f=$('[data-form=receipt]');if(!f)return;const p=catalog.products.find(p=>p.id===Number(f.elements.product_id.value)),out=$('#receipt-conversion');if(!p){out.textContent='Pilih produk dan satuan untuk melihat konversi stok.';return;}const u=f.elements.uom.value,factor=Number(poUnits(p)[u]),qty=Number(f.elements.qty.value),price=Number(f.elements.unit_cost.value);out.textContent=`${qty} ${u} = ${qty*factor} ${p.base_uom} · Harga per ${u} · HPP/dasar: ${Number((price/factor).toFixed(8))} / ${p.base_uom}`;}
function renderTransfers(){return `<section><h2>Penerimaan transfer</h2>${field('Panggil nomor dokumen kirim',`<select id="transfer-document">${options(transfers.map(t=>({id:t.id,name:t.document_number+' · '+t.shipped_date+' · '+nameOf(catalog.warehouses,t.destination_id)})),selectedTransfer,'Pilih nomor dokumen kirim…')}</select>`)}<div id="transfer-detail">${renderTransferReceipt()}</div></section><section><h2>Daftar pengiriman</h2>${table(['No. dokumen kirim','Tanggal kirim','Asal','Tujuan','Status'],transfers.map(t=>`<tr><td><button data-action="open-transfer" data-id="${t.id}">${esc(t.document_number)}</button></td><td>${esc(t.shipped_date)}</td><td>${esc(nameOf(catalog.warehouses,t.source_id))}</td><td>${esc(nameOf(catalog.warehouses,t.destination_id))}</td><td>${esc(t.status)}</td></tr>`))}</section>${canWrite()?`<section><h3>Kirim barang</h3><form data-form="ship"><div class="grid">${field('Nama petugas pengirim',input('sender_name','','text','required maxlength="150"'))}${field('Nomor kendaraan pengirim',input('vehicle_number','','text','required maxlength="50"'))}${field('Nomor dokumen kirim',input('document_number','','text','required maxlength="150"'))}${field('Tanggal kirim',input('shipped_date',localToday(),'date',`required max="${localToday()}"`))}${field('Gudang asal',select('source_id',writableWarehouses()))}${field('Gudang tujuan',select('destination_id',catalog.warehouses.filter(w=>w.active)))}</div><div id="shipment-lines">${shipmentRows()}</div><button type="button" data-action="shipment-add">Tambah barang</button><div class="actions"><button class="primary">Kirim dengan FEFO</button><button type="button" data-action="print-do" data-id="${savedShipment?.id||''}" ${savedShipment?'':'disabled'}>Cetak DO</button><span id="shipment-print-status" class="muted">${savedShipment?'DO tersimpan: '+esc(savedShipment.document_number):'Simpan pengiriman terlebih dahulu untuk mencetak DO.'}</span></div></form></section>`:''}`;}
const canPurchase=()=>['admin','purchasing'].includes(catalog.user.role);
const canApprove=()=>['admin','approver'].includes(catalog.user.role);
const operationLabels={draft:'Draft',pending:'Menunggu persetujuan',approved:'Disetujui',partial:'Diterima sebagian',received:'Diterima seluruhnya',closed:'Ditutup',posted:'Diposting',rejected:'Ditolak',cancelled:'Dibatalkan'};
function printablePo(o){return o.kind==='po'&&['approved','partial','received','closed'].includes(o.status)&&o.approved_by!=null;}
// Decimal arithmetic keeps printed line totals independent of binary floating-point rounding.
function printDecimal(value){
 const m=String(value).match(/^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);
 if(!m)throw Error('Angka dokumen tidak valid.');
 const fraction=m[3]||'';let n=BigInt((m[1]||'')+m[2]+fraction),scale=fraction.length-Number(m[4]||0);
 if(scale<0){n*=10n**BigInt(-scale);scale=0;}
 return {n,scale};
}
function printNumber(value,money=false){
 let {n,scale}=typeof value==='object'?value:printDecimal(value);
 if(money&&scale>2){const div=10n**BigInt(scale-2);n=(n+div/2n)/div;scale=2;}
 let digits=n.toString().padStart(scale+1,'0');
 let whole=scale?digits.slice(0,-scale):digits,frac=scale?digits.slice(-scale).replace(/0+$/,''):'';
 return (money?'Rp ':'')+whole.replace(/\B(?=(\d{3})+(?!\d))/g,'.')+(frac?','+frac:'');
}
function printLineTotal(line){const q=printDecimal(line.purchase_qty||line.qty),p=printDecimal(line.purchase_price??line.unit_price);return printNumber({n:q.n*p.n,scale:q.scale+p.scale},true);}
function printPurchaseOrder(id){
 const o=operations.documents.find(o=>o.id===id);if(!o||!printablePo(o))throw Error('PO harus disetujui sebelum dicetak.');
 let area=$('#do-print');if(!area){area=document.createElement('article');area.id='do-print';document.body.append(area);}
 area.className='po-document';
 area.innerHTML=`<h1>PURCHASE ORDER</h1><h2>NO PO <span class="po-number">: ${esc(o.number)}</span></h2><div class="po-information"><p>Tanggal: ${esc(o.document_date)}</p><div class="po-parties"><p>Supplier : ${esc(o.data.supplier_code)} · ${esc(o.data.supplier_name)}</p><p>Gudang tujuan: ${esc(nameOf(catalog.warehouses,o.warehouse_id))}</p></div></div><table class="po-items"><colgroup><col style="width:6%"><col style="width:40%"><col style="width:8%"><col style="width:12%"><col style="width:17%"><col style="width:17%"></colgroup><thead><tr><th>NO</th><th>NAMA BARANG</th><th>QTY</th><th>SATUAN</th><th>HARGA</th><th>TOTAL</th></tr></thead><tbody>${o.data.lines.map((l,i)=>`<tr><td class="po-center">${i+1}</td><td>${esc(l.code)} ${esc(l.name)}</td><td class="po-center">${esc(printNumber(l.purchase_qty||l.qty))}</td><td class="po-center">${esc(poPurchaseUnit(l))}</td><td class="po-money">${esc(printNumber(l.net_purchase_price??l.purchase_price??l.unit_price,true))}</td><td class="po-money">${esc(printLineTotal(l))}</td></tr>`).join('')}<tr class="po-spacer"><td>&nbsp;</td><td></td><td></td><td></td><td></td><td></td></tr><tr class="po-total"><td></td><td>TOTAL</td><td></td><td></td><td></td><td class="po-money">${esc(printNumber(o.data.total,true))}</td></tr></tbody></table><div class="po-approval"><p>Disetujui oleh</p><p class="po-signature">( <span></span> )</p></div>`;
 window.print();
}
function operationTable(kind){return table(['Nomor / tanggal','Gudang','Status',''],operations.documents.filter(o=>o.kind===kind).map(o=>`<tr><td>${esc(o.number)}<small>${esc(o.document_date)}</small></td><td>${esc(nameOf(catalog.warehouses,o.warehouse_id))}</td><td>${esc(operationLabels[o.status])}</td><td><button data-action="ops-open" data-id="${o.id}">Buka</button> ${kind==='po'&&printablePo(o)?`<button data-action="ops-print-po" data-id="${o.id}">Cetak</button>`:''}</td></tr>`));}
function operationButtons(o){
 let html='';
 const button=(action,label)=>`<button type="button" data-action="ops-${action}" data-id="${o.id}">${label}</button>`;
 if(o.kind==='po'&&o.status==='draft'&&canPurchase())html+=button('edit-po','Ubah draft')+button('submit-po','Ajukan PO');
 if(o.status==='pending'&&canApprove())html+=button('approve-operation','Setujui')+button('reject-operation','Tolak');
 if(['draft','pending'].includes(o.status)&&(o.kind==='po'?canPurchase():canWrite()))html+=button('cancel-operation','Batalkan');
 if(o.kind==='po'&&['approved','partial'].includes(o.status)&&canPurchase())html+=button('close-po','Tutup sisa PO');
 return `<div class="actions">${html}</div>`;
}
function operationHeader(o){return `<h3>${esc(o.number)} · ${esc(operationLabels[o.status])}</h3><p>${esc(o.document_date)} · ${esc(nameOf(catalog.warehouses,o.warehouse_id))}<br>Dibuat akun #${o.created_by}${o.approved_by?' · Diputuskan akun #'+o.approved_by:''}</p>${o.data.reason?`<p>Catatan: ${esc(o.data.reason)}</p>`:''}${o.data.decision_reason?`<p>Keputusan: ${esc(o.data.decision_reason)}</p>`:''}${operationButtons(o)}`;}
function poUnits(p){return p?{[p.base_uom]:'1',...p.uoms}:{};}
function poRows(){return table(['Produk','Qty beli','Satuan beli','Harga / satuan beli','Setara stok dasar',''],poLines.map((l,i)=>{
 const p=catalog.products.find(p=>p.id===Number(l.product_id)),units=poUnits(p),unit=l.purchase_uom||p?.base_uom;
 return `<tr><td>${select('po-product-'+i,products(),l.product_id)}</td><td>${qtyInput('po-qty-'+i,l.qty||'')}</td><td><select name="po-uom-${i}" required ${p?'':'disabled'}>${p?Object.entries(units).map(([u,f])=>`<option value="${esc(u)}" ${u===unit?'selected':''}>${esc(u)}${u===p.base_uom?' (dasar)':' = '+esc(f)+' '+esc(p.base_uom)}</option>`).join(''):'<option value="">Pilih produk dahulu</option>'}</select></td><td>${input('po-price-'+i,l.unit_price??'','number','required min="0" step="0.00000001"')}<small id="po-price-label-${i}">Harga per ${esc(unit||'satuan beli')}</small></td><td id="po-conversion-${i}">${p&&l.qty?esc(Number(l.qty)*Number(units[unit]))+' '+esc(p.base_uom):'—'}</td><td><button type="button" data-action="ops-remove-po-line" data-id="${i}">Hapus</button></td></tr>`;
}));}
function collectPo(){const f=$('[data-form=po]');if(!f)return;const d=new FormData(f);poLines=poLines.map((_,i)=>({product_id:Number(d.get('po-product-'+i)),qty:d.get('po-qty-'+i),unit_price:d.get('po-price-'+i),purchase_uom:d.get('po-uom-'+i)}));}
function poPreview(i){const f=$('[data-form=po]');if(!f)return;const p=catalog.products.find(p=>p.id===Number(f.elements['po-product-'+i]?.value));if(!p)return;const u=f.elements['po-uom-'+i].value,qty=f.elements['po-qty-'+i].value;$('#po-conversion-'+i).textContent=qty?`${Number(qty)*Number(poUnits(p)[u])} ${p.base_uom}`:'—';$('#po-price-label-'+i).textContent='Harga per '+u;}
function poPurchaseUnit(l){return l.purchase_uom||l.uom;}
function poFactor(l){return Number(l.conversion_factor||1);}
function renderPoDetail(o){return `<section>${operationHeader(o)}<p>Supplier: ${esc(o.data.supplier_name)} · Nilai PO: ${esc(o.data.total)}</p>${table(['Produk','Satuan beli','Dipesan / setara stok','Harga per satuan beli','Diterima (dasar)','Sisa (dasar)'],o.data.lines.map(l=>`<tr><td>${esc(l.code)} · ${esc(l.name)}</td><td>${esc(poPurchaseUnit(l))}</td><td>${esc(l.purchase_qty||l.qty)} ${esc(poPurchaseUnit(l))}<small>${esc(l.qty)} ${esc(l.uom)}</small></td><td>${esc(l.purchase_price??l.unit_price)} / ${esc(poPurchaseUnit(l))}</td><td>${esc(l.received_qty)} ${esc(l.uom)}</td><td>${Number(l.qty)-Number(l.received_qty)} ${esc(l.uom)}</td></tr>`))}${['approved','partial'].includes(o.status)&&canWrite()?`<h3>Penerimaan PO</h3><form data-form="po-receipt" data-id="${o.id}"><div class="grid">${field('Nomor dokumen penerimaan supplier',input('reference','','text','required maxlength="100"'))}${field('Tanggal terima',input('received_date',localToday(),'date',`required min="${o.document_date}" max="${localToday()}"`))}${field('Petugas penerima',input('receiver_name','','text','required maxlength="150"'))}</div>${table(['Produk','Qty terima','Satuan terima','Batch','ED'],o.data.lines.map((l,i)=>`<tr><td>${esc(l.name)} (${esc(l.uom)})</td><td>${input('receive-qty-'+i,0,'number',`required min="0" step="0.000001"`)}</td><td><select name="receive-uom-${i}"><option value="${esc(poPurchaseUnit(l))}">${esc(poPurchaseUnit(l))}${poPurchaseUnit(l)!==l.uom?' = '+esc(l.conversion_factor)+' '+esc(l.uom):''}</option>${poPurchaseUnit(l)!==l.uom?`<option value="${esc(l.uom)}">${esc(l.uom)} (dasar)</option>`:''}</select><small>Sisa: ${(Number(l.qty)-Number(l.received_qty))/poFactor(l)} ${esc(poPurchaseUnit(l))}</small></td><td>${input('receive-batch-'+i,'','text','maxlength="100"')}</td><td>${input('receive-expiry-'+i,'','date',`min="${localToday()}"`)}</td></tr>`))}<p class="muted">Isi hanya barang yang diterima sekarang. Pilih satuan PO atau satuan dasar. Konversi memakai faktor yang tersimpan pada PO; qty nol dilewati.</p><button class="primary">Simpan penerimaan PO</button></form>`:''}<h3 style="margin-top:20px">Riwayat penerimaan PO</h3>${table(['Dokumen / tanggal','Petugas','Produk / batch','Qty / HPP'],o.data.receipts.flatMap(r=>r.lines.map(l=>`<tr><td>${esc(r.reference)}<small>${esc(r.received_date)}</small></td><td>${esc(r.receiver_name)}</td><td>${esc(l.name)} · ${esc(l.batch_number)}</td><td>${esc(l.receipt_qty||l.qty)} ${esc(l.receipt_uom||l.uom)}<small>Stok: ${esc(l.qty)} ${esc(l.uom)} · HPP/dasar ${esc(l.unit_cost)}</small></td></tr>`)))}</section>`;}
function renderPurchasing(){
 const o=operations.documents.find(o=>o.id===selectedOperation&&o.kind==='po'),editing=operations.documents.find(o=>o.id===editPo),supplier=operations.suppliers.find(s=>s.id===editSupplier);
 return `<section><h2>Purchasing / PO</h2><p class="muted">Draft → persetujuan → penerimaan bertahap di Central. Pilih satuan beli sesuai produk. Qty dan harga mengikuti satuan beli; konversi stok dihitung otomatis. Belum termasuk pajak/ongkir. Seluruh perubahan tersimpan dalam audit.</p>${operationTable('po')}</section>${o?renderPoDetail(o):''}${canPurchase()?`<section><h3>${editing?'Ubah draft '+esc(editing.number):'Buat PO'}</h3><form data-form="po"><div class="grid">${field('Nomor PO',input('number',editing?.number,'text','required maxlength="100"'))}${field('Tanggal PO',input('document_date',editing?.document_date||localToday(),'date',`required max="${localToday()}"`))}${field('Supplier',select('supplier_id',operations.suppliers.filter(s=>s.active),editing?.supplier_id))}${field('Gudang Central',select('warehouse_id',writableWarehouses().filter(w=>w.kind==='central'),editing?.warehouse_id))}</div><div id="po-lines">${poRows()}</div><button type="button" data-action="ops-add-po-line">Tambah barang PO</button><div class="actions"><button class="primary">Simpan draft PO</button><button type="button" data-action="ops-clear-po">Bersihkan form</button></div></form></section>`:''}<section><h3>Supplier</h3>${table(['Kode','Nama','Kontak','Status',''],operations.suppliers.map(s=>`<tr><td>${esc(s.code)}</td><td>${esc(s.name)}</td><td>${esc(s.contact)}</td><td>${s.active?'Aktif':'Nonaktif'}</td><td>${canPurchase()?`<button data-action="ops-edit-supplier" data-id="${s.id}">Ubah</button>`:''}</td></tr>`))}${canPurchase()?`<form data-form="supplier"><h3>${supplier?'Ubah supplier':'Tambah supplier'}</h3><div class="grid">${field('Kode supplier',input('code',supplier?.code,'text','required maxlength="50"'))}${field('Nama supplier',input('name',supplier?.name,'text','required maxlength="200"'))}${field('Kontak / alamat',input('contact',supplier?.contact,'text','maxlength="250"'))}</div><label><input type="checkbox" name="active" ${supplier?.active!==false?'checked':''}> Aktif</label><div class="actions"><button class="primary">Simpan supplier</button><button type="button" data-action="ops-clear-supplier">Batal ubah</button></div></form>`:''}</section>`;
}
function extraRows(){return table(['Produk temuan','Batch','ED','Qty fisik','HPP/unit',''],opnameExtras.map((l,i)=>`<tr><td>${select('extra-product-'+i,products(),l.product_id)}</td><td>${input('extra-batch-'+i,l.batch_number,'text','required maxlength="100"')}</td><td>${input('extra-expiry-'+i,l.expiry_date,'date','required')}</td><td>${qtyInput('extra-qty-'+i,l.counted_qty||'')}</td><td>${input('extra-cost-'+i,l.unit_cost??'','number','required min="0" step="0.00000001"')}</td><td><button type="button" data-action="ops-remove-extra" data-id="${i}">Hapus</button></td></tr>`));}
function collectExtras(){const f=$('[data-form=opname-count]');if(!f)return;const d=new FormData(f);opnameExtras=opnameExtras.map((_,i)=>({product_id:Number(d.get('extra-product-'+i)),batch_number:d.get('extra-batch-'+i),expiry_date:d.get('extra-expiry-'+i),counted_qty:d.get('extra-qty-'+i),unit_cost:d.get('extra-cost-'+i)}));}
function renderOpname(){
 const o=operations.documents.find(o=>o.id===selectedOperation&&o.kind==='opname');
 const counting=o&&o.status==='draft'&&canWrite();
 return `<section><h2>Stock opname</h2><p class="notice">Mulai opname menyimpan saldo awal dan mengunci mutasi gudang sampai disetujui, ditolak, atau dibatalkan. Selesaikan pengajuan scrap lebih dulu. Hitung fisik seluruh lot, termasuk barang rusak/kedaluwarsa.</p>${operationTable('opname')}</section>${o?`<section>${operationHeader(o)}<form data-form="opname-count" data-id="${o.id}">${table(['Barang / batch','Satuan','Saldo awal','Qty fisik','Selisih'],o.data.lines.map(l=>`<tr><td>${esc(l.name)} · ${esc(l.batch_number)}</td><td>${esc(l.uom)}</td><td>${esc(l.system_qty)}</td><td>${counting?input('count-'+l.balance_id,'','number','required min="0" step="0.000001"'):esc(l.counted_qty??'—')}</td><td>${esc(l.difference??'—')}</td></tr>`))}${counting?`<h3 style="margin-top:20px">Lot ditemukan yang belum tercatat</h3><div id="opname-extras">${extraRows()}</div><button type="button" data-action="ops-add-extra">Tambah lot temuan</button><div class="grid">${field('Petugas penghitung',input('counted_by','','text','required maxlength="150"'))}${field('Catatan / alasan selisih',input('reason','','text','required maxlength="500"'))}</div><button class="primary">Ajukan hasil opname</button>`:''}</form>${o.data.counted_by?`<p>Petugas: ${esc(o.data.counted_by)}</p>`:''}${o.data.new_lots?.length?`<h3>Lot temuan</h3>${table(['Produk','Batch / ED','Qty fisik','HPP/unit'],o.data.new_lots.map(l=>`<tr><td>${esc(l.name)}</td><td>${esc(l.batch_number)} / ${esc(l.expiry_date)}</td><td>${esc(l.counted_qty)}</td><td>${esc(l.unit_cost)}</td></tr>`))}`:''}</section>`:''}${canWrite()?`<section><h3>Mulai opname</h3><form data-form="start-opname"><div class="grid">${field('Nomor opname',input('number','','text','required maxlength="100"'))}${field('Tanggal dokumen',input('document_date',localToday(),'date',`required max="${localToday()}"`))}${field('Gudang',select('warehouse_id',writableWarehouses()))}</div><button class="primary">Mulai hitung & kunci gudang</button></form></section>`:''}`;
}
function scrapRows(){const items=stock.filter(s=>s.warehouse_id===scrapWarehouse&&Number(s.available_qty)>0).map(s=>({id:s.balance_id,name:nameOf(catalog.products,s.product_id)+' · '+s.batch_number+' · tersedia '+s.available_qty}));return table(['Barang / lot','Qty scrap',''],scrapLines.map((l,i)=>`<tr><td>${select('scrap-balance-'+i,items,l.balance_id)}</td><td>${qtyInput('scrap-qty-'+i,l.qty||'')}</td><td><button type="button" data-action="ops-remove-scrap-line" data-id="${i}">Hapus</button></td></tr>`));}
function collectScrap(){const f=$('[data-form=request-scrap]');if(!f)return;const d=new FormData(f);scrapLines=scrapLines.map((_,i)=>({balance_id:Number(d.get('scrap-balance-'+i)),qty:d.get('scrap-qty-'+i)}));}
function renderScrap(){const o=operations.documents.find(o=>o.id===selectedOperation&&o.kind==='scrap');return `<section><h2>Pengajuan & approval scrap</h2><p class="muted">Scrap untuk barang yang sudah ada di stok. Qty diajukan ditahan dari pemakaian/transfer, lalu dikurangi hanya setelah persetujuan. Penolakan/pembatalan melepas penahanan. Scrap hasil produksi akan dicatat lewat modul produksi.</p>${operationTable('scrap')}</section>${o?`<section>${operationHeader(o)}${table(['Produk / batch','Qty scrap','Satuan','HPP/unit'],o.data.lines.map(l=>`<tr><td>${esc(l.name)} · ${esc(l.batch_number)}</td><td>${esc(l.qty)}</td><td>${esc(l.uom)}</td><td>${rupiah(l.unit_cost)}</td></tr>`))}</section>`:''}${canWrite()?`<section><h3>Ajukan scrap</h3><form data-form="request-scrap"><div class="grid">${field('Nomor pengajuan',input('number','','text','required maxlength="100"'))}${field('Tanggal dokumen',input('document_date',localToday(),'date',`required max="${localToday()}"`))}${field('Gudang',select('warehouse_id',writableWarehouses(),scrapWarehouse))}${field('Alasan scrap',input('reason','','text','required maxlength="500"'))}</div><div id="scrap-lines">${scrapRows()}</div><button type="button" data-action="ops-add-scrap-line">Tambah barang scrap</button><div class="actions"><button class="primary">Ajukan scrap</button></div></form></section>`:''}`;}
async function operationAction(action,id,button){
 const o=operations.documents.find(o=>o.id===id);
 if(action==='ops-print-po'){printPurchaseOrder(id);return;}
 if(action==='ops-open'){selectedOperation=id;opnameExtras=[];render();return;}
 if(action==='ops-edit-po'){selectedOperation=id;editPo=id;poLines=o.data.lines.map(l=>({product_id:l.product_id,qty:l.purchase_qty||l.qty,unit_price:l.purchase_price??l.unit_price,purchase_uom:poPurchaseUnit(l)}));render();return;}
 if(action==='ops-clear-po'){editPo=null;poLines=[{}];render();return;}
 if(action==='ops-edit-supplier'){editSupplier=id;render();return;}
 if(action==='ops-clear-supplier'){editSupplier=null;render();return;}
 if(action.includes('po-line')){collectPo();if(action==='ops-add-po-line')poLines.push({});else poLines.splice(id,1);$('#po-lines').innerHTML=poRows();return;}
 if(action.includes('extra')){collectExtras();if(action==='ops-add-extra')opnameExtras.push({});else opnameExtras.splice(id,1);$('#opname-extras').innerHTML=extraRows();return;}
 if(action.includes('scrap-line')){collectScrap();if(action==='ops-add-scrap-line')scrapLines.push({});else scrapLines.splice(id,1);$('#scrap-lines').innerHTML=scrapRows();return;}
 const operation=action.slice(4),body={id,revision:o.revision};
 if(operation!=='submit-po'){const reason=prompt('Catatan / alasan keputusan:');if(!reason)return;body.reason=reason;}
 await command(operation,body,button);if(editPo===id){editPo=null;poLines=[{}];}selectedOperation=id;await refresh();render();message('Tersimpan di server.');
}
async function operationSubmit(kind,d,body,form){
 if(kind==='supplier'){
   if(editSupplier){const s=operations.suppliers.find(s=>s.id===editSupplier);body.id=s.id;body.revision=s.revision;}
   body.active=d.has('active');await command('save-supplier',body,form);editSupplier=null;
 }else if(kind==='po'){
   collectPo();body.lines=poLines;
   if(editPo){const o=operations.documents.find(o=>o.id===editPo);body.id=o.id;body.revision=o.revision;}
   const r=await command('save-po',body,form);selectedOperation=r.id;editPo=null;poLines=[{}];
 }else if(kind==='po-receipt'){
   const o=operations.documents.find(o=>o.id===Number(form.dataset.id));
   const lines=o.data.lines.map((l,i)=>({product_id:l.product_id,qty:d.get('receive-qty-'+i),uom:d.get('receive-uom-'+i),batch_number:d.get('receive-batch-'+i),expiry_date:d.get('receive-expiry-'+i)}));
   await command('receive-po',{...body,id:o.id,revision:o.revision,lines},form);
 }else if(kind==='start-opname'){
   const r=await command(kind,body,form);selectedOperation=r.id;opnameExtras=[];
 }else if(kind==='opname-count'){
   const o=operations.documents.find(o=>o.id===Number(form.dataset.id));collectExtras();
   await command('submit-opname',{id:o.id,revision:o.revision,counted_by:d.get('counted_by'),reason:d.get('reason'),lines:o.data.lines.map(l=>({balance_id:l.balance_id,counted_qty:d.get('count-'+l.balance_id)})),new_lots:opnameExtras},form);
 }else if(kind==='request-scrap'){
   collectScrap();const r=await command(kind,{...body,lines:scrapLines},form);selectedOperation=r.id;scrapLines=[{}];
 }
}

function renderMovements(){return `<section><h2>Riwayat mutasi</h2><p class="muted">300 mutasi terakhir dalam lingkup gudang pengguna. Riwayat sebelum migrasi berada dalam arsip.</p>${table(['Waktu','Jenis','Gudang','Lot','Qty','Referensi','Pengguna'],movements.map(m=>`<tr><td>${esc(m.at)} UTC</td><td>${esc(m.kind)}</td><td>${esc(nameOf(catalog.warehouses,m.warehouse_id))}</td><td>#${m.lot_id}</td><td>${esc(m.qty)}</td><td>${esc(m.reference)}</td><td>#${m.actor_id}</td></tr>`))}</section>`;}
function renderAccess(){if(!isAdmin())return '';return `<section><h2>Pengguna & akses gudang</h2><p class="muted">Hak tambahan di bawah melengkapi lingkup gudang lama. Hanya peran Admin/Staf Gudang dapat melakukan mutasi; Purchasing mengelola PO dan supplier; Approver menyetujui PO/opname/scrap sesuai lingkup gudang.</p>${table(['Pengguna','Peran','Gudang tambahan'],users.map(u=>`<tr><td>${esc(u.name)}<small>${esc(u.username)}</small></td><td>${esc(u.role)}</td><td>${esc(accesses.filter(a=>a.user_id===u.id).map(a=>nameOf(catalog.warehouses,a.warehouse_id)).join(', ')||'—')}</td></tr>`))}<form data-form="access"><div class="grid">${field('Pengguna',select('user_id',users))}<div>${catalog.warehouses.filter(w=>w.active).map(w=>`<p><label><input type="checkbox" name="wh" value="${w.id}"> ${esc(w.name)}</label></p>`).join('')}</div></div><button class="primary">Ganti daftar akses tambahan</button></form></section><section><h3>Tambah pengguna</h3><form data-form="user"><div class="grid">${field('Nama',input('name','','text','required'))}${field('Username',input('username','','text','required autocomplete="off"'))}${field('Password awal',input('password','','password','required autocomplete="new-password" minlength="8"'))}${field('Peran','<select name="role"><option value="gudang">Staf Gudang</option><option value="purchasing">Purchasing</option><option value="approver">Approver</option><option value="admin">Admin</option></select>')}</div><p class="muted">Wajib ganti password saat login pertama. Atur akses gudang sesudah akun dibuat.</p><button class="primary">Buat pengguna</button></form></section>`;}
function collectBom(){
  const form=$('[data-form=bom]'); if(!form)return;
  const d=new FormData(form);
  bomMaterials=bomMaterials.map((_,i)=>({product_id:Number(d.get(`material-product-${i}`)),qty:d.get(`material-qty-${i}`),uom:d.get(`material-uom-${i}`)}));
  bomByproducts=bomByproducts.map((_,i)=>({product_id:Number(d.get(`byproduct-product-${i}`)),qty:d.get(`byproduct-qty-${i}`)}));
  bomOverheads=bomOverheads.map((_,i)=>({name:d.get('overhead-name-'+i),amount:'0'}));
  return {product_id:Number(d.get('product_id')),output_qty:d.get('output_qty')};
}
function redrawBom(){
  const header=collectBom();render();
  if(header){const f=$('[data-form=bom]');f.elements.product_id.value=header.product_id||'';f.elements.output_qty.value=header.output_qty;}
}
async function task(fn){if(busy)return;busy=true;try{await fn();}catch(e){message(e.message,true);}finally{busy=false;}}
document.addEventListener('click',e=>{
  const button=e.target.closest('button');if(!button)return;
  if(button.dataset.tab){tab=button.dataset.tab;message('');render();return;}
  const action=button.dataset.action, id=Number(button.dataset.id);
  if(!action)return;
  task(async()=>{
    if(action.startsWith('ops-')){await operationAction(action,id,button);return;}
    if(action==='print-do'){if(savedShipment&&savedShipment.id===id)printDeliveryOrder(id);return;}
    if(action==='open-transfer'){selectedTransfer=id;$('#transfer-document').value=String(id);$('#transfer-detail').innerHTML=renderTransferReceipt();$('#transfer-detail').scrollIntoView({behavior:'smooth'});return;}
    if(action==='shipment-add'||action==='shipment-remove'){
      clearShipmentPrint();collectShipment();if(action==='shipment-add')shipmentLines.push({});else shipmentLines.splice(id,1);
      $('#shipment-lines').innerHTML=shipmentRows();return;
    }
    if(action==='logout'){await api('/api/auth/logout',{});location.href='/';return;}
    if(action==='archive'){const a=await api('/api/manufacturing/archive');const url=URL.createObjectURL(new Blob([JSON.stringify(a,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='inventory-archive.json';link.click();URL.revokeObjectURL(url);return;}
    for(const type of ['warehouse','kitchen']){
      if(action===`edit-${type}`){if(type==='warehouse')editWarehouse=id;else editKitchen=id;render();$(`[data-form=${type}]`).scrollIntoView({behavior:'smooth'});return;}
      if(action===`cancel-${type}`){if(type==='warehouse')editWarehouse=null;else editKitchen=null;render();return;}
      if(action===`delete-${type}`){
        const item=(type==='warehouse'?catalog.warehouses:catalog.kitchens).find(x=>x.id===id);
        if(!confirm(`Hapus ${item.code} · ${item.name}? Data yang sudah digunakan tidak dapat dihapus.`))return;
        await command(`delete-${type}`,{id,version:item.version},button);
        if(type==='warehouse')editWarehouse=null;else editKitchen=null;
        await refresh();render();message('Data berhasil dihapus.');return;
      }
    }
    if(action==='edit-product'){editProduct=id;render();$('[data-form=product]').scrollIntoView({behavior:'smooth'});return;}
    if(action==='cancel-product'){editProduct=null;render();return;}
    if(action==='edit-bom'){
      const b=catalog.boms.find(b=>b.id===id);editBom=b.status==='draft'?b.id:null;
      bomMaterials=structuredClone(b.materials);bomByproducts=structuredClone(b.byproducts);bomOverheads=structuredClone(b.overheads);render();
      const f=$('[data-form=bom]');f.elements.product_id.value=b.product_id;f.elements.output_qty.value=b.output_qty;f.scrollIntoView({behavior:'smooth'});return;
    }
    if(action==='cancel-bom'){editBom=null;bomMaterials=[];bomByproducts=[];bomOverheads=[];render();return;}
    if(action.startsWith('add-')||action.startsWith('remove-')){
      const header=collectBom();
      const arr=action.endsWith('material')?bomMaterials:action.endsWith('byproduct')?bomByproducts:bomOverheads;
      if(action.startsWith('add-'))arr.push({});else arr.splice(id,1);
      render();if(header){const f=$('[data-form=bom]');f.elements.product_id.value=header.product_id||'';f.elements.output_qty.value=header.output_qty;}
      return;
    }
    if(action==='activate-bom'){await command('activate-bom',{id},button);await refresh();render();message('BOM aktif. Versi aktif sebelumnya menjadi arsip.');return;}
    if(action==='simulate'){
      const target=prompt('Target hasil produksi dalam satuan dasar:');if(target===null)return;
      const r=await command('simulate-bom',{id,target_qty:target},button);
      message('');
      $('#simulation').innerHTML='<h3>Kebutuhan untuk '+esc(target)+'</h3>'+table(['Bahan','Qty','Satuan dasar'],r.materials.map(m=>`<tr><td>${esc(nameOf(catalog.products,m.product_id))}</td><td>${esc(m.base_qty)}</td><td>${esc(m.uom)}</td></tr>`));return;
    }
    if(action==='correct-lot'){
      const expiry=prompt('Tanggal kedaluwarsa sesuai dokumen sumber (YYYY-MM-DD):');if(!expiry)return;
      const reason=prompt('Alasan/dokumen pendukung koreksi:');if(!reason)return;
      await command('correct-lot',{id,expiry_date:expiry,reason},button);await refresh();render();message('ED lot telah dilengkapi.');
    }
  });
});
function clearShipmentPrint(){
  savedShipment=null;
  const button=$('[data-form=ship] [data-action=print-do]');
  if(button){button.disabled=true;button.dataset.id='';}
  const status=$('#shipment-print-status');if(status)status.textContent='Simpan pengiriman terlebih dahulu untuk mencetak DO.';
}
document.addEventListener('input',e=>{if(e.target.closest('[data-form=ship]'))clearShipmentPrint();});
document.addEventListener('input',e=>{if(e.target.name?.startsWith('po-qty-'))poPreview(Number(e.target.name.slice(7)));});
document.addEventListener('input',e=>{
 if(e.target.closest('[data-form=receipt]'))receiptPreview();
 if(e.target.name?.startsWith('ship-qty-'))shipmentPreview(Number(e.target.name.slice(9)));
});
document.addEventListener('change',e=>{
 if(e.target.closest('[data-form=receipt]')){if(e.target.name==='product_id'){receiptUnitOptions();e.target.form.elements.unit_cost.value='';}if(e.target.name==='uom')e.target.form.elements.unit_cost.value='';receiptPreview();}
 if(e.target.name?.startsWith('ship-product-')){const i=Number(e.target.name.slice(13));collectShipment();shipmentLines[i].uom=catalog.products.find(p=>p.id===shipmentLines[i].product_id)?.base_uom;$('#shipment-lines').innerHTML=shipmentRows();}
 if(e.target.name?.startsWith('ship-uom-'))shipmentPreview(Number(e.target.name.slice(9)));
 if(e.target.name?.startsWith('transfer-uom-')){e.target.form.elements['line-'+e.target.name.slice(13)].value='';}

  if(e.target.name?.startsWith('po-product-')){const i=Number(e.target.name.slice(11));collectPo();const p=catalog.products.find(p=>p.id===poLines[i].product_id);poLines[i].purchase_uom=p?.base_uom;poLines[i].unit_price='';$('#po-lines').innerHTML=poRows();}
  if(e.target.name?.startsWith('po-uom-')){const i=Number(e.target.name.slice(7));const f=e.target.form;f.elements['po-price-'+i].value='';poPreview(i);}

  if(e.target.name==='warehouse_id'&&e.target.closest('[data-form=request-scrap]')){scrapWarehouse=Number(e.target.value);scrapLines=[{}];$('#scrap-lines').innerHTML=scrapRows();}
  if(e.target.closest('[data-form=ship]'))clearShipmentPrint();
  if(e.target.id==='transfer-document'){selectedTransfer=Number(e.target.value)||null;$('#transfer-detail').innerHTML=renderTransferReceipt();}
  if(e.target.name==='kind')syncKitchen();
  if(e.target.name==='user_id'&&e.target.closest('[data-form=access]')){
    const ids=accesses.filter(a=>a.user_id===Number(e.target.value)).map(a=>a.warehouse_id);
    e.target.form.querySelectorAll('[name=wh]').forEach(x=>x.checked=ids.includes(Number(x.value)));
  }
});
document.addEventListener('submit',e=>{
  const form=e.target.closest('[data-form]');if(!form)return;e.preventDefault();
  task(async()=>{
    const kind=form.dataset.form,d=new FormData(form),body=Object.fromEntries(d);
    if(['supplier','po','po-receipt','start-opname','opname-count','request-scrap'].includes(kind)){await operationSubmit(kind,d,body,form);}
    else if(kind==='activate'){await command('activate',{source_version:setup.preview.source_version},form);}
    else if(['warehouse','kitchen'].includes(kind)){
      const kitchen=kind==='kitchen',id=kitchen?editKitchen:editWarehouse;
      if(id){const item=(kitchen?catalog.kitchens:catalog.warehouses).find(x=>x.id===id);body.id=id;body.version=item.version;}
      if(kitchen)body.warehouse_id=Number(d.get('warehouse_id'));else body.active=d.has('active');
      await command(`save-${kind}`,body,form);
      if(kitchen)editKitchen=null;else editWarehouse=null;
    }
    else if(kind==='product'){
      body.uoms={};for(const part of String(d.get('uoms')).split(';').map(v=>v.trim()).filter(Boolean)){const [key,value,...rest]=part.split('=');if(!key||!value||rest.length)throw Error('Konversi: sak=25; dus=10');body.uoms[key.trim()]=value.trim();}
      body.kitchen_id=d.get('kitchen_id')?Number(d.get('kitchen_id')):null;body.shelf_life_days=d.get('shelf_life_days')===''?null:Number(d.get('shelf_life_days'));body.discrete=d.has('discrete');body.active=d.has('active');
      if(editProduct){const p=catalog.products.find(p=>p.id===editProduct);body.id=p.id;body.revision=p.revision;}
      await command('save-product',body,form);editProduct=null;
    }else if(kind==='bom'){
      const header=collectBom();const materials=bomMaterials.map(m=>({...m,...(!m.uom?{uom:catalog.products.find(p=>p.id===m.product_id)?.base_uom}: {})}));
      const payload={...header,materials,byproducts:bomByproducts,overheads:bomOverheads};if(editBom){const b=catalog.boms.find(b=>b.id===editBom);payload.id=b.id;payload.revision=b.revision;}
      await command('save-bom',payload,form);editBom=null;bomMaterials=[];bomByproducts=[];bomOverheads=[];
    }else if(kind==='access')await command('set-access',{user_id:Number(d.get('user_id')),warehouse_ids:d.getAll('wh').map(Number)},form);
    else if(kind==='user')await api('/api/users',{...body,warehouseId:null});
    else if(kind==='receive-transfer'){
      const id=Number(form.dataset.transfer),t=transfers.find(t=>t.id===id);
      await command('receive-transfer',{id,received_date:d.get('received_date'),receiver_name:d.get('receiver_name'),lines:t.lines.map(l=>({id:l.id,qty:d.get('line-'+l.id),uom:d.get('transfer-uom-'+l.id)}))},form);
    }else if(kind==='ship'){collectShipment();const result=await command('ship',{...body,lines:shipmentLines},form);savedShipment=result;selectedTransfer=result.id;shipmentLines=[{}];}
    else if(['receipt','usage'].includes(kind))await command(kind,body,form);
    await refresh();render();message('Tersimpan di server.');
  });
});


