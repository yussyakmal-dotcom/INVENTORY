"""Server-owned phase-one inventory and BOM commands.

All writes share a database gate, including the legacy JSON write path. This is
deliberately conservative: correctness across workers before fine-grained locks.
"""
import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from inventory_models import (Access, Audit, Balance, Base, Bom, Command, Control,
                              Kitchen, Lot, Movement, Product, Transfer,
                              TransferLine, Warehouse, now)

KINDS = {"raw", "packaging", "wip", "finished", "package", "byproduct"}
MADE = {"wip", "finished", "package", "byproduct"}


def fail(message, code=422):
    raise HTTPException(code, message)


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def today():
    return datetime.now(ZoneInfo("Asia/Jakarta")).date()


def number(value, label, positive=False, scale=6):
    try:
        if isinstance(value, bool):
            raise ValueError()
        n = Decimal(str(value))
        if not n.is_finite() or n < 0 or (positive and n <= 0):
            raise ValueError()
        if n >= Decimal("1000000000000") or n != n.quantize(Decimal(1).scaleb(-scale)):
            raise ValueError()
        return n
    except (ValueError, InvalidOperation, TypeError):
        fail(f"{label} harus angka {'positif' if positive else 'nonnegatif'}, maksimal {scale} desimal.")


def integer(value, label, minimum=1):
    if isinstance(value, bool):
        fail(f"{label} tidak valid.")
    try:
        n = int(str(value))
        if n < minimum or n > 2147483647:
            raise ValueError()
        return n
    except (ValueError, TypeError):
        fail(f"{label} harus bilangan bulat >= {minimum}.")


def label(value, name, limit=100):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        fail(f"{name} wajib, maksimal {limit} karakter.")
    return value.strip()


def flag(value, name):
    if not isinstance(value, bool):
        fail(f"{name} harus true/false.")
    return value


def get(db, model, ident):
    item = db.get(model, integer(ident, "ID"))
    if item is None:
        fail("Data tidak ditemukan.", 404)
    return item


def control(db):
    return db.get(Control, 1)


def require_active(db):
    if not control(db).active:
        fail("Aktifkan fondasi melalui halaman Persiapan terlebih dahulu.", 409)


def actor(user):
    return SimpleNamespace(id=user.id, role=user.role, username=user.username,
                           warehouse_id=user.warehouse_id)


def admin(user):
    if user.role != "admin":
        fail("Hanya Admin yang dapat mengubah master atau mengaktifkan fondasi.", 403)


def allowed_warehouses(db, user):
    if user.role == "admin":
        return None
    ids = {a.warehouse_id for a in db.query(Access).filter_by(user_id=user.id)}
    if user.warehouse_id is not None:
        legacy = db.query(Warehouse).filter_by(legacy_id=user.warehouse_id).first()
        if legacy:
            ids.add(legacy.id)
    return ids


def warehouse_access(db, user, wid, write=True):
    wh = get(db, Warehouse, wid)
    if not wh.active:
        fail("Gudang tidak aktif.")
    if write and user.role not in {"admin", "gudang"}:
        fail("Peran tidak dapat melakukan mutasi stok.", 403)
    ids = allowed_warehouses(db, user)
    if ids is not None and wh.id not in ids:
        fail("Gudang di luar lingkup pengguna.", 403)
    return wh


def acquire_gate(db):
    # UPDATE acquires an InnoDB row lock (also serializes SQLite test writes).
    db.execute(update(Control).where(Control.id == 1).values(revision=Control.revision + 1))


def legacy_write_guard(db, user):
    identity = actor(user)
    db.rollback()  # End the authentication read snapshot before acquiring gate.
    acquire_gate(db)
    if control(db).active:
        fail("Stok telah dipindahkan ke fondasi server. Gunakan /manufacturing; aplikasi lama hanya arsip.", 409)
    return identity


def execute(db, user, operation, payload, key, fn, active=True):
    who = actor(user)
    key = label(key, "Idempotency-Key", 100)
    hashed = hashlib.sha256(dump(payload).encode()).hexdigest()
    db.rollback()
    try:
        acquire_gate(db)
        old = db.query(Command).filter_by(actor_id=who.id, operation=operation, request_key=key).first()
        if old:
            if old.payload_hash != hashed:
                fail("Kunci permintaan sudah digunakan untuk isi berbeda.", 409)
            response = json.loads(old.response)
            db.rollback()
            return response
        if active:
            require_active(db)
        result = json.loads(dump(fn(who)))
        db.add(Audit(actor_id=who.id, operation=operation, document=dump(payload)))
        db.add(Command(actor_id=who.id, operation=operation, request_key=key,
                       payload_hash=hashed, response=dump(result)))
        db.commit()
        return result
    except IntegrityError:
        db.rollback()
        fail("Kode atau versi sudah digunakan. Muat ulang sebelum mencoba lagi.", 409)
    except Exception:
        db.rollback()
        raise


def initialize(engine, sessions):
    Base.metadata.create_all(engine)
    with sessions() as db:
        if not control(db):
            try:
                db.add(Control(id=1, schema_version=1, revision=0, active=False))
                db.commit()
            except IntegrityError:  # Another worker completed initialization.
                db.rollback()
        acquire_gate(db)
        for i in range(1, 12):
            code = f"D{i:02}" if i <= 10 else "PACK"
            name = f"Dapur {i}" if i <= 10 else "Dapur Packing"
            kind = "kitchen" if i <= 10 else "packing"
            wh = db.query(Warehouse).filter_by(code=f"G-{code}").first()
            if not wh:
                wh = Warehouse(code=f"G-{code}", name=f"Gudang {name}", kind=kind)
                db.add(wh)
                db.flush()
            if not db.query(Kitchen).filter_by(code=code).first():
                db.add(Kitchen(code=code, name=name, kind="production" if i <= 10 else "packing", warehouse_id=wh.id))
        db.commit()


def legacy_date(value):
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000, ZoneInfo("Asia/Jakarta")).date()
        return date.fromisoformat(value)
    except (ValueError, TypeError, OverflowError):
        fail("Tanggal kedaluwarsa pada data lama tidak valid.")


def legacy_timestamp(value):
    if value is None:
        return now()
    try:
        return datetime.fromtimestamp(float(value) / 1000, timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, OverflowError):
        fail("Waktu penerimaan pada data lama tidak valid.")


def migration_preview(db, state_model):
    row = db.get(state_model, 1)
    data = json.loads(row.data) if row else {}
    blockers = []
    terminal = {
        "transfers": {"diterima", "batal", "kedaluwarsa"},
        "scraps": {"disetujui", "ditolak", "batal"},
        "opnames": {"diposting", "batal"},
        "pos": {"selesai", "batal"},
    }
    for collection, closed in terminal.items():
        for doc in data.get(collection, []):
            if doc.get("status") not in closed:
                blockers.append(f"Selesaikan {collection}: {doc.get('no', doc.get('id'))} ({doc.get('status')}).")
    if data.get("reservations"):
        blockers.append("Masih ada reservasi aktif di aplikasi lama.")
    whs = {w["id"]: w for w in data.get("warehouses", [])}
    products = {p["id"]: p for p in data.get("products", [])}
    reserved_codes = {w.code.casefold() for w in db.query(Warehouse)}
    for w in whs.values():
        if str(w.get("code", "")).casefold() in reserved_codes:
            blockers.append(f"Kode gudang {w.get('code')} berbenturan dengan gudang dapur baru.")
    positive = []
    for b in data.get("batches", []):
        q = number(b.get("qty"), "Saldo batch")
        number(b.get("cost"), "Biaya batch", scale=8)
        if b.get("warehouseId") not in whs or b.get("productId") not in products:
            blockers.append(f"Batch {b.get('id')} memiliki master yang tidak ditemukan.")
        legacy_date(b.get("expDate"))
        legacy_timestamp(b.get("inboundAt"))
        if q > 0:
            positive.append(b)
    for collection in [list(whs.values()), list(products.values())]:
        codes = [str(x.get("code", "")).strip().casefold() for x in collection]
        if "" in codes or len(codes) != len(set(codes)):
            blockers.append("Master lama memiliki kode kosong/duplikat.")
    return {
        "source_version": row.version if row else 0,
        "warehouses": len(whs), "products": len(products), "lots": len(positive),
        "stock_value": str(sum((number(b["qty"], "Qty") * number(b["cost"], "Cost", scale=8) for b in positive), Decimal(0))),
        "missing_expiry": sum(1 for b in positive if not b.get("expDate")),
        "blockers": blockers,
    }, data


def migrate(db, user, body, state_model):
    admin(user)
    if control(db).active:
        fail("Fondasi sudah aktif.", 409)
    preview, data = migration_preview(db, state_model)
    if integer(body.get("source_version"), "Versi sumber", 0) != preview["source_version"]:
        fail("Data lama berubah; buat preview migrasi lagi.", 409)
    if preview["blockers"]:
        fail("Migrasi belum dapat dijalankan: " + " ".join(preview["blockers"]), 409)
    wh_map, product_map = {}, {}
    for w in data.get("warehouses", []):
        row = Warehouse(code=label(w["code"], "Kode gudang", 50), name=label(w["name"], "Nama gudang", 200),
                        kind="central" if w.get("isCentral") else "store", legacy_id=w["id"], active=bool(w.get("isActive", True)))
        db.add(row)
        db.flush()
        wh_map[w["id"]] = row.id
    if not any(w.kind == "central" for w in db.query(Warehouse)):
        db.add(Warehouse(code="GDC", name="Gudang Central", kind="central"))
    for p in data.get("products", []):
        conversions = {}
        for u in p.get("uoms", []):
            conversions[label(u["name"], "Satuan", 20)] = str(number(u["factor"], "Konversi", True))
        row = Product(code=label(p["code"], "Kode", 50), name=label(p["name"], "Nama", 200), kind="raw",
                      base_uom=label(p["baseUom"], "Satuan dasar", 20), uoms=dump(conversions),
                      legacy_id=p["id"], active=bool(p.get("isActive", True)))
        db.add(row)
        db.flush()
        product_map[p["id"]] = row.id
    for b in data.get("batches", []):
        qty = number(b["qty"], "Saldo")
        if qty == 0:
            continue
        exp = legacy_date(b.get("expDate"))
        lot = Lot(product_id=product_map[b["productId"]], batch_number=label(b["batchNo"], "Batch", 100),
                  expiry_date=exp, blocked=exp is None, unit_cost=number(b["cost"], "Cost", scale=8),
                  received_at=legacy_timestamp(b.get("inboundAt")), legacy_id=b["id"])
        db.add(lot)
        db.flush()
        balance = Balance(lot_id=lot.id, warehouse_id=wh_map[b["warehouseId"]], qty=qty)
        db.add(balance)
        db.flush()
        movement(db, balance, lot, qty, "OPENING", f"CUTOVER-v{preview['source_version']}", user)
    ctrl = control(db)
    ctrl.archive = dump(data)
    ctrl.legacy_version = preview["source_version"]
    ctrl.active = True
    ctrl.activated_at = now()
    legacy = db.get(state_model, 1)
    if legacy:
        legacy.version += 1  # Wake existing browser tabs so they enter the new UI.
    return {"active": True, "imported": preview}


def product_dict(p):
    return {"id": p.id, "code": p.code, "name": p.name, "kind": p.kind,
            "base_uom": p.base_uom, "uoms": json.loads(p.uoms), "discrete": p.discrete,
            "shelf_life_days": p.shelf_life_days, "kitchen_id": p.kitchen_id,
            "selling_price": str(p.selling_price), "active": p.active, "revision": p.revision}


def save_product(db, user, body, pid=None):
    admin(user)
    p = get(db, Product, pid) if pid else Product(revision=1)
    if pid and integer(body.get("revision"), "Versi") != p.revision:
        fail("Produk berubah; muat ulang.", 409)
    old = product_dict(p) if pid else None
    kind = body.get("kind")
    if kind not in KINDS:
        fail("Jenis produk tidak valid.")
    base = label(body.get("base_uom"), "Satuan dasar", 20)
    discrete = flag(body.get("discrete", False), "Satuan diskret")
    # Once used, units must remain immutable even when current balance is zero.
    used = bool(pid and db.query(Lot).filter_by(product_id=p.id).first())
    if pid and not used:
        for recipe in db.query(Bom):
            doc = json.loads(recipe.document)
            if recipe.product_id == p.id or any(m["product_id"] == p.id for m in doc["materials"] + doc["byproducts"]):
                used = True
                break
    uoms = body.get("uoms", {})
    if not isinstance(uoms, dict):
        fail("Konversi satuan harus berupa objek nama:faktor.")
    parsed = {label(k, "Satuan", 20): str(number(v, "Faktor satuan", True)) for k, v in uoms.items()}
    if base in parsed:
        fail("Konversi tidak boleh mengulang satuan dasar.")
    if used and (base != p.base_uom or discrete != p.discrete or parsed != json.loads(p.uoms)):
        fail("Satuan, konversi dan sifat diskret tidak dapat diubah setelah digunakan.")
    days = body.get("shelf_life_days")
    days = None if days is None else integer(days, "Umur simpan", 0)
    kid = body.get("kitchen_id")
    kid = None if kid is None else get(db, Kitchen, kid).id
    if kind in MADE:
        if days is None or kid is None:
            fail("Produk hasil produksi wajib memiliki umur simpan dan dapur.")
        kitchen = get(db, Kitchen, kid)
        if (kind == "package") != (kitchen.kind == "packing"):
            fail("Paket dibuat di packing; produk lain dibuat di dapur produksi.")
    if pid and p.kitchen_id != kid and not body.get("change_reason"):
        fail("Perubahan dapur wajib disertai alasan.")
    p.code = label(body.get("code"), "Kode produk", 50).upper()
    p.name = label(body.get("name"), "Nama produk", 200)
    p.kind, p.base_uom, p.uoms, p.discrete = kind, base, dump(parsed), discrete
    p.kitchen_id, p.shelf_life_days = kid, days
    p.selling_price = number(body.get("selling_price", 0), "Harga jual", scale=8)
    p.active = flag(body.get("active", True), "Status aktif")
    if pid:
        p.revision += 1
    db.add(p)
    db.flush()
    # An edit must not silently invalidate an already active recipe.
    for active_bom in db.query(Bom).filter_by(status="active"):
        validate_bom(db, get(db, Product, active_bom.product_id), json.loads(active_bom.document))
    db.add(Audit(actor_id=user.id, operation="product_change", document=dump({"before": old, "after": product_dict(p), "reason": body.get("change_reason")})))
    return product_dict(p)


def quantity_for(p, qty):
    q = number(qty, "Qty", True)
    if p.discrete and q != q.to_integral_value():
        fail(f"Qty {p.name} harus bulat dalam satuan {p.base_uom}.")
    return q


def validate_bom(db, product, body):
    if not isinstance(body, dict):
        fail("Isi BOM tidak valid.")
    if not product.active or product.kind not in MADE:
        fail("BOM hanya untuk produk hasil produksi yang aktif.")
    output = quantity_for(product, body.get("output_qty"))
    materials = body.get("materials")
    if not isinstance(materials, list) or not materials or len(materials) > 200:
        fail("BOM harus memiliki 1–200 bahan/kemasan.")
    lines, seen = [], set()
    for m in materials:
        if not isinstance(m, dict):
            fail("Baris bahan tidak valid.")
        p = get(db, Product, m.get("product_id"))
        if p.id == product.id or p.id in seen or not p.active:
            fail("Bahan tidak aktif, duplikat, atau memakai produk sendiri.")
        seen.add(p.id)
        uom = label(m.get("uom", p.base_uom), "Satuan", 20)
        factors = {p.base_uom: "1", **json.loads(p.uoms)}
        if uom not in factors:
            fail(f"Satuan {uom} tidak tersedia untuk {p.name}.")
        qty = number(m.get("qty"), "Qty bahan", True)
        base = qty * Decimal(factors[uom])
        quantity_for(p, base)
        lines.append({"product_id": p.id, "qty": str(qty), "uom": uom, "factor": factors[uom], "base_qty": str(base)})
    overheads, byproducts = [], []
    overhead_list, byproduct_list = body.get("overheads", []), body.get("byproducts", [])
    if not isinstance(overhead_list, list) or not isinstance(byproduct_list, list) or len(overhead_list) > 100 or len(byproduct_list) > 100:
        fail("Daftar overhead/turunan tidak valid atau terlalu panjang.")
    for o in overhead_list:
        if not isinstance(o, dict):
            fail("Baris overhead tidak valid.")
        if number(o.get("amount", 0), "Overhead", scale=8) != 0:
            fail("Nilai overhead harus Rp0 pada tahap ini.")
        overheads.append({"name": label(o.get("name"), "Nama overhead"), "amount": "0"})
    seen_by = set()
    for b in byproduct_list:
        if not isinstance(b, dict):
            fail("Baris turunan tidak valid.")
        p = get(db, Product, b.get("product_id"))
        if p.id == product.id or p.id in seen_by or not p.active or p.kind != "byproduct":
            fail("Pilih SKU turunan aktif, tidak duplikat dan berbeda dari hasil utama.")
        if p.kitchen_id != product.kitchen_id:
            fail("Produk turunan harus ditetapkan ke dapur yang sama dengan produk utama.")
        seen_by.add(p.id)
        if number(b.get("unit_cost", 0), "HPP turunan", scale=8) != 0:
            fail("HPP turunan harus Rp0.")
        byproducts.append({"product_id": p.id, "qty": str(quantity_for(p, b.get("qty"))), "unit_cost": "0"})
    return {"output_qty": str(output), "materials": lines, "overheads": overheads, "byproducts": byproducts}


def bom_dict(b):
    return {"id": b.id, "product_id": b.product_id, "version": b.version,
            "status": b.status, "revision": b.revision, **json.loads(b.document)}


def save_bom(db, user, body, bid=None):
    admin(user)
    bom = get(db, Bom, bid) if bid else None
    if bom and (bom.status != "draft" or integer(body.get("revision"), "Versi") != bom.revision):
        fail("Hanya draft versi terbaru yang dapat diedit.", 409)
    pid = bom.product_id if bom else integer(body.get("product_id"), "Produk")
    if bom and integer(body.get("product_id"), "Produk") != bom.product_id:
        fail("Produk hasil pada versi BOM tidak dapat diganti.")
    p = get(db, Product, pid)
    document = validate_bom(db, p, body)
    if not bom:
        ver = (db.query(func.max(Bom.version)).filter_by(product_id=pid).scalar() or 0) + 1
        bom = Bom(product_id=pid, version=ver, status="draft", revision=1, created_by=user.id)
    else:
        bom.revision += 1
    bom.output_qty = Decimal(document["output_qty"])
    bom.document = dump(document)
    db.add(bom)
    db.flush()
    return bom_dict(bom)


def activate_bom(db, user, bid):
    admin(user)
    bom = get(db, Bom, bid)
    if bom.status != "draft":
        fail("Hanya BOM draft yang dapat diaktifkan.", 409)
    p = get(db, Product, bom.product_id)
    document = validate_bom(db, p, json.loads(bom.document))
    if p.kitchen_id is None or p.shelf_life_days is None:
        fail("Lengkapi dapur dan umur simpan produk.")
    graph = {}
    for active in db.query(Bom).filter_by(status="active"):
        graph[active.product_id] = [m["product_id"] for m in json.loads(active.document)["materials"]]
    graph[p.id] = [m["product_id"] for m in document["materials"]]
    visiting, done = set(), set()

    def visit(node):
        if node in visiting:
            fail("BOM membentuk siklus resep.")
        if node in done:
            return
        visiting.add(node)
        for child in graph.get(node, []):
            visit(child)
        visiting.remove(node)
        done.add(node)

    for node in graph:
        visit(node)
    for old in db.query(Bom).filter_by(product_id=p.id, status="active"):
        old.status = "retired"
    bom.document = dump(document)
    bom.status, bom.approved_by, bom.approved_at = "active", user.id, now()
    bom.revision += 1
    return bom_dict(bom)


def movement(db, balance, lot, qty, kind, reference, user):
    db.add(Movement(balance_id=balance.id, kind=kind, qty_delta=qty,
                    unit_cost=lot.unit_cost, reference=reference, actor_id=user.id))


def stock_rows(db, user):
    ids = allowed_warehouses(db, user)
    query = db.query(Balance, Lot).join(Lot, Lot.id == Balance.lot_id).filter(Balance.qty > 0)
    if ids is not None:
        query = query.filter(Balance.warehouse_id.in_(ids))
    return [{"balance_id": b.id, "lot_id": l.id, "product_id": l.product_id,
             "warehouse_id": b.warehouse_id, "batch_number": l.batch_number,
             "expiry_date": str(l.expiry_date) if l.expiry_date else None,
             "qty": str(b.qty), "unit_cost": str(l.unit_cost), "blocked": l.blocked,
             "usable": not l.blocked and l.expiry_date is not None and l.expiry_date >= today()}
            for b, l in query.order_by(Lot.expiry_date, Lot.received_at, Lot.id)]


def fefo(db, product, warehouse, qty):
    need, picks = quantity_for(product, qty), []
    rows = db.query(Balance, Lot).join(Lot, Lot.id == Balance.lot_id).filter(
        Balance.warehouse_id == warehouse.id, Lot.product_id == product.id,
        Balance.qty > 0, Lot.blocked.is_(False), Lot.expiry_date >= today()
    ).order_by(Lot.expiry_date, Lot.received_at, Lot.id).all()
    for balance, lot in rows:
        take = min(need, balance.qty)
        if take > 0:
            picks.append((balance, lot, take))
            need -= take
        if need == 0:
            break
    if need > 0:
        fail(f"Stok layak {product.name} tidak cukup di {warehouse.name}; kurang {need} {product.base_uom}.", 409)
    return picks


def receive_stock(db, user, body):
    wh = warehouse_access(db, user, body.get("warehouse_id"))
    if wh.kind != "central":
        fail("Penerimaan pembelian dilakukan di Gudang Central; gunakan transfer untuk dapur.")
    p = get(db, Product, body.get("product_id"))
    if not p.active:
        fail("Produk tidak aktif.")
    try:
        exp = date.fromisoformat(body.get("expiry_date", ""))
    except (ValueError, TypeError):
        fail("Tanggal kedaluwarsa wajib dalam format YYYY-MM-DD.")
    if exp < today():
        fail("Tidak dapat menerima barang kedaluwarsa.")
    qty = quantity_for(p, body.get("qty"))
    lot = Lot(product_id=p.id, batch_number=label(body.get("batch_number"), "Batch"),
              expiry_date=exp, unit_cost=number(body.get("unit_cost"), "HPP satuan dasar", scale=8))
    db.add(lot)
    db.flush()
    bal = Balance(lot_id=lot.id, warehouse_id=wh.id, qty=qty)
    db.add(bal)
    db.flush()
    movement(db, bal, lot, qty, "RECEIPT", label(body.get("reference"), "Referensi", 150), user)
    return {"lot_id": lot.id, "qty": str(qty)}


def consume(db, user, body):
    wh = warehouse_access(db, user, body.get("warehouse_id"))
    p = get(db, Product, body.get("product_id"))
    if not p.active:
        fail("Produk tidak aktif.")
    ref = label(body.get("reference"), "Alasan/referensi pemakaian", 150)
    picks = fefo(db, p, wh, body.get("qty"))
    cost = Decimal(0)
    for balance, lot, qty in picks:
        balance.qty -= qty
        movement(db, balance, lot, -qty, "USAGE", ref, user)
        cost += qty * lot.unit_cost
    return {"cost": str(cost), "picks": [{"lot_id": l.id, "qty": str(q)} for _, l, q in picks]}


def ship(db, user, body):
    src = warehouse_access(db, user, body.get("source_id"))
    dst = get(db, Warehouse, body.get("destination_id"))
    if not dst.active or src.id == dst.id:
        fail("Gudang tujuan harus aktif dan berbeda dari asal.")
    p = get(db, Product, body.get("product_id"))
    if not p.active:
        fail("Produk tidak aktif.")
    picks = fefo(db, p, src, body.get("qty"))
    transfer = Transfer(source_id=src.id, destination_id=dst.id, reference=label(body.get("reference"), "Referensi", 150), created_by=user.id)
    db.add(transfer)
    db.flush()
    for balance, lot, qty in picks:
        balance.qty -= qty
        db.add(TransferLine(transfer_id=transfer.id, lot_id=lot.id, shipped_qty=qty, received_qty=0))
        movement(db, balance, lot, -qty, "TRANSFER_OUT", f"TRF-{transfer.id}", user)
    db.flush()
    return transfer_dict(db, transfer)


def transfer_dict(db, t):
    return {"id": t.id, "source_id": t.source_id, "destination_id": t.destination_id,
            "reference": t.reference, "status": t.status,
            "lines": [{"id": l.id, "lot_id": l.lot_id, "shipped_qty": str(l.shipped_qty),
                       "received_qty": str(l.received_qty), "remaining": str(l.shipped_qty - l.received_qty)}
                      for l in db.query(TransferLine).filter_by(transfer_id=t.id).order_by(TransferLine.id)]}


def receive_transfer(db, user, tid, body):
    t = get(db, Transfer, tid)
    warehouse_access(db, user, t.destination_id)
    if t.status == "received":
        fail("Transfer sudah diterima seluruhnya.", 409)
    lines = {l.id: l for l in db.query(TransferLine).filter_by(transfer_id=t.id)}
    entries = body.get("lines")
    if not isinstance(entries, list) or not entries:
        fail("Isi minimal satu jumlah diterima.")
    seen, total = set(), Decimal(0)
    for entry in entries:
        if not isinstance(entry, dict):
            fail("Baris penerimaan tidak valid.")
        lid = integer(entry.get("id"), "Baris transfer")
        if lid not in lines or lid in seen:
            fail("Baris transfer salah atau duplikat.")
        seen.add(lid)
        line = lines[lid]
        qty = number(entry.get("qty"), "Qty diterima")
        lot = get(db, Lot, line.lot_id)
        p = get(db, Product, lot.product_id)
        if p.discrete and qty != qty.to_integral_value():
            fail("Qty produk diskret harus bulat.")
        if qty > line.shipped_qty - line.received_qty:
            fail("Jumlah diterima melebihi sisa kiriman.")
        if qty == 0:
            continue
        bal = db.query(Balance).filter_by(lot_id=lot.id, warehouse_id=t.destination_id).first()
        if not bal:
            bal = Balance(lot_id=lot.id, warehouse_id=t.destination_id, qty=0)
            db.add(bal)
            db.flush()
        bal.qty += qty
        line.received_qty += qty
        total += qty
        # Physical receipt is allowed even if it expired in transit; FEFO blocks use.
        movement(db, bal, lot, qty, "TRANSFER_IN", f"TRF-{t.id}", user)
    if total == 0:
        fail("Jumlah diterima harus lebih dari nol.")
    t.status = "received" if all(l.shipped_qty == l.received_qty for l in lines.values()) else "partial"
    return transfer_dict(db, t)


def install(app, sessions, engine, ready_user, get_db, state_model, user_model, static_dir):
    @app.get("/manufacturing", include_in_schema=False)
    def page():
        return FileResponse(static_dir + "/manufacturing.html", headers={"Cache-Control": "no-cache"})

    @app.get("/static/manufacturing.js", include_in_schema=False)
    def script():
        return FileResponse(static_dir + "/manufacturing.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/api/manufacturing/setup")
    def setup(u=Depends(ready_user), db=Depends(get_db)):
        c = control(db)
        preview = None
        if u.role == "admin" and not c.active:
            preview, _ = migration_preview(db, state_model)
        return {"active": c.active, "schema_version": c.schema_version, "preview": preview}

    @app.get("/api/manufacturing/catalog")
    def catalog(u=Depends(ready_user), db=Depends(get_db)):
        return {"active": control(db).active, "user": {"id": u.id, "name": u.name, "role": u.role},
                "warehouse_access": sorted(allowed_warehouses(db, u)) if u.role != "admin" else None,
                "warehouses": [{"id": w.id, "code": w.code, "name": w.name, "kind": w.kind, "active": w.active} for w in db.query(Warehouse).order_by(Warehouse.id)],
                "kitchens": [{"id": k.id, "code": k.code, "name": k.name, "kind": k.kind, "warehouse_id": k.warehouse_id} for k in db.query(Kitchen).order_by(Kitchen.id)],
                "products": [product_dict(p) for p in db.query(Product).order_by(Product.code)],
                "boms": [bom_dict(b) for b in db.query(Bom).order_by(Bom.id)]}

    @app.get("/api/manufacturing/stock")
    def stock(u=Depends(ready_user), db=Depends(get_db)):
        require_active(db)
        return stock_rows(db, u)

    @app.get("/api/manufacturing/transfers")
    def transfers(u=Depends(ready_user), db=Depends(get_db)):
        require_active(db)
        ids = allowed_warehouses(db, u)
        return [transfer_dict(db, t) for t in db.query(Transfer).order_by(Transfer.id.desc())
                if ids is None or t.source_id in ids or t.destination_id in ids]

    @app.get("/api/manufacturing/movements")
    def movements(u=Depends(ready_user), db=Depends(get_db)):
        require_active(db)
        ids = allowed_warehouses(db, u)
        q = db.query(Movement, Balance).join(Balance, Balance.id == Movement.balance_id)
        if ids is not None:
            q = q.filter(Balance.warehouse_id.in_(ids))
        return [{"id": m.id, "lot_id": b.lot_id, "warehouse_id": b.warehouse_id, "kind": m.kind,
                 "qty": str(m.qty_delta), "reference": m.reference, "actor_id": m.actor_id, "at": str(m.created_at)}
                for m, b in q.order_by(Movement.id.desc()).limit(300)]

    @app.get("/api/manufacturing/archive")
    def archive(u=Depends(ready_user), db=Depends(get_db)):
        admin(u)
        c = control(db)
        return {"source_version": c.legacy_version, "data": json.loads(c.archive) if c.archive else None}

    @app.get("/api/manufacturing/access")
    def access_list(u=Depends(ready_user), db=Depends(get_db)):
        admin(u)
        return [{"user_id": a.user_id, "warehouse_id": a.warehouse_id} for a in db.query(Access)]

    @app.post("/api/manufacturing/commands/{operation}")
    async def command(operation: str, request: Request, u=Depends(ready_user), db=Depends(get_db)):
        try:
            payload = await request.json()
        except ValueError:
            fail("JSON tidak valid.")
        if not isinstance(payload, dict):
            fail("Isi permintaan harus objek.")

        def action(who):
            if operation == "activate":
                return migrate(db, who, payload, state_model)
            if operation == "save-product":
                return save_product(db, who, payload, payload.get("id"))
            if operation == "save-bom":
                return save_bom(db, who, payload, payload.get("id"))
            if operation == "activate-bom":
                return activate_bom(db, who, payload.get("id"))
            if operation == "simulate-bom":
                b = get(db, Bom, payload.get("id"))
                p = get(db, Product, b.product_id)
                ratio = quantity_for(p, payload.get("target_qty")) / b.output_qty
                doc = json.loads(b.document)
                rows = []
                for m in doc["materials"]:
                    amount = Decimal(m["base_qty"]) * ratio
                    component = get(db, Product, m["product_id"])
                    quantity_for(component, amount)
                    rows.append({"product_id": component.id, "base_qty": str(amount), "uom": component.base_uom})
                return {"ratio": str(ratio), "materials": rows}
            if operation == "receipt":
                return receive_stock(db, who, payload)
            if operation == "usage":
                return consume(db, who, payload)
            if operation == "ship":
                return ship(db, who, payload)
            if operation == "receive-transfer":
                return receive_transfer(db, who, payload.get("id"), payload)
            if operation == "set-access":
                admin(who)
                uid = integer(payload.get("user_id"), "Pengguna")
                get(db, user_model, uid)
                ids = payload.get("warehouse_ids")
                if not isinstance(ids, list):
                    fail("Daftar gudang tidak valid.")
                ids = {get(db, Warehouse, wid).id for wid in ids}
                db.query(Access).filter_by(user_id=uid).delete()
                for wid in ids:
                    db.add(Access(user_id=uid, warehouse_id=wid))
                return {"user_id": uid, "warehouse_ids": sorted(ids)}
            if operation == "correct-lot":
                admin(who)
                lot = get(db, Lot, payload.get("id"))
                label(payload.get("reason"), "Alasan koreksi")
                try:
                    exp = date.fromisoformat(payload.get("expiry_date", ""))
                except (ValueError, TypeError):
                    fail("Tanggal kedaluwarsa tidak valid.")
                if lot.expiry_date is not None:
                    fail("Koreksi ini hanya untuk melengkapi ED lot impor yang kosong.")
                lot.expiry_date, lot.blocked = exp, False
                return {"lot_id": lot.id, "expiry_date": exp.isoformat()}
            fail("Perintah tidak ditemukan.", 404)

        return execute(db, u, operation, payload, request.headers.get("Idempotency-Key"), action,
                       active=operation != "activate")
