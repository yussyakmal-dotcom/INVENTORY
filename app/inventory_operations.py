"""PO, physical counts and stock scrap. All writes run inside inventory.execute's DB gate."""
import json
from datetime import date
from decimal import Decimal

import inventory as c
from inventory_models import Supplier, Operation, Product, Warehouse, Balance, Lot, now

OPEN = {'draft', 'pending', 'approved', 'partial'}
OPERATIONS = {'save-supplier', 'save-po', 'submit-po', 'approve-operation', 'reject-operation',
              'cancel-operation', 'close-po', 'receive-po', 'start-opname', 'submit-opname', 'request-scrap'}


def role(user, roles):
    if user.role not in roles:
        c.fail('Peran tidak diizinkan untuk tindakan ini.', 403)


def scope(db, user, wid):
    return c.warehouse_access(db, user, wid, write=False)


def version(item, body):
    if c.integer(body.get('revision'), 'Versi') != item.revision:
        c.fail('Dokumen sudah berubah. Muat ulang sebelum melanjutkan.', 409)


def supplier_dict(s):
    return {k: getattr(s, k) for k in ('id', 'code', 'name', 'contact', 'active', 'revision')}


def operation_dict(o):
    return {**{k: getattr(o, k) for k in ('id', 'kind', 'number', 'warehouse_id', 'supplier_id', 'status', 'revision', 'created_by', 'approved_by')},
            'document_date': str(o.document_date), 'created_at': str(o.created_at),
            'decided_at': str(o.decided_at) if o.decided_at else None, 'data': json.loads(o.document)}


def listing(db, user):
    ids = c.allowed_warehouses(db, user)
    query = db.query(Operation)
    if ids is not None:
        query = query.filter(Operation.warehouse_id.in_(ids))
    return {'suppliers': [supplier_dict(s) for s in db.query(Supplier).order_by(Supplier.name)],
            'documents': [operation_dict(o) for o in query.order_by(Operation.id.desc())]}


def freeze(db, wid):
    return db.query(Operation).filter(Operation.kind == 'opname', Operation.warehouse_id == wid,
                                      Operation.status.in_(['draft', 'pending'])).first()


def reserved(db, balance_id):
    total = Decimal(0)
    for o in db.query(Operation).filter_by(kind='scrap', status='pending'):
        for line in json.loads(o.document)['lines']:
            if line['balance_id'] == balance_id:
                total += Decimal(line['qty'])
    return total


def save(db, o, data=None):
    if data is not None:
        o.document = c.dump(data)
    o.revision += 1
    db.flush()
    return operation_dict(o)


def new_operation(db, user, kind, body, data, status='draft'):
    o = Operation(kind=kind, number=c.label(body.get('number'), 'Nomor dokumen', 100).upper(),
                  warehouse_id=c.integer(body.get('warehouse_id'), 'Gudang'), status=status,
                  document_date=c.document_date(body.get('document_date'), 'Tanggal dokumen'),
                  created_by=user.id, revision=1, document=c.dump(data))
    db.add(o)
    db.flush()
    return o


def snapshot_product(p):
    return {'product_id': p.id, 'code': p.code, 'name': p.name, 'uom': p.base_uom}


def balance_line(db, b):
    lot = c.get(db, Lot, b.lot_id)
    return {**snapshot_product(c.get(db, Product, lot.product_id)), 'balance_id': b.id, 'lot_id': lot.id,
            'batch_number': lot.batch_number, 'expiry_date': str(lot.expiry_date) if lot.expiry_date else None,
            'unit_cost': str(lot.unit_cost), 'system_qty': str(b.qty)}


def save_supplier(db, user, body):
    role(user, {'admin', 'purchasing'})
    item = c.get(db, Supplier, body['id']) if body.get('id') else Supplier(revision=0)
    if item.id:
        version(item, body)
    item.code = c.label(body.get('code'), 'Kode supplier', 50).upper()
    item.name = c.label(body.get('name'), 'Nama supplier', 200)
    contact = body.get('contact', '')
    if not isinstance(contact, str) or len(contact) > 250:
        c.fail('Kontak supplier maksimal 250 karakter.')
    item.contact = contact.strip()
    item.active = c.flag(body.get('active', True), 'Status supplier')
    item.revision += 1
    db.add(item)
    db.flush()
    return supplier_dict(item)


def save_po(db, user, body):
    role(user, {'admin', 'purchasing'})
    wh = scope(db, user, body.get('warehouse_id'))
    if wh.kind != 'central':
        c.fail('PO harus diterima di Gudang Central.')
    supplier = c.get(db, Supplier, body.get('supplier_id'))
    if not supplier.active:
        c.fail('Supplier tidak aktif.')
    o = c.get(db, Operation, body['id']) if body.get('id') else None
    if o:
        scope(db, user, o.warehouse_id)
        version(o, body)
        if o.kind != 'po' or o.status != 'draft':
            c.fail('Hanya draft PO dapat diubah.', 409)
    rows = body.get('lines')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        c.fail('PO wajib berisi 1–200 baris.')
    lines, seen, total = [], set(), Decimal(0)
    for row in rows:
        if not isinstance(row, dict):
            c.fail('Baris PO tidak valid.')
        p = c.get(db, Product, row.get('product_id'))
        if not p.active or p.id in seen:
            c.fail('Produk PO harus aktif dan tidak berulang.')
        seen.add(p.id)
        qty = c.quantity_for(p, row.get('qty'))
        price = c.number(row.get('unit_price'), 'Harga satuan dasar', scale=8)
        total += qty * price
        lines.append({**snapshot_product(p), 'qty': str(qty), 'unit_price': str(price), 'received_qty': '0'})
    data = {'supplier_name': supplier.name, 'supplier_code': supplier.code, 'lines': lines, 'total': str(total), 'receipts': []}
    if o:
        o.number = c.label(body.get('number'), 'Nomor PO', 100).upper()
        o.warehouse_id = wh.id
        o.document_date = c.document_date(body.get('document_date'), 'Tanggal PO')
    else:
        o = new_operation(db, user, 'po', body, data)
    o.supplier_id = supplier.id
    return save(db, o, data)


def receive_po(db, user, body):
    role(user, {'admin', 'gudang'})
    o = c.get(db, Operation, body.get('id'))
    c.warehouse_access(db, user, o.warehouse_id)
    version(o, body)
    if o.kind != 'po' or o.status not in {'approved', 'partial'}:
        c.fail('PO belum disetujui atau sudah ditutup.', 409)
    received_date = c.document_date(body.get('received_date'), 'Tanggal penerimaan')
    if received_date < o.document_date:
        c.fail('Tanggal penerimaan tidak boleh sebelum PO.')
    reference = c.label(body.get('reference'), 'Nomor dokumen penerimaan supplier', 100).upper()
    receiver = c.label(body.get('receiver_name'), 'Petugas penerima', 150)
    data = json.loads(o.document)
    if any(r['reference'] == reference for r in data['receipts']):
        c.fail('Dokumen penerimaan ini sudah dicatat pada PO.', 409)
    entries = body.get('lines')
    if not isinstance(entries, list) or not entries or len(entries) > 200:
        c.fail('Isi baris penerimaan PO.')
    by_product = {l['product_id']: l for l in data['lines']}
    received = []
    for row in entries:
        if not isinstance(row, dict):
            c.fail('Baris penerimaan tidak valid.')
        pid = c.integer(row.get('product_id'), 'Produk')
        if pid not in by_product:
            c.fail('Produk tidak tercantum pada PO.')
        line = by_product[pid]
        p = c.get(db, Product, pid)
        qty = c.number(row.get('qty'), 'Qty penerimaan')
        if qty == 0:
            continue
        c.quantity_for(p, qty)
        if qty > Decimal(line['qty']) - Decimal(line['received_qty']):
            c.fail('Qty penerimaan melebihi sisa PO.', 409)
        result = c.receive_stock(db, user, {'warehouse_id': o.warehouse_id, 'product_id': pid, 'qty': str(qty),
                                          'unit_cost': line['unit_price'], 'batch_number': row.get('batch_number'),
                                          'expiry_date': row.get('expiry_date'), 'reference': o.number + '/' + reference[:40]})
        line['received_qty'] = str(Decimal(line['received_qty']) + qty)
        received.append({**snapshot_product(p), 'qty': str(qty), 'lot_id': result['lot_id'],
                         'batch_number': row['batch_number'], 'expiry_date': row['expiry_date'], 'unit_cost': line['unit_price']})
    if not received:
        c.fail('Minimal satu baris penerimaan harus positif.')
    data['receipts'].append({'reference': reference, 'received_date': str(received_date), 'receiver_name': receiver,
                             'actor_id': user.id, 'recorded_at': str(now()), 'lines': received})
    o.status = 'received' if all(Decimal(l['qty']) == Decimal(l['received_qty']) for l in data['lines']) else 'partial'
    return save(db, o, data)


def start_opname(db, user, body):
    role(user, {'admin', 'gudang'})
    wh = c.warehouse_access(db, user, body.get('warehouse_id'))
    if db.query(Operation).filter_by(kind='scrap', warehouse_id=wh.id, status='pending').first():
        c.fail('Selesaikan pengajuan scrap sebelum memulai opname.', 409)
    lines = [balance_line(db, b) for b in db.query(Balance).filter_by(warehouse_id=wh.id).order_by(Balance.id)]
    o = new_operation(db, user, 'opname', body, {'lines': lines, 'reason': '', 'counted_by': None})
    return operation_dict(o)


def submit_opname(db, user, body):
    role(user, {'admin', 'gudang'})
    o = c.get(db, Operation, body.get('id'))
    scope(db, user, o.warehouse_id)
    version(o, body)
    if o.kind != 'opname' or o.status != 'draft':
        c.fail('Hanya draft opname dapat diajukan.', 409)
    data = json.loads(o.document)
    entries = body.get('lines')
    if not isinstance(entries, list) or len(entries) != len(data['lines']):
        c.fail('Isi seluruh baris hasil hitung fisik.')
    counts = {}
    for row in entries:
        if not isinstance(row, dict):
            c.fail('Baris opname tidak valid.')
        bid = c.integer(row.get('balance_id'), 'Saldo')
        if bid in counts:
            c.fail('Baris opname duplikat.')
        counts[bid] = c.number(row.get('counted_qty'), 'Qty fisik')
    for line in data['lines']:
        qty = counts.get(line['balance_id'])
        if qty is None:
            c.fail('Baris opname tidak sesuai snapshot.')
        p = c.get(db, Product, line['product_id'])
        if p.discrete and qty != qty.to_integral_value():
            c.fail('Qty produk diskret harus bulat.')
        line['counted_qty'] = str(qty)
        line['difference'] = str(qty - Decimal(line['system_qty']))
    extras = body.get('new_lots', [])
    if not isinstance(extras, list) or len(extras) > 200:
        c.fail('Daftar lot temuan tidak valid.')
    data['new_lots'] = []
    for row in extras:
        if not isinstance(row, dict):
            c.fail('Lot temuan tidak valid.')
        p = c.get(db, Product, row.get('product_id'))
        if not p.active:
            c.fail('Produk temuan harus aktif.')
        qty = c.quantity_for(p, row.get('counted_qty'))
        try:
            expiry = date.fromisoformat(row.get('expiry_date', ''))
        except (ValueError, TypeError):
            c.fail('Lot temuan wajib memiliki ED valid.')
        batch = c.label(row.get('batch_number'), 'Batch temuan', 100)
        if any(l['product_id'] == p.id and l['batch_number'] == batch for l in data['lines'] + data['new_lots']):
            c.fail('Batch sudah tercatat; isi qty fisik pada baris yang tersedia.')
        data['new_lots'].append({**snapshot_product(p), 'counted_qty': str(qty), 'batch_number': batch,
                                 'expiry_date': str(expiry), 'unit_cost': str(c.number(row.get('unit_cost'), 'HPP temuan', scale=8))})
    data['reason'] = c.label(body.get('reason'), 'Catatan/alasan hasil opname', 500)
    data['counted_by'] = c.label(body.get('counted_by'), 'Petugas penghitung', 150)
    o.status = 'pending'
    return save(db, o, data)


def request_scrap(db, user, body):
    role(user, {'admin', 'gudang'})
    wh = c.warehouse_access(db, user, body.get('warehouse_id'))
    rows = body.get('lines')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
        c.fail('Isi 1–200 baris scrap.')
    lines, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            c.fail('Baris scrap tidak valid.')
        b = c.get(db, Balance, row.get('balance_id'))
        if b.warehouse_id != wh.id or b.id in seen:
            c.fail('Lot scrap harus dari gudang yang dipilih dan tidak berulang.')
        seen.add(b.id)
        line = balance_line(db, b)
        qty = c.quantity_for(c.get(db, Product, line['product_id']), row.get('qty'))
        if qty > b.qty - reserved(db, b.id):
            c.fail('Jumlah scrap melebihi stok yang belum ditahan.', 409)
        lines.append({**line, 'qty': str(qty)})
    reason = c.label(body.get('reason'), 'Alasan scrap', 500)
    o = new_operation(db, user, 'scrap', body, {'lines': lines, 'reason': reason}, status='pending')
    return operation_dict(o)


def decision(db, user, body, action):
    o = c.get(db, Operation, body.get('id'))
    scope(db, user, o.warehouse_id)
    version(o, body)
    data = json.loads(o.document)
    if action == 'submit-po':
        role(user, {'admin', 'purchasing'})
        if o.kind != 'po' or o.status != 'draft':
            c.fail('Hanya draft PO dapat diajukan.', 409)
        if not c.get(db, Supplier, o.supplier_id).active or any(not c.get(db, Product, l['product_id']).active for l in data['lines']):
            c.fail('Supplier dan produk PO harus aktif.')
        o.status = 'pending'
    elif action in {'cancel-operation', 'close-po'}:
        role(user, {'admin', 'purchasing'} if o.kind == 'po' else {'admin', 'gudang'})
        if action == 'close-po':
            if o.kind != 'po' or o.status not in {'approved', 'partial'}:
                c.fail('Hanya PO disetujui/sebagian dapat ditutup.', 409)
            o.status = 'closed'
        else:
            if o.status not in {'draft', 'pending'}:
                c.fail('Dokumen yang sudah diposting tidak dapat dibatalkan.', 409)
            o.status = 'cancelled'
        data['decision_reason'] = c.label(body.get('reason'), 'Alasan', 500)
        data['decided_by'] = user.id
        o.decided_at = now()
    else:
        role(user, {'admin', 'approver'})
        if o.status != 'pending':
            c.fail('Dokumen tidak sedang menunggu persetujuan.', 409)
        data['decision_reason'] = c.label(body.get('reason'), 'Catatan persetujuan/penolakan', 500)
        o.approved_by, o.decided_at = user.id, now()
        if action == 'reject-operation':
            o.status = 'rejected'
        else:
            if o.kind == 'po':
                if not c.get(db, Supplier, o.supplier_id).active:
                    c.fail('Supplier tidak aktif.')
                if any(not c.get(db, Product, l['product_id']).active for l in data['lines']):
                    c.fail('Produk PO tidak aktif.')
                o.status = 'approved'
            else:
                if o.kind == 'scrap' and freeze(db, o.warehouse_id):
                    c.fail('Gudang sedang opname.', 409)
                for line in data['lines']:
                    b = c.get(db, Balance, line['balance_id'])
                    lot = c.get(db, Lot, b.lot_id)
                    if o.kind == 'opname':
                        if b.qty != Decimal(line['system_qty']):
                            c.fail('Saldo berubah dari snapshot; batalkan dan hitung ulang.', 409)
                        delta = Decimal(line['counted_qty']) - b.qty
                    else:
                        delta = -Decimal(line['qty'])
                        if b.qty < reserved(db, b.id):
                            c.fail('Saldo tidak cukup untuk pengajuan scrap yang ditahan.', 409)
                    b.qty += delta
                    if delta:
                        c.movement(db, b, lot, delta, 'OPNAME' if o.kind == 'opname' else 'SCRAP', o.number, user)
                if o.kind == 'opname':
                    for line in data.get('new_lots', []):
                        lot = Lot(product_id=line['product_id'], batch_number=line['batch_number'],
                                  expiry_date=date.fromisoformat(line['expiry_date']), unit_cost=Decimal(line['unit_cost']), blocked=False)
                        db.add(lot)
                        db.flush()
                        qty = Decimal(line['counted_qty'])
                        b = Balance(lot_id=lot.id, warehouse_id=o.warehouse_id, qty=qty)
                        db.add(b)
                        db.flush()
                        line['lot_id'], line['balance_id'] = lot.id, b.id
                        c.movement(db, b, lot, qty, 'OPNAME', o.number, user)
                o.status = 'posted'
    return save(db, o, data)


def handle(db, user, operation, body):
    functions = {'save-supplier': save_supplier, 'save-po': save_po, 'receive-po': receive_po,
                 'start-opname': start_opname, 'submit-opname': submit_opname, 'request-scrap': request_scrap}
    if operation in functions:
        return functions[operation](db, user, body)
    return decision(db, user, body, operation)
