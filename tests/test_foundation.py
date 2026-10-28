"""API-level acceptance tests. No live accounts or production DB are used."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import secrets
import sys
import tempfile

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
TEST_DIR = tempfile.TemporaryDirectory()
db_url = os.getenv("TEST_DATABASE_URL", "sqlite:///" + str(Path(TEST_DIR.name) / "inventory.db"))
if not db_url.startswith("sqlite:") and not db_url.endswith("/inventory_test"):
    raise RuntimeError("Integration tests only accept a database named inventory_test")
os.environ["DATABASE_URL"] = db_url
os.environ["SEED_DEMO_USERS"] = "false"
os.environ["AUDIT_LOG_PATH"] = str(Path(TEST_DIR.name) / "audit.jsonl")

import main
import inventory as inv
import inventory_models as m


def key():
    return secrets.token_hex(16)


def cmd(client, operation, body, request_key=None):
    if operation == "ship":
        body = {"sender_name": "Pengirim Uji", "vehicle_number": "BE 1234 AA", "document_number": body.get("reference", "TEST-DOC"), "shipped_date": inv.today().isoformat(), **body}
    if operation == "receive-transfer":
        body = {"receiver_name": "Penerima Uji", "received_date": inv.today().isoformat(), **body}
    return client.post("/api/manufacturing/commands/" + operation, json=body,
                       headers={"Idempotency-Key": request_key or key()})


@pytest.fixture()
def client():
    m.Base.metadata.drop_all(main.engine)
    main.Base.metadata.drop_all(main.engine)
    password = "A" + secrets.token_urlsafe(20) + "1"
    os.environ["ADMIN_PASSWORD"] = password
    main.ADMIN_PASSWORD = password
    with TestClient(main.app) as c:
        with main.SessionLocal() as db:
            u = db.query(main.User).filter_by(username="admin").one()
            u.must_change_password = False
            db.commit()
        assert c.post("/api/auth/login", json={"username": "admin", "password": password}).status_code == 200
        yield c


def activate(c, data=None):
    if data is not None:
        assert c.put("/api/state", json={"version": 0, "data": data}).status_code == 200
    preview = c.get("/api/manufacturing/setup").json()["preview"]
    r = cmd(c, "activate", {"source_version": preview["source_version"]})
    assert r.status_code == 200, r.text
    return c.get("/api/manufacturing/catalog").json()


def make_product(c, code="FLOUR", **changes):
    body = {"code": code, "name": code, "kind": "raw", "base_uom": "kg",
            "uoms": {}, "discrete": False, "active": True}
    body.update(changes)
    r = cmd(c, "save-product", body)
    assert r.status_code == 200, r.text
    return r.json()


def receipt(c, warehouse, p, qty="10", cost="20000", days=30, batch="B1"):
    r = cmd(c, "receipt", {"warehouse_id": warehouse, "product_id": p,
            "qty": qty, "unit_cost": cost, "batch_number": batch,
            "expiry_date": (inv.today() + timedelta(days=days)).isoformat(), "reference": "SUPPLIER-1"})
    assert r.status_code == 200, r.text
    return r.json()


def central(catalog):
    return next(w["id"] for w in catalog["warehouses"] if w["kind"] == "central")


def bom(c, product, material, **changes):
    body = {"product_id": product, "output_qty": "40", "materials": [{"product_id": material, "qty": "1", "uom": "kg"}],
            "overheads": [{"name": "Gas", "amount": "0"}], "byproducts": []}
    body.update(changes)
    r = cmd(c, "save-bom", body)
    assert r.status_code == 200, r.text
    return r.json()


def test_seed_is_idempotent_and_legacy_remains_available(client):
    inv.initialize(main.engine, main.SessionLocal)
    cat = client.get("/api/manufacturing/catalog").json()
    assert [k["code"] for k in cat["kitchens"]] == [f"D{i:02}" for i in range(1, 11)] + ["PACK"]
    assert len({k["warehouse_id"] for k in cat["kitchens"]}) == 11
    assert not cat["active"]
    r = client.put("/api/state", json={"version": 0, "data": {"products": []}})
    assert r.status_code == 200
    assert cmd(client, "save-product", {}).status_code == 409


def test_activation_archives_imports_and_blocks_legacy_writes(client):
    data = {"warehouses": [{"id": 21, "code": "CENTRAL", "name": "Central", "isCentral": True, "isActive": True}],
            "products": [{"id": 31, "code": "F1", "name": "Tepung", "baseUom": "kg", "uoms": [{"name": "sak", "factor": 25}]}],
            "batches": [{"id": 41, "warehouseId": 21, "productId": 31, "qty": 10, "cost": 20000,
                         "batchNo": "OLD-BATCH", "expDate": None}]}
    activate(client, data)
    rows = client.get("/api/manufacturing/stock").json()
    assert len(rows) == 1 and rows[0]["qty"] == "10.000000"
    assert rows[0]["blocked"] and not rows[0]["usable"]
    archive = client.get("/api/manufacturing/archive").json()
    assert archive["data"] == data and archive["source_version"] == 1
    assert client.put("/api/state", json={"version": 2, "data": {}}).status_code == 409
    assert client.get("/api/state").json()["foundationActive"]
    with main.SessionLocal() as db:
        assert db.query(m.Movement).count() == 1
        assert db.query(m.Lot).count() == 1


@pytest.mark.parametrize("collection,status", [("transfers", "dikirim"), ("transfers", "draft"),
    ("scraps", "draft"), ("opnames", "menghitung"), ("pos", "dipesan")])
def test_migration_refuses_open_documents(client, collection, status):
    data = {collection: [{"id": 1, "no": "OPEN", "status": status}]}
    assert client.put("/api/state", json={"version": 0, "data": data}).status_code == 200
    r = cmd(client, "activate", {"source_version": 1})
    assert r.status_code == 409 and "OPEN" in r.text
    assert not client.get("/api/manufacturing/setup").json()["active"]


def test_migration_stale_preview_and_duplicate_retry(client):
    client.put("/api/state", json={"version": 0, "data": {}})
    assert cmd(client, "activate", {"source_version": 0}).status_code == 409
    request_key = key()
    first = cmd(client, "activate", {"source_version": 1}, request_key)
    assert first.status_code == 200
    assert cmd(client, "activate", {"source_version": 1}, request_key).json() == first.json()
    assert cmd(client, "activate", {"source_version": 2}, request_key).status_code == 409


def test_master_shelf_life_kitchen_and_optimistic_revision(client):
    cat = activate(client)
    k = cat["kitchens"][0]["id"]
    p = make_product(client, "ROTI", kind="finished", base_uom="pcs", discrete=True, shelf_life_days=3, kitchen_id=k)
    assert cmd(client, "save-product", {**p, "shelf_life_days": -1}).status_code == 422
    assert cmd(client, "save-product", {**p, "kind": "package"}).status_code == 422
    other = cat["kitchens"][1]["id"]
    assert cmd(client, "save-product", {**p, "kitchen_id": other}).status_code == 422
    r = cmd(client, "save-product", {**p, "kitchen_id": other, "change_reason": "Penataan dapur"})
    assert r.status_code == 200 and r.json()["revision"] == 2
    assert cmd(client, "save-product", p).status_code == 409


def test_bom_versions_zero_overhead_simulation_and_immutability(client):
    cat = activate(client)
    p = make_product(client)
    result = make_product(client, "BREAD", kind="finished", base_uom="pcs", discrete=True,
                          shelf_life_days=3, kitchen_id=cat["kitchens"][0]["id"])
    b = bom(client, result["id"], p["id"])
    assert cmd(client, "activate-bom", {"id": b["id"]}).status_code == 200
    r = cmd(client, "simulate-bom", {"id": b["id"], "target_qty": "80"})
    assert r.status_code == 200 and float(r.json()["materials"][0]["base_qty"]) == 2
    assert cmd(client, "save-bom", {**b, "output_qty": "50"}).status_code == 409
    assert cmd(client, "save-bom", {**b, "id": None, "overheads": [{"name": "Gas", "amount": "1"}]}).status_code == 422
    second = bom(client, result["id"], p["id"])
    assert second["version"] == 2
    assert cmd(client, "activate-bom", {"id": second["id"]}).status_code == 200
    boms = client.get("/api/manufacturing/catalog").json()["boms"]
    assert [b["status"] for b in boms] == ["retired", "active"]


def test_bom_indirect_cycle_and_byproduct_cost(client):
    cat = activate(client)
    kid = cat["kitchens"][0]["id"]
    a = make_product(client, "A", kind="wip", shelf_life_days=2)
    b = make_product(client, "B", kind="wip", shelf_life_days=2)
    by = make_product(client, "WHITE", kind="byproduct", shelf_life_days=2, selling_price="10000")
    first = bom(client, a["id"], b["id"], byproducts=[{"product_id": by["id"], "qty": "1", "unit_cost": "0"}])
    assert cmd(client, "activate-bom", {"id": first["id"]}).status_code == 200
    cycle = bom(client, b["id"], a["id"])
    assert cmd(client, "activate-bom", {"id": cycle["id"]}).status_code == 422
    invalid = {"product_id": a["id"], "output_qty": "40", "materials": [{"product_id": b["id"], "qty": "1"}],
               "byproducts": [{"product_id": by["id"], "qty": "1", "unit_cost": "1"}]}
    assert cmd(client, "save-bom", invalid).status_code == 422
    assert cmd(client, "save-product", {**by, "active": False}).status_code == 422


def test_fefo_consumption_and_insufficient_stock_is_atomic(client):
    cat = activate(client)
    wh = central(cat)
    p = make_product(client)
    later = receipt(client, wh, p["id"], qty="10", days=30)
    earlier = receipt(client, wh, p["id"], qty="2", days=5, batch="EARLY")
    r = cmd(client, "usage", {"warehouse_id": wh, "product_id": p["id"], "qty": "3", "reference": "USE-1"})
    assert r.status_code == 200
    assert [x["lot_id"] for x in r.json()["picks"]] == [earlier["lot_id"], later["lot_id"]]
    assert float(r.json()["cost"]) == 60000
    before = client.get("/api/manufacturing/stock").json()
    assert cmd(client, "usage", {"warehouse_id": wh, "product_id": p["id"], "qty": "99", "reference": "TOO-MUCH"}).status_code == 409
    assert client.get("/api/manufacturing/stock").json() == before


def test_receipt_idempotency_and_input_validation(client):
    cat = activate(client)
    wh = central(cat)
    p = make_product(client)
    body = {"warehouse_id": wh, "product_id": p["id"], "qty": "2", "unit_cost": "10",
            "batch_number": "B", "expiry_date": inv.today().isoformat(), "reference": "IN"}
    request_key = key()
    one, two = cmd(client, "receipt", body, request_key), cmd(client, "receipt", body, request_key)
    assert one.status_code == two.status_code == 200 and one.json() == two.json()
    assert cmd(client, "receipt", {**body, "qty": "3"}, request_key).status_code == 409
    for value in ["NaN", "Infinity", "-1", "0", "0.0000001", True, "1000000000000"]:
        assert cmd(client, "receipt", {**body, "qty": value}).status_code == 422
    assert client.post("/api/manufacturing/commands/receipt", json=body).status_code == 422
    assert cmd(client, "receipt", {**body, "expiry_date": (inv.today()-timedelta(days=1)).isoformat()}).status_code == 422
    assert len(client.get("/api/manufacturing/stock").json()) == 1


def test_transfer_partial_receipt_keeps_transit_and_cost(client):
    cat = activate(client)
    wh, dest = central(cat), cat["kitchens"][0]["warehouse_id"]
    p = make_product(client)
    lot = receipt(client, wh, p["id"], qty="100")
    r = cmd(client, "ship", {"source_id": wh, "destination_id": dest, "product_id": p["id"], "qty": "100", "reference": "DAPUR"})
    assert r.status_code == 200
    t = r.json()
    assert client.get("/api/manufacturing/stock").json() == []
    received = cmd(client, "receive-transfer", {"id": t["id"], "lines": [{"id": t["lines"][0]["id"], "qty": "98"}]})
    assert received.status_code == 200
    assert received.json()["status"] == "partial" and float(received.json()["lines"][0]["remaining"]) == 2
    s = client.get("/api/manufacturing/stock").json()[0]
    assert s["warehouse_id"] == dest and s["lot_id"] == lot["lot_id"] and float(s["unit_cost"]) == 20000
    assert cmd(client, "receive-transfer", {"id": t["id"], "lines": [{"id": t["lines"][0]["id"], "qty": "3"}]}).status_code == 422
    assert cmd(client, "receive-transfer", {"id": t["id"], "lines": [{"id": t["lines"][0]["id"], "qty": "2"}]}).json()["status"] == "received"


def test_expired_blocked_and_missing_expiry_cannot_be_consumed(client):
    cat = activate(client)
    wh = central(cat)
    p = make_product(client)
    lot = receipt(client, wh, p["id"])
    with main.SessionLocal() as db:
        db.get(m.Lot, lot["lot_id"]).expiry_date = inv.today() - timedelta(days=1)
        db.commit()
    body = {"warehouse_id": wh, "product_id": p["id"], "qty": "1", "reference": "USE"}
    assert cmd(client, "usage", body).status_code == 409
    with main.SessionLocal() as db:
        l = db.get(m.Lot, lot["lot_id"])
        l.expiry_date, l.blocked = inv.today(), True
        db.commit()
    assert cmd(client, "usage", body).status_code == 409


def test_api_scope_and_master_roles(client):
    cat = activate(client)
    wh, dapur = central(cat), cat["kitchens"][0]["warehouse_id"]
    p = make_product(client)
    receipt(client, wh, p["id"])
    with main.SessionLocal() as db:
        password = "A" + secrets.token_urlsafe(15) + "1"
        u = main.User(username="staff", name="Staf", role="gudang", password_hash=main.hash_pw(password), is_active=True, must_change_password=False)
        db.add(u); db.commit(); uid = u.id
    # No warehouse_id does not mean all warehouses in the new API.
    with TestClient(main.app) as staff:
        assert staff.post("/api/auth/login", json={"username": "staff", "password": password}).status_code == 200
        assert staff.get("/api/manufacturing/stock").json() == []
        assert cmd(staff, "usage", {"warehouse_id": wh, "product_id": p["id"], "qty": "1", "reference": "NO"}).status_code == 403
        assert cmd(staff, "save-product", {}).status_code == 403
        assert staff.get("/api/manufacturing/archive").status_code == 403
        assert cmd(client, "set-access", {"user_id": uid, "warehouse_ids": [dapur]}).status_code == 200
        assert cmd(staff, "usage", {"warehouse_id": wh, "product_id": p["id"], "qty": "1", "reference": "NO"}).status_code == 403


def test_concurrent_consumption_never_oversells(client):
    cat = activate(client)
    wh = central(cat)
    p = make_product(client)
    receipt(client, wh, p["id"], qty="10")
    cookies = dict(client.cookies)

    def use_stock(_):
        with TestClient(main.app) as other:
            other.cookies.update(cookies)
            return cmd(other, "usage", {"warehouse_id": wh, "product_id": p["id"], "qty": "7", "reference": "RACE"}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(use_stock, [1, 2]))
    assert sorted(results) == [200, 409]
    assert float(client.get("/api/manufacturing/stock").json()[0]["qty"]) == 3


def test_frontend_assets_and_authentication(client):
    assert client.get("/manufacturing").status_code == 200
    assert "BOM" in client.get("/static/manufacturing.js").text
    with TestClient(main.app) as anon:
        assert anon.get("/api/manufacturing/catalog").status_code == 401
        assert cmd(anon, "activate", {"source_version": 0}).status_code == 401


def test_bad_nested_bom_payloads_fail_cleanly(client):
    cat = activate(client)
    p = make_product(client, "WIP", kind="wip", shelf_life_days=2)
    material = make_product(client)
    for field, bad in [("materials", [None]), ("overheads", None), ("overheads", [None]), ("byproducts", {})]:
        r = cmd(client, "save-bom", {"product_id": p["id"], "output_qty": "1", "materials": [{"product_id": material["id"], "qty": "1"}], field: bad})
        assert r.status_code == 422, r.text


def test_failed_migration_rolls_back_master_and_control(client):
    # Validation failure after warehouse insert must not leave partial cutover.
    data = {"warehouses": [{"id": 1, "code": "OLD", "name": "Central", "isCentral": True}],
            "products": [{"id": 1, "code": "BROKEN", "name": "", "baseUom": "kg"}]}
    assert client.put("/api/state", json={"version": 0, "data": data}).status_code == 200
    assert cmd(client, "activate", {"source_version": 1}).status_code == 422
    with main.SessionLocal() as db:
        assert not db.get(m.Control, 1).active
        assert db.query(m.Warehouse).count() == 11
        assert db.query(m.Product).count() == 0
        assert db.get(main.AppState, 1).version == 1


def test_migration_preserves_receipt_time_and_can_complete_missing_ed(client):
    data = {"warehouses": [{"id": 1, "code": "OLD", "name": "Central", "isCentral": True}],
            "products": [{"id": 1, "code": "OLD-P", "name": "Bahan", "baseUom": "kg"}],
            "batches": [{"id": 1, "warehouseId": 1, "productId": 1, "qty": 1, "cost": 0,
                         "batchNo": "B", "expDate": None, "inboundAt": 1704067200000}]}
    cat = activate(client, data)
    row = client.get("/api/manufacturing/stock").json()[0]
    with main.SessionLocal() as db:
        assert db.get(m.Lot, row["lot_id"]).received_at.isoformat() == "2024-01-01T00:00:00"
    assert cmd(client, "usage", {"warehouse_id": central(cat), "product_id": row["product_id"], "qty": 1, "reference": "NO-ED"}).status_code == 409
    assert cmd(client, "correct-lot", {"id": row["lot_id"], "expiry_date": inv.today().isoformat(), "reason": "Dokumen sumber"}).status_code == 200
    assert cmd(client, "usage", {"warehouse_id": central(cat), "product_id": row["product_id"], "qty": 1, "reference": "HAS-ED"}).status_code == 200


def test_bom_uom_conversion_and_discrete_scaling(client):
    cat = activate(client)
    material = make_product(client, uoms={"sak": "25"})
    p = make_product(client, "BREAD", kind="finished", base_uom="pcs", discrete=True,
                     shelf_life_days=3, kitchen_id=cat["kitchens"][0]["id"])
    b = bom(client, p["id"], material["id"], materials=[{"product_id": material["id"], "qty": "0.5", "uom": "sak"}])
    assert float(b["materials"][0]["base_qty"]) == 12.5
    r = cmd(client, "simulate-bom", {"id": b["id"], "target_qty": 80})
    assert r.status_code == 200 and float(r.json()["materials"][0]["base_qty"]) == 25
    assert cmd(client, "simulate-bom", {"id": b["id"], "target_qty": "1.5"}).status_code == 422


@pytest.mark.parametrize('kind', ['raw', 'packaging', 'byproduct'])
def test_non_finished_cannot_own_kitchen_or_bom(client, kind):
    cat = activate(client)
    p = make_product(client, 'NONFINISHED', kind=kind, shelf_life_days=3)
    material = make_product(client)
    assert cmd(client, 'save-product', {**p, 'kitchen_id': cat['kitchens'][0]['id'], 'change_reason': 'test'}).status_code == 422
    assert cmd(client, 'save-bom', {'product_id': p['id'], 'output_qty': '1', 'materials': [{'product_id': material['id'], 'qty': '1'}]}).status_code == 422


def test_wip_bom_activates_without_master_kitchen(client):
    activate(client)
    p = make_product(client, 'WIP', kind='wip', shelf_life_days=3)
    raw = make_product(client)
    b = bom(client, p['id'], raw['id'])
    assert p['kitchen_id'] is None
    assert cmd(client, 'activate-bom', {'id': b['id']}).status_code == 200


def test_location_crud_versions_and_restart(client):
    cat = activate(client)
    w = cmd(client, 'save-warehouse', {'code': 'new', 'name': 'Gudang baru', 'kind': 'kitchen'}).json()
    assert w['code'] == 'NEW'
    k = cmd(client, 'save-kitchen', {'code': 'D11', 'name': 'Dapur 11', 'kind': 'production', 'warehouse_id': w['id']}).json()
    assert 'version' in k
    assert cmd(client, 'save-kitchen', {**k, 'id': None, 'code': 'D12'}).status_code == 409
    assert cmd(client, 'save-warehouse', {**w, 'id': None}).status_code == 409
    assert cmd(client, 'save-kitchen', {**k, 'kind': 'packing'}).status_code == 422
    assert cmd(client, 'delete-warehouse', w).status_code == 409
    updated = cmd(client, 'save-kitchen', {**k, 'name': 'Dapur baru'}).json()
    assert updated['name'] == 'Dapur baru'
    assert cmd(client, 'save-kitchen', {**k, 'name': 'Stale'}).status_code == 409
    assert cmd(client, 'delete-kitchen', k).status_code == 409
    assert cmd(client, 'delete-kitchen', updated).status_code == 200
    changed = cmd(client, 'save-warehouse', {**w, 'active': False}).json()
    assert changed['active'] is False
    assert cmd(client, 'delete-warehouse', w).status_code == 409
    assert cmd(client, 'delete-warehouse', changed).status_code == 200
    seeded = cat['kitchens'][0]
    assert cmd(client, 'delete-kitchen', seeded).status_code == 200
    wh = next(x for x in cat['warehouses'] if x['id'] == seeded['warehouse_id'])
    assert cmd(client, 'delete-warehouse', wh).status_code == 200
    inv.initialize(main.engine, main.SessionLocal)
    cat = client.get('/api/manufacturing/catalog').json()
    assert all(x['code'] != seeded['code'] for x in cat['kitchens'])
    assert all(x['code'] != wh['code'] for x in cat['warehouses'])


def test_location_protect_products_stock_and_history(client):
    cat = activate(client)
    k = cat['kitchens'][0]
    w = next(x for x in cat['warehouses'] if x['id'] == k['warehouse_id'])
    make_product(client, 'BREAD', kind='finished', shelf_life_days=3, kitchen_id=k['id'])
    assert cmd(client, 'delete-kitchen', k).status_code == 409
    assert cmd(client, 'save-warehouse', {**w, 'active': False}).status_code == 409
    assert cmd(client, 'save-warehouse', {**w, 'kind': 'store'}).status_code == 409
    source = next(x for x in cat['warehouses'] if x['kind'] == 'central')
    assert cmd(client, 'delete-warehouse', source).status_code == 409
    assert cmd(client, 'save-warehouse', {**source, 'active': False}).status_code == 409
    assert cmd(client, 'save-warehouse', {'code': 'C2', 'name': 'Central 2', 'kind': 'central'}).status_code == 409
    second = cmd(client, 'save-warehouse', {'code': 'S2', 'name': 'Store 2', 'kind': 'store'}).json()
    p = make_product(client)
    receipt(client, source['id'], p['id'], qty='2')
    inbound = cmd(client, 'ship', {'source_id': source['id'], 'destination_id': second['id'], 'product_id': p['id'], 'qty': '2', 'reference': 'TO-STORE'}).json()
    assert cmd(client, 'receive-transfer', {'id': inbound['id'], 'lines': [{'id': x['id'], 'qty': x['remaining']} for x in inbound['lines']]}).status_code == 200
    assert cmd(client, 'delete-warehouse', second).status_code == 409
    assert cmd(client, 'save-warehouse', {**second, 'active': False}).status_code == 409
    transfer = cmd(client, 'ship', {'source_id': second['id'], 'destination_id': w['id'], 'product_id': p['id'], 'qty': '2', 'reference': 'TEST'}).json()
    assert cmd(client, 'save-warehouse', {**second, 'active': False}).status_code == 409
    assert cmd(client, 'receive-transfer', {'id': transfer['id'], 'lines': [{'id': x['id'], 'qty': x['remaining']} for x in transfer['lines']]}).status_code == 200
    assert cmd(client, 'delete-warehouse', second).status_code == 409
    assert cmd(client, 'save-warehouse', {**second, 'active': False}).status_code == 200


def test_location_admin_only_and_idempotency(client):
    activate(client)
    body = {'code': 'TEST', 'name': 'Test', 'kind': 'store'}
    token = key()
    first = cmd(client, 'save-warehouse', body, token)
    assert first.status_code == 200
    assert cmd(client, 'save-warehouse', body, token).json() == first.json()
    with main.SessionLocal() as db:
        u = db.query(main.User).filter_by(username='admin').one()
        u.role = 'gudang'
        db.commit()
    for operation in ['save-warehouse', 'save-kitchen', 'delete-warehouse', 'delete-kitchen']:
        assert cmd(client, operation, {}).status_code == 403


def test_transfer_documents_multiple_goods_receipt_dates_and_retry(client):
    cat = activate(client)
    wh, dest = central(cat), cat['kitchens'][0]['warehouse_id']
    flour, sugar = make_product(client), make_product(client, 'SUGAR')
    receipt(client, wh, flour['id'], qty='10')
    receipt(client, wh, sugar['id'], qty='20')
    yesterday = (inv.today() - timedelta(days=1)).isoformat()
    body = {'source_id': wh, 'destination_id': dest, 'document_number': 'sj-001', 'shipped_date': yesterday,
            'lines': [{'product_id': flour['id'], 'qty': '3'}, {'product_id': sugar['id'], 'qty': '5'}]}
    token = key()
    result = cmd(client, 'ship', body, token)
    assert result.status_code == 200, result.text
    t = result.json()
    assert t['document_number'] == 'SJ-001' and t['shipped_date'] == yesterday
    assert {x['product_code'] for x in t['lines']} == {'FLOUR', 'SUGAR'}
    assert all(x['uom'] == 'kg' and x['batch_number'] == 'B1' for x in t['lines'])
    assert cmd(client, 'ship', body, token).json() == t
    assert cmd(client, 'ship', body).status_code == 409
    before = client.get('/api/manufacturing/stock').json()
    bad = {**body, 'document_number': 'SJ-002', 'lines': [{'product_id': flour['id'], 'qty': '1'}, {'product_id': sugar['id'], 'qty': '999'}]}
    assert cmd(client, 'ship', bad).status_code == 409
    assert client.get('/api/manufacturing/stock').json() == before
    rbody = {'id': t['id'], 'received_date': yesterday, 'lines': [{'id': x['id'], 'qty': '1'} for x in t['lines']]}
    assert cmd(client, 'receive-transfer', {**rbody, 'received_date': (inv.today()-timedelta(days=2)).isoformat()}).status_code == 422
    assert cmd(client, 'receive-transfer', {**rbody, 'received_date': (inv.today()+timedelta(days=1)).isoformat()}).status_code == 422
    assert cmd(client, 'receive-transfer', {**rbody, 'received_date': 'wrong'}).status_code == 422
    rtoken = key()
    first = cmd(client, 'receive-transfer', rbody, rtoken)
    assert first.status_code == 200, first.text
    assert first.json()['receipts'][0]['received_date'] == yesterday
    assert cmd(client, 'receive-transfer', rbody, rtoken).json() == first.json()
    part = first.json()
    rest = {'id': t['id'], 'received_date': inv.today().isoformat(), 'lines': [{'id': x['id'], 'qty': x['remaining']} for x in part['lines']]}
    final = cmd(client, 'receive-transfer', rest).json()
    assert final['status'] == 'received'
    assert len(final['receipts']) == 2
    assert final['receipts'][1]['received_date'] == inv.today().isoformat()
    assert sum(len(r['lines']) for r in final['receipts']) == 4
    assert cmd(client, 'receive-transfer', rest).status_code == 409
    for field in ['shipped_date']:
        invalid = {**body, 'document_number': 'SJ-003', field: ''}
        assert cmd(client, 'ship', invalid).status_code == 422


def test_existing_transfer_document_upgrade_is_repeatable(client):
    cat = activate(client)
    with main.SessionLocal() as db:
        t = m.Transfer(source_id=central(cat), destination_id=cat['kitchens'][0]['warehouse_id'],
                       reference='OLD-REF', created_by=1, status='partial')
        db.add(t)
        db.flush()
        tid = t.id
        db.get(m.Control, 1).schema_version = 3
        db.commit()
    inv.initialize(main.engine, main.SessionLocal)
    inv.initialize(main.engine, main.SessionLocal)
    rows = client.get('/api/manufacturing/transfers').json()
    assert len(rows) == 1
    assert rows[0]['document_number'] == f'TRF-{tid}'
    assert rows[0]['reference'] == 'OLD-REF' and rows[0]['legacy'] is True
    assert rows[0]['receipts'] == []
    assert rows[0]['shipped_date'] == inv.today().isoformat()


def test_do_dispatch_and_receiver_required_persisted_per_receipt(client):
    cat = activate(client)
    source, dest = central(cat), cat['kitchens'][0]['warehouse_id']
    p = make_product(client)
    receipt(client, source, p['id'], qty='10')
    body = {'source_id': source, 'destination_id': dest, 'document_number': 'DO-NAMES',
            'shipped_date': inv.today().isoformat(), 'product_id': p['id'], 'qty': '3',
            'sender_name': '  Andi <Pengirim>  ', 'vehicle_number': ' be 1234 aa '}
    for field in ['sender_name', 'vehicle_number']:
        for invalid in ['', '   ', None, 'X' * 151]:
            assert cmd(client, 'ship', {**body, field: invalid}).status_code == 422
        missing = {k: v for k, v in body.items() if k != field}
        assert client.post('/api/manufacturing/commands/ship', json=missing,
                           headers={'Idempotency-Key': key()}).status_code == 422
    assert client.get('/api/manufacturing/transfers').json() == []
    result = cmd(client, 'ship', body)
    assert result.status_code == 200, result.text
    t = result.json()
    assert t['sender_name'] == 'Andi <Pengirim>' and t['vehicle_number'] == 'BE 1234 AA'
    rbody = {'id': t['id'], 'received_date': inv.today().isoformat(),
             'lines': [{'id': t['lines'][0]['id'], 'qty': '1'}]}
    assert client.post('/api/manufacturing/commands/receive-transfer', json=rbody,
                       headers={'Idempotency-Key': key()}).status_code == 422
    for invalid in ['', '  ', None, 'X' * 151]:
        assert cmd(client, 'receive-transfer', {**rbody, 'receiver_name': invalid}).status_code == 422
    first = cmd(client, 'receive-transfer', {**rbody, 'receiver_name': 'Budi'}).json()
    assert first['receipts'][0]['receiver_name'] == 'Budi'
    token = key()
    last_body = {**rbody, 'receiver_name': 'Sari', 'lines': [{'id': t['lines'][0]['id'], 'qty': '2'}]}
    final = cmd(client, 'receive-transfer', last_body, token).json()
    assert cmd(client, 'receive-transfer', last_body, token).json() == final
    stored = client.get('/api/manufacturing/transfers').json()[0]
    assert stored['status'] == 'received'
    assert [r['receiver_name'] for r in stored['receipts']] == ['Budi', 'Sari']
    assert stored['sender_name'] == 'Andi <Pengirim>'


def test_do_identity_upgrade_does_not_invent_legacy_names(client):
    cat = activate(client)
    p = make_product(client)
    receipt(client, central(cat), p['id'], qty='2')
    t = cmd(client, 'ship', {'source_id': central(cat), 'destination_id': cat['kitchens'][0]['warehouse_id'],
                           'product_id': p['id'], 'qty': '2'}).json()
    cmd(client, 'receive-transfer', {'id': t['id'], 'lines': [{'id': t['lines'][0]['id'], 'qty': '1'}]})
    with main.SessionLocal() as db:
        db.query(m.TransferReceiver).delete()
        db.query(m.TransferDispatch).delete()
        db.get(m.Control, 1).schema_version = 4
        db.commit()
    inv.initialize(main.engine, main.SessionLocal)
    inv.initialize(main.engine, main.SessionLocal)
    old = client.get('/api/manufacturing/transfers').json()[0]
    assert old['sender_name'] is None and old['vehicle_number'] is None
    assert old['receipts'][0]['receiver_name'] is None
    assert old['status'] == 'partial' and float(old['lines'][0]['remaining']) == 1



def test_manufacturing_page_versions_script_and_disables_cache(client):
    import hashlib
    import re
    page = client.get('/manufacturing')
    assert page.status_code == 200 and page.headers['cache-control'] == 'no-store'
    url = re.search(r'src="(/static/manufacturing.js\?v=[0-9a-f]+)"', page.text).group(1)
    script = client.get(url)
    assert script.headers['cache-control'] == 'no-store'
    assert url.endswith(hashlib.sha256(script.content).hexdigest()[:16])
    assert "input('sender_name'" in script.text
    assert "input('vehicle_number'" in script.text
    assert 'Cetak DO' in script.text


def operation(client, ident):
    return next(o for o in client.get('/api/manufacturing/operations').json()['documents'] if o['id'] == ident)


def decide(client, action, o, **extra):
    return cmd(client, action, {'id': o['id'], 'revision': o['revision'], 'reason': 'Diperiksa', **extra})


def po_fixture(client):
    cat = activate(client)
    p = make_product(client)
    supplier = cmd(client, 'save-supplier', {'code': 'S1', 'name': 'Supplier 1', 'contact': 'Lampung'}).json()
    body = {'number': 'PO-001', 'document_date': inv.today().isoformat(), 'warehouse_id': central(cat),
            'supplier_id': supplier['id'], 'lines': [{'product_id': p['id'], 'qty': '10', 'unit_price': '12000'}]}
    r = cmd(client, 'save-po', body)
    assert r.status_code == 200, r.text
    return cat, p, body, r.json()


def po_receipt_body(o, p, qty='4', reference='SJ-001'):
    return {'id': o['id'], 'revision': o['revision'], 'reference': reference,
            'received_date': inv.today().isoformat(), 'receiver_name': 'Petugas Gudang',
            'lines': [{'product_id': p['id'], 'qty': qty, 'batch_number': reference,
                       'expiry_date': (inv.today()+timedelta(days=10)).isoformat()}]}


def test_po_draft_approval_partial_receipts_and_close(client):
    cat, p, body, o = po_fixture(client)
    assert o['status'] == 'draft' and Decimal(o['data']['total']) == 120000
    assert cmd(client, 'receive-po', po_receipt_body(o, p)).status_code == 409
    edited = cmd(client, 'save-po', {**body, 'id': o['id'], 'revision': o['revision']}).json()
    assert decide(client, 'submit-po', o).status_code == 409
    o = decide(client, 'submit-po', edited).json()
    assert o['status'] == 'pending'
    o = decide(client, 'approve-operation', o).json()
    assert o['status'] == 'approved'
    assert cmd(client, 'save-po', {**body, 'id': o['id'], 'revision': o['revision']}).status_code == 409
    token = key()
    received_body = po_receipt_body(o, p)
    r = cmd(client, 'receive-po', received_body, token)
    assert r.status_code == 200, r.text
    o = r.json()
    assert cmd(client, 'receive-po', received_body, token).json() == o
    assert o['status'] == 'partial' and o['data']['receipts'][0]['receiver_name'] == 'Petugas Gudang'
    assert cmd(client, 'receive-po', po_receipt_body(o, p)).status_code == 409
    assert cmd(client, 'receive-po', po_receipt_body(o, p, qty='7', reference='SJ-002')).status_code == 409
    rows = client.get('/api/manufacturing/stock').json()
    assert len(rows) == 1 and Decimal(rows[0]['qty']) == 4 and Decimal(rows[0]['unit_cost']) == 12000
    closed = decide(client, 'close-po', o).json()
    assert closed['status'] == 'closed' and Decimal(closed['data']['lines'][0]['received_qty']) == 4
    assert cmd(client, 'receive-po', po_receipt_body(closed, p, reference='SJ-003')).status_code == 409


def test_po_full_receipt_atomic_invalid_lines_and_rejection(client):
    cat, p, body, o = po_fixture(client)
    o = decide(client, 'submit-po', o).json()
    rejected = decide(client, 'reject-operation', o).json()
    assert rejected['status'] == 'rejected'
    assert decide(client, 'approve-operation', rejected).status_code == 409
    o = cmd(client, 'save-po', {**body, 'number': 'PO-002'}).json()
    o = decide(client, 'submit-po', o).json()
    o = decide(client, 'approve-operation', o).json()
    bad = po_receipt_body(o, p)
    bad['lines'] += [{'product_id': p['id'], 'qty': '1', 'batch_number': 'B2', 'expiry_date': 'invalid'}]
    assert cmd(client, 'receive-po', bad).status_code == 422
    assert client.get('/api/manufacturing/stock').json() == []
    assert operation(client, o['id'])['data']['receipts'] == []
    r = cmd(client, 'receive-po', po_receipt_body(o, p, qty='10')).json()
    assert r['status'] == 'received'
    assert decide(client, 'close-po', r).status_code == 409


def count_fixture(client):
    cat = activate(client)
    p = make_product(client)
    wh = central(cat)
    receipt(client, wh, p['id'], qty='10')
    rows = client.get('/api/manufacturing/stock').json()
    return cat, p, wh, rows[0]


def test_opname_preserves_concurrent_movements_and_posts_difference_once(client):
    cat, p, wh, row = count_fixture(client)
    o = cmd(client, 'start-opname', {'number': 'OP-001', 'warehouse_id': wh, 'document_date': inv.today().isoformat()}).json()
    assert o['status'] == 'draft'
    assert cmd(client, 'start-opname', {'number': 'OP-002', 'warehouse_id': wh, 'document_date': inv.today().isoformat()}).status_code == 409
    assert cmd(client, 'usage', {'warehouse_id': wh, 'product_id': p['id'], 'qty': '1', 'reference': 'DURING-COUNT'}).status_code == 200
    assert cmd(client, 'ship', {'source_id': wh, 'destination_id': cat['kitchens'][0]['warehouse_id'], 'product_id': p['id'], 'qty': '1'}).status_code == 200
    assert cmd(client, 'receipt', {'warehouse_id': wh, 'product_id': p['id']}).status_code == 422
    b = {'id': o['id'], 'revision': o['revision'], 'counted_by': 'Penghitung', 'reason': 'Hitung fisik',
         'lines': [{'balance_id': row['balance_id'], 'counted_qty': '8'}],
         'new_lots': [{'product_id': p['id'], 'counted_qty': '2', 'batch_number': 'TEMUAN', 'unit_cost': '9000',
                       'expiry_date': (inv.today()-timedelta(days=1)).isoformat()}]}
    o = cmd(client, 'submit-opname', b).json()
    assert o['status'] == 'pending'
    assert Decimal(client.get('/api/manufacturing/stock').json()[0]['qty']) == 8
    token = key()
    decision = {'id': o['id'], 'revision': o['revision'], 'reason': 'Sesuai fisik'}
    result = cmd(client, 'approve-operation', decision, token)
    assert result.status_code == 200, result.text
    assert cmd(client, 'approve-operation', decision, token).json() == result.json()
    rows = client.get('/api/manufacturing/stock').json()
    assert sum(Decimal(r['qty']) for r in rows) == 8
    assert next(r for r in rows if r['batch_number'] == 'TEMUAN')['usable'] is False
    assert len([m for m in client.get('/api/manufacturing/movements').json() if m['kind'] == 'OPNAME']) == 2
    assert cmd(client, 'usage', {'warehouse_id': wh, 'product_id': p['id'], 'qty': '1', 'reference': 'AFTER'}).status_code == 200
    assert decide(client, 'approve-operation', result.json()).status_code == 409


def test_scrap_holds_stock_and_only_approval_deducts(client):
    cat, p, wh, row = count_fixture(client)
    body = {'number': 'SC-001', 'warehouse_id': wh, 'document_date': inv.today().isoformat(), 'reason': 'Rusak',
            'lines': [{'balance_id': row['balance_id'], 'qty': '3'}]}
    o = cmd(client, 'request-scrap', body).json()
    assert o['status'] == 'pending'
    s = client.get('/api/manufacturing/stock').json()[0]
    assert Decimal(s['qty']) == 10 and Decimal(s['available_qty']) == 7
    assert cmd(client, 'usage', {'warehouse_id': wh, 'product_id': p['id'], 'qty': '8', 'reference': 'HOLD'}).status_code == 409
    assert cmd(client, 'start-opname', {'number': 'OP-1', 'warehouse_id': wh, 'document_date': inv.today().isoformat()}).status_code == 409
    assert cmd(client, 'request-scrap', {**body, 'number': 'SC-002', 'lines': [{'balance_id': row['balance_id'], 'qty': '8'}]}).status_code == 409
    assert cmd(client, 'usage', {'warehouse_id': wh, 'product_id': p['id'], 'qty': '7', 'reference': 'UNRESERVED'}).status_code == 200
    result = decide(client, 'approve-operation', o)
    assert result.status_code == 200, result.text
    assert client.get('/api/manufacturing/stock').json() == []
    assert len([m for m in client.get('/api/manufacturing/movements').json() if m['kind'] == 'SCRAP']) == 1
    assert decide(client, 'approve-operation', result.json()).status_code == 409


def test_scrap_rejection_and_opname_cancel_unlock(client):
    cat, p, wh, row = count_fixture(client)
    o = cmd(client, 'request-scrap', {'number': 'SC-X', 'warehouse_id': wh, 'document_date': inv.today().isoformat(), 'reason': 'Rusak', 'lines': [{'balance_id': row['balance_id'], 'qty': '2'}]}).json()
    assert decide(client, 'reject-operation', o).json()['status'] == 'rejected'
    assert Decimal(client.get('/api/manufacturing/stock').json()[0]['available_qty']) == 10
    o = cmd(client, 'start-opname', {'number': 'OP-X', 'warehouse_id': wh, 'document_date': inv.today().isoformat()}).json()
    assert decide(client, 'cancel-operation', o).json()['status'] == 'cancelled'
    assert cmd(client, 'usage', {'warehouse_id': wh, 'product_id': p['id'], 'qty': '1', 'reference': 'UNLOCK'}).status_code == 200


def test_operations_roles_scope_and_master_protection(client):
    cat, p, body, o = po_fixture(client)
    product = client.get('/api/manufacturing/catalog').json()['products'][0]
    assert cmd(client, 'save-product', {**product, 'base_uom': 'pcs'}).status_code == 422
    wh = next(w for w in cat['warehouses'] if w['id'] == central(cat))
    assert cmd(client, 'save-warehouse', {**wh, 'active': False}).status_code == 409
    with main.SessionLocal() as db:
        u = db.query(main.User).filter_by(username='admin').one()
        u.role = 'purchasing'
        uid = u.id
        db.commit()
    assert client.get('/api/manufacturing/operations').json()['documents'] == []
    assert decide(client, 'submit-po', o).status_code == 403
    with main.SessionLocal() as db:
        db.add(m.Access(user_id=uid, warehouse_id=central(cat)))
        db.commit()
    o = decide(client, 'submit-po', o).json()
    assert o['status'] == 'pending'
    assert decide(client, 'approve-operation', o).status_code == 403
    assert cmd(client, 'request-scrap', {}).status_code == 403
    with main.SessionLocal() as db:
        db.get(main.User, uid).role = 'approver'
        db.commit()
    assert decide(client, 'approve-operation', o).json()['status'] == 'approved'
    assert cmd(client, 'save-po', body).status_code == 403
    assert cmd(client, 'save-supplier', {'code': 'S2', 'name': 'Forbidden'}).status_code == 403


def test_concurrent_scrap_decisions_do_not_double_post(client):
    cat, p, wh, row = count_fixture(client)
    o = cmd(client, 'request-scrap', {'number': 'SC-CONCURRENT', 'warehouse_id': wh, 'document_date': inv.today().isoformat(), 'reason': 'Rusak', 'lines': [{'balance_id': row['balance_id'], 'qty': '2'}]}).json()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: decide(client, 'approve-operation', o).status_code, range(2)))
    assert sorted(results) == [200, 409]
    assert Decimal(client.get('/api/manufacturing/stock').json()[0]['qty']) == 8


def test_po_purchase_units_convert_price_and_receive_using_snapshot(client):
    cat = activate(client)
    p = make_product(client, uoms={'sak': '25'})
    supplier = cmd(client, 'save-supplier', {'code': 'UOM-S', 'name': 'Supplier'}).json()
    body = {'number': 'PO-UOM', 'document_date': inv.today().isoformat(), 'warehouse_id': central(cat),
            'supplier_id': supplier['id'], 'lines': [{'product_id': p['id'], 'purchase_uom': 'sak', 'qty': '2', 'unit_price': '300000', 'conversion_factor': '999'}]}
    o = cmd(client, 'save-po', body).json()
    line = o['data']['lines'][0]
    assert line['purchase_uom'] == 'sak' and Decimal(line['conversion_factor']) == 25
    assert Decimal(line['qty']) == 50 and Decimal(line['unit_price']) == 12000
    assert Decimal(o['data']['total']) == 600000
    assert Decimal(line['purchase_qty']) == 2 and Decimal(line['purchase_price']) == 300000
    # Even a master change outside the application must not reinterpret an approved PO.
    with main.SessionLocal() as db:
        db.get(m.Product, p['id']).uoms = json.dumps({'sak': '30'})
        db.commit()
    o = decide(client, 'submit-po', o).json()
    o = decide(client, 'approve-operation', o).json()
    receipt_body = po_receipt_body(o, p, qty='1')
    receipt_body['lines'][0]['uom'] = 'sak'
    received = cmd(client, 'receive-po', receipt_body)
    assert received.status_code == 200, received.text
    o = received.json()
    assert o['status'] == 'partial'
    assert Decimal(o['data']['lines'][0]['received_qty']) == 25
    row = client.get('/api/manufacturing/stock').json()[0]
    assert Decimal(row['qty']) == 25 and Decimal(row['unit_cost']) == 12000
    receipt_body = po_receipt_body(o, p, qty='2', reference='UOM-OVER')
    receipt_body['lines'][0]['uom'] = 'sak'
    assert cmd(client, 'receive-po', receipt_body).status_code == 409
    receipt_body['lines'][0]['uom'] = 'dus'
    assert cmd(client, 'receive-po', receipt_body).status_code == 422
    receipt_body = po_receipt_body(o, p, qty='25', reference='UOM-BASE')
    receipt_body['lines'][0]['uom'] = 'kg'
    o = cmd(client, 'receive-po', receipt_body).json()
    assert o['status'] == 'received'
    assert [r['lines'][0]['receipt_uom'] for r in o['data']['receipts']] == ['sak', 'kg']
    assert sum(Decimal(r['qty']) for r in client.get('/api/manufacturing/stock').json()) == 50


def test_po_units_validation_discrete_and_base_price_rounding(client):
    cat = activate(client)
    p = make_product(client, base_uom='pcs', discrete=True, uoms={'dus': '3'})
    supplier = cmd(client, 'save-supplier', {'code': 'ROUND-S', 'name': 'Supplier'}).json()
    body = {'number': 'PO-ROUND', 'document_date': inv.today().isoformat(), 'warehouse_id': central(cat),
            'supplier_id': supplier['id'], 'lines': [{'product_id': p['id'], 'purchase_uom': 'dus', 'qty': '1', 'unit_price': '100'}]}
    for unit, qty in [('unknown', '1'), ('dus', '0.5')]:
        assert cmd(client, 'save-po', {**body, 'lines': [{**body['lines'][0], 'purchase_uom': unit, 'qty': qty}]}).status_code == 422
    result = cmd(client, 'save-po', body)
    assert result.status_code == 200, result.text
    line = result.json()['data']['lines'][0]
    assert line['unit_price'] == '33.33333333'
    assert Decimal(result.json()['data']['total']) == 100


def test_purchase_receipt_units_and_transfer_snapshot_conversion(client):
    cat = activate(client)
    p = make_product(client, uoms={'sak': '25'})
    wh, dest = central(cat), cat['kitchens'][0]['warehouse_id']
    body = {'warehouse_id': wh, 'product_id': p['id'], 'qty': '2', 'uom': 'sak', 'unit_cost': '300000',
            'batch_number': 'UNIT-LOT', 'expiry_date': (inv.today()+timedelta(days=60)).isoformat(), 'reference': 'UNIT-IN'}
    token = key()
    r = cmd(client, 'receipt', body, token)
    assert r.status_code == 200, r.text
    assert cmd(client, 'receipt', body, token).json() == r.json()
    assert Decimal(r.json()['qty']) == 50 and Decimal(r.json()['unit_cost']) == 12000
    with main.SessionLocal() as db:
        snap = json.loads(db.get(m.ReceiptUnits, r.json()['lot_id']).document)
        assert snap['uom'] == 'sak' and Decimal(snap['factor']) == 25
    assert cmd(client, 'receipt', {**body, 'uom': 'unknown'}).status_code == 422
    ship_body = {'source_id': wh, 'destination_id': dest, 'document_number': 'UNIT-DO',
                 'lines': [{'product_id': p['id'], 'qty': '1', 'uom': 'sak'}]}
    shipped = cmd(client, 'ship', ship_body)
    assert shipped.status_code == 200, shipped.text
    t = shipped.json()
    assert Decimal(t['lines'][0]['shipped_qty']) == 25 and t['lines'][0]['shipping_uom'] == 'sak'
    assert Decimal(t['shipment_units'][str(p['id'])]['factor']) == 25
    with main.SessionLocal() as db:
        db.get(m.Product, p['id']).uoms = json.dumps({'sak': '30'})
        db.commit()
    receive = {'id': t['id'], 'lines': [{'id': t['lines'][0]['id'], 'qty': '0.4', 'uom': 'sak'}]}
    r = cmd(client, 'receive-transfer', receive)
    assert r.status_code == 200, r.text
    t = r.json()
    assert Decimal(t['lines'][0]['received_qty']) == 10
    assert t['receipts'][0]['lines'][0]['input_uom'] == 'sak'
    assert cmd(client, 'receive-transfer', {'id': t['id'], 'lines': [{'id': t['lines'][0]['id'], 'qty': '1', 'uom': 'sak'}]}).status_code == 422
    final = cmd(client, 'receive-transfer', {'id': t['id'], 'lines': [{'id': t['lines'][0]['id'], 'qty': '15', 'uom': 'kg'}]}).json()
    assert final['status'] == 'received'
    assert sum(Decimal(s['qty']) for s in client.get('/api/manufacturing/stock').json()) == 50
    assert all(Decimal(s['unit_cost']) == 12000 for s in client.get('/api/manufacturing/stock').json())


def test_transfer_units_validation_and_legacy_fallback(client):
    cat = activate(client)
    p = make_product(client, base_uom='pcs', discrete=True, uoms={'dus': '3'})
    receipt(client, central(cat), p['id'], qty='9')
    body = {'source_id': central(cat), 'destination_id': cat['kitchens'][0]['warehouse_id'],
            'product_id': p['id'], 'qty': '0.5', 'uom': 'dus'}
    assert cmd(client, 'ship', body).status_code == 422
    assert cmd(client, 'ship', {**body, 'uom': 'bad'}).status_code == 422
    t = cmd(client, 'ship', {**body, 'qty': '1'}).json()
    assert Decimal(t['lines'][0]['shipped_qty']) == 3
    with main.SessionLocal() as db:
        db.query(m.TransferUnits).delete()
        db.commit()
    old = client.get('/api/manufacturing/transfers').json()[0]
    assert old['lines'][0]['units'] == {'pcs': '1'}
    assert cmd(client, 'receive-transfer', {'id': old['id'], 'lines': [{'id': old['lines'][0]['id'], 'qty': '1', 'uom': 'dus'}]}).status_code == 422
    assert cmd(client, 'receive-transfer', {'id': old['id'], 'lines': [{'id': old['lines'][0]['id'], 'qty': '3'}]}).json()['status'] == 'received'
