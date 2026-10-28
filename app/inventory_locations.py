"""Warehouse capabilities and migration from the obsolete kitchen pairing."""
from sqlalchemy.orm import object_session
from inventory_models import Warehouse, Kitchen, Product, ProductionLocation, Profile
import inventory as c
from inventory_restore import profile, put_profile


def capabilities(w):
    db=object_session(w)
    data=profile(db,f'warehouse-capabilities:{w.id}') if db and w.id else {}
    return {'can_produce':data.get('can_produce',w.kind=='kitchen'),
            'can_pack':data.get('can_pack',w.kind=='packing')}


def production_warehouse(p):
    db=object_session(p)
    if not db or not p.id:return None
    link=db.get(ProductionLocation,p.id)
    if link:return link.warehouse_id
    legacy=db.get(Kitchen,p.kitchen_id) if p.kitchen_id else None
    return legacy.warehouse_id if legacy else None


def migrate(db):
    for p in db.query(Product).filter(Product.kitchen_id.isnot(None)):
        if not db.get(ProductionLocation,p.id):
            k=db.get(Kitchen,p.kitchen_id)
            if k:db.add(ProductionLocation(product_id=p.id,warehouse_id=k.warehouse_id))
    # Rename only untouched seed labels; IDs, balances and document references stay intact.
    for i in range(1,11):
        w=db.query(Warehouse).filter_by(code=f'G-D{i:02}',name=f'Gudang Dapur {i}').first()
        if w and not db.query(Warehouse).filter_by(code=f'D{i:02}').first():
            w.code=f'D{i:02}';w.name=f'Dapur {i}'
    db.flush()


def validate_assignment(db,p,body,kind):
    if 'production_warehouse_id' in body and body.get('kitchen_id') is not None:
        legacy=c.get(db,Kitchen,body['kitchen_id'])
        canonical=body['production_warehouse_id']
        if canonical != legacy.warehouse_id:
            if body.get('kitchen_id') != p.kitchen_id and canonical == production_warehouse(p):
                body={**body};body.pop('production_warehouse_id')
            elif canonical == production_warehouse(p):
                c.fail('Penetapan gudang dan dapur lama tidak konsisten.')
    if 'production_warehouse_id' in body:
        wid=body['production_warehouse_id']
        wid=None if wid in (None,'') else c.get(db,Warehouse,wid).id
        kid=None
    elif 'kitchen_id' in body:
        kid=body['kitchen_id']
        k=c.get(db,Kitchen,kid) if kid is not None else None
        wid=k.warehouse_id if k else None
    else:
        wid=production_warehouse(p);kid=p.kitchen_id
    if c.product_category(kind)=='finished':
        if wid is None:c.fail('Produk jadi wajib memiliki gudang produksi.')
        w=c.get(db,Warehouse,wid);caps=capabilities(w)
        if not w.active:c.fail('Gudang produksi tidak aktif.')
        if not caps['can_pack' if kind=='package' else 'can_produce']:
            c.fail('Gudang tidak memiliki kemampuan packing/produksi yang diperlukan.')
    elif wid is not None:c.fail('Penetapan gudang produksi hanya untuk produk jadi, bukan WIP/bahan baku.')
    if p.id and production_warehouse(p)!=wid and not body.get('change_reason'):
        c.fail('Perubahan gudang produksi wajib disertai alasan.')
    return wid,kid


def assign(db,p,wid):
    row=db.get(ProductionLocation,p.id)
    if wid is None:
        if row:db.delete(row)
    elif row:row.warehouse_id=wid
    else:db.add(ProductionLocation(product_id=p.id,warehouse_id=wid))
    db.flush()


def save_capabilities(db,w,body):
    old=capabilities(w)
    data={k:c.flag(body.get(k,old[k]),k) for k in ('can_produce','can_pack')}
    for p in db.query(Product).join(ProductionLocation,ProductionLocation.product_id==Product.id).filter(ProductionLocation.warehouse_id==w.id,Product.active.is_(True)):
        if not w.active or not data['can_pack' if p.kind=='package' else 'can_produce']:
            c.fail('Pindahkan produk aktif sebelum menonaktifkan gudang atau kemampuan produksinya.',409)
    put_profile(db,f'warehouse-capabilities:{w.id}',data)
