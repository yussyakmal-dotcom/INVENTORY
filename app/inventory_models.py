"""Additive phase-one schema. Existing JSON is retained as a cutover archive."""
from datetime import datetime, timezone

from sqlalchemy import (Boolean, CheckConstraint, Column, Date, DateTime, ForeignKey,
                        Integer, Numeric, String, Text, UniqueConstraint)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import declarative_base

Base = declarative_base()
BigText = Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb")
Qty = Numeric(20, 6)
Money = Numeric(24, 8)


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Control(Base):
    __tablename__ = "inv_control"
    id = Column(Integer, primary_key=True)
    schema_version = Column(Integer, nullable=False, default=1)
    revision = Column(Integer, nullable=False, default=0)
    active = Column(Boolean, nullable=False, default=False)
    legacy_version = Column(Integer)
    archive = Column(BigText)
    activated_at = Column(DateTime)


class Warehouse(Base):
    __tablename__ = "inv_warehouses"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    kind = Column(String(20), nullable=False)
    legacy_id = Column(Integer, unique=True)
    active = Column(Boolean, nullable=False, default=True)


class Kitchen(Base):
    __tablename__ = "inv_kitchens"
    id = Column(Integer, primary_key=True)
    code = Column(String(10), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("inv_warehouses.id"), nullable=False, unique=True)
    kind = Column(String(20), nullable=False)


class Access(Base):
    __tablename__ = "inv_warehouse_access"
    user_id = Column(Integer, primary_key=True)
    warehouse_id = Column(Integer, ForeignKey("inv_warehouses.id"), primary_key=True)


class Product(Base):
    __tablename__ = "inv_products"
    id = Column(Integer, primary_key=True)
    code = Column(String(50), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    kind = Column(String(20), nullable=False, default="raw")
    base_uom = Column(String(20), nullable=False)
    uoms = Column(Text, nullable=False, default="{}")
    discrete = Column(Boolean, nullable=False, default=False)
    shelf_life_days = Column(Integer)
    kitchen_id = Column(Integer, ForeignKey("inv_kitchens.id"))
    selling_price = Column(Money, nullable=False, default=0)
    legacy_id = Column(Integer, unique=True)
    active = Column(Boolean, nullable=False, default=True)
    revision = Column(Integer, nullable=False, default=1)
    __table_args__ = (CheckConstraint("shelf_life_days IS NULL OR shelf_life_days >= 0"),)


class Bom(Base):
    __tablename__ = "inv_boms"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("inv_products.id"), nullable=False)
    version = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False, default="draft")
    output_qty = Column(Qty, nullable=False)
    document = Column(BigText, nullable=False)
    revision = Column(Integer, nullable=False, default=1)
    created_by = Column(Integer, nullable=False)
    approved_by = Column(Integer)
    approved_at = Column(DateTime)
    __table_args__ = (UniqueConstraint("product_id", "version"), CheckConstraint("output_qty > 0"))


class Lot(Base):
    __tablename__ = "inv_lots"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("inv_products.id"), nullable=False, index=True)
    batch_number = Column(String(100), nullable=False)
    expiry_date = Column(Date, index=True)
    unit_cost = Column(Money, nullable=False)
    received_at = Column(DateTime, nullable=False, default=now)
    blocked = Column(Boolean, nullable=False, default=False)
    legacy_id = Column(Integer, unique=True)
    __table_args__ = (CheckConstraint("unit_cost >= 0"),)


class Balance(Base):
    __tablename__ = "inv_balances"
    id = Column(Integer, primary_key=True)
    lot_id = Column(Integer, ForeignKey("inv_lots.id"), nullable=False)
    warehouse_id = Column(Integer, ForeignKey("inv_warehouses.id"), nullable=False)
    qty = Column(Qty, nullable=False, default=0)
    __table_args__ = (UniqueConstraint("lot_id", "warehouse_id"), CheckConstraint("qty >= 0"))


class Transfer(Base):
    __tablename__ = "inv_transfers"
    id = Column(Integer, primary_key=True)
    source_id = Column(Integer, ForeignKey("inv_warehouses.id"), nullable=False)
    destination_id = Column(Integer, ForeignKey("inv_warehouses.id"), nullable=False)
    reference = Column(String(150), nullable=False)
    status = Column(String(20), nullable=False, default="shipped")
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=now)


class TransferLine(Base):
    __tablename__ = "inv_transfer_lines"
    id = Column(Integer, primary_key=True)
    transfer_id = Column(Integer, ForeignKey("inv_transfers.id"), nullable=False)
    lot_id = Column(Integer, ForeignKey("inv_lots.id"), nullable=False)
    shipped_qty = Column(Qty, nullable=False)
    received_qty = Column(Qty, nullable=False, default=0)
    __table_args__ = (CheckConstraint("shipped_qty > 0"),
                      CheckConstraint("received_qty >= 0 AND received_qty <= shipped_qty"))


class TransferDocument(Base):
    __tablename__ = "inv_transfer_documents"
    transfer_id = Column(Integer, ForeignKey("inv_transfers.id"), primary_key=True)
    document_number = Column(String(150), nullable=False, unique=True)
    shipped_date = Column(Date, nullable=False)
    legacy = Column(Boolean, nullable=False, default=False)


class TransferReceipt(Base):
    __tablename__ = "inv_transfer_receipts"
    id = Column(Integer, primary_key=True)
    transfer_id = Column(Integer, ForeignKey("inv_transfers.id"), nullable=False, index=True)
    received_date = Column(Date, nullable=False)
    actor_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=now)


class TransferReceiptLine(Base):
    __tablename__ = "inv_transfer_receipt_lines"
    id = Column(Integer, primary_key=True)
    receipt_id = Column(Integer, ForeignKey("inv_transfer_receipts.id"), nullable=False)
    transfer_line_id = Column(Integer, ForeignKey("inv_transfer_lines.id"), nullable=False)
    qty = Column(Qty, nullable=False)
    __table_args__ = (UniqueConstraint("receipt_id", "transfer_line_id"), CheckConstraint("qty > 0"))


class Movement(Base):
    __tablename__ = "inv_movements"
    id = Column(Integer, primary_key=True)
    balance_id = Column(Integer, ForeignKey("inv_balances.id"), nullable=False, index=True)
    kind = Column(String(30), nullable=False)
    qty_delta = Column(Qty, nullable=False)
    unit_cost = Column(Money, nullable=False)
    reference = Column(String(150), nullable=False)
    actor_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=now)


class Audit(Base):
    __tablename__ = "inv_audit"
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, nullable=False)
    operation = Column(String(80), nullable=False)
    document = Column(BigText, nullable=False)
    created_at = Column(DateTime, nullable=False, default=now)


class Command(Base):
    __tablename__ = "inv_commands"
    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, nullable=False)
    operation = Column(String(80), nullable=False)
    request_key = Column(String(100), nullable=False)
    payload_hash = Column(String(64), nullable=False)
    response = Column(BigText, nullable=False)
    __table_args__ = (UniqueConstraint("actor_id", "operation", "request_key"),)

