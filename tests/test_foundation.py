"""API-level acceptance tests. No live accounts or production DB are used."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
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
    second = cmd(client, 'save-warehouse', {'code': 'C2', 'name': 'Central 2', 'kind': 'central'}).json()
    p = make_product(client)
    receipt(client, second['id'], p['id'], qty='2')
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
