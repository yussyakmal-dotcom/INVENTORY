"""
Sistem Manajemen Inventori Multi-Gudang (MVP)
FastAPI + SQLAlchemy + MariaDB

- Login dengan session cookie (HttpOnly), password di-hash PBKDF2-SHA256.
- Data operasional disimpan sebagai satu dokumen JSON ber-versi (optimistic locking).
- Audit log ditulis ke file JSON Lines (AUDIT_LOG_PATH), sesuai PRD.
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, create_engine, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, declarative_base, sessionmaker

import inventory

# ------------------------------------------------------------------ konfigurasi
def env(name, default=None):
    v = os.getenv(name)
    return v if v not in (None, "") else default

def env_bool(name, default=False):
    return str(env(name, str(default))).strip().lower() in ("1", "true", "yes", "ya", "on")

DATABASE_URL = env("DATABASE_URL") or "mysql+pymysql://{u}:{p}@{h}:{port}/{d}?charset=utf8mb4".format(
    u=quote_plus(env("DB_USER", "inventory")), p=quote_plus(env("DB_PASSWORD", "")),
    h=env("DB_HOST", "mariadb"), port=env("DB_PORT", "3306"), d=env("DB_NAME", "inventory_db"))
ADMIN_USERNAME = env("ADMIN_USERNAME", "admin").lower()
ADMIN_PASSWORD = env("ADMIN_PASSWORD")
SEED_DEMO_USERS = env_bool("SEED_DEMO_USERS", True)
DEMO_PASSWORD = env("DEMO_PASSWORD") or secrets.token_urlsafe(24)
DEMO_DATA = env_bool("DEMO_DATA", True)
COOKIE_SECURE = env_bool("COOKIE_SECURE", False)
SESSION_HOURS = int(env("SESSION_HOURS", "12"))
AUDIT_LOG_PATH = env("AUDIT_LOG_PATH", "/var/log/inventory/audit_log.jsonl")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
COOKIE = "inv_session"
ROLES = {"admin", "gudang", "purchasing", "approver"}

# ------------------------------------------------------------------ database
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
BigText = Text().with_variant(LONGTEXT(), "mysql").with_variant(LONGTEXT(), "mariadb")

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(30), unique=True, index=True, nullable=False)
    name = Column(String(80), nullable=False)
    role = Column(String(20), nullable=False)
    warehouse_id = Column(Integer, nullable=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)          # soft delete
    must_change_password = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

class UserSession(Base):
    __tablename__ = "user_sessions"
    token_hash = Column(String(64), primary_key=True)
    user_id = Column(Integer, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=utcnow)

class AppState(Base):
    __tablename__ = "app_state"
    id = Column(Integer, primary_key=True)
    version = Column(Integer, nullable=False, default=0)
    data = Column(BigText, nullable=False)
    updated_at = Column(DateTime, default=utcnow)
    updated_by = Column(String(30))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ------------------------------------------------------------------ keamanan
def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16); it = 310_000
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, it)
    return f"pbkdf2_sha256${it}${salt.hex()}${dk.hex()}"

def verify_pw(pw: str, stored: str) -> bool:
    try:
        _, it, salt, h = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(dk.hex(), h)
    except Exception:
        return False

def check_pw_policy(pw: str):
    if not isinstance(pw, str) or len(pw) < 8:
        raise HTTPException(400, "Password minimal 8 karakter.")
    if pw.lower() == pw or not any(c.isdigit() for c in pw):
        raise HTTPException(400, "Password harus memuat huruf besar dan angka.")

_fail_lock = threading.Lock()
_fails: dict = {}  # key -> (jumlah gagal, terkunci sampai)

def _rate_key(request: Request, username: str):
    return f"{request.client.host if request.client else '-'}|{username}"

# ------------------------------------------------------------------ audit log (JSON Lines)
_audit_lock = threading.Lock()

def write_audit(entries):
    if not entries:
        return
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
        with _audit_lock, open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:
        print(f"[audit] gagal menulis log: {exc}", flush=True)

def audit_event(user, action, endpoint, before=None, after=None):
    write_audit([{
        "timestamp": datetime.now(timezone.utc).isoformat(), "user_id": user, "action": action,
        "endpoint": endpoint, "payload_before": before, "payload_after": after, "source": "server"}])

# ------------------------------------------------------------------ helper
def user_dict(u: User):
    return {"id": u.id, "name": u.name, "username": u.username, "role": u.role, "warehouseId": u.warehouse_id,
            "isActive": bool(u.is_active), "mustChangePassword": bool(u.must_change_password)}

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    tok = request.cookies.get(COOKIE)
    if not tok:
        raise HTTPException(401, "Belum masuk.")
    s = db.get(UserSession, hashlib.sha256(tok.encode()).hexdigest())
    if not s or s.expires_at < utcnow():
        raise HTTPException(401, "Sesi berakhir. Silakan masuk lagi.")
    u = db.get(User, s.user_id)
    if not u or not u.is_active:
        raise HTTPException(401, "Akun tidak aktif.")
    return u

def admin_user(u: User = Depends(current_user)) -> User:
    if u.role != "admin":
        raise HTTPException(403, "Hanya Admin.")
    return u

def ready_user(u: User = Depends(current_user)) -> User:
    if u.must_change_password:
        raise HTTPException(403, "Ganti password terlebih dahulu.")
    return u

# ------------------------------------------------------------------ startup
def init_db():
    for i in range(60):
        try:
            Base.metadata.create_all(bind=engine)
            break
        except OperationalError as exc:
            print(f"[startup] menunggu database ({i + 1}/60): {exc.__class__.__name__}", flush=True)
            time.sleep(2)
    else:
        raise RuntimeError("Database tidak bisa dihubungi.")
    with SessionLocal() as db:
        if db.query(User).count() == 0:
            pw = ADMIN_PASSWORD or secrets.token_urlsafe(12)
            # urutan ini penting: id gudang di data demo (1 = Gudang Central, 2 = Cabang Utara)
            users = [(ADMIN_USERNAME, "Administrator", "admin", None, pw, True)]
            if SEED_DEMO_USERS:
                users += [("budi", "Budi Santoso", "gudang", 1, DEMO_PASSWORD, False),
                          ("sari", "Sari Lestari", "gudang", 2, DEMO_PASSWORD, False),
                          ("dimas", "Dimas Pratama", "purchasing", None, DEMO_PASSWORD, False),
                          ("wulan", "Wulan Anggraini", "approver", None, DEMO_PASSWORD, False)]
            for un, name, role, wh, p, must in users:
                db.add(User(username=un, name=name, role=role, warehouse_id=wh, password_hash=hash_pw(p), must_change_password=must))
            db.commit()
            print("=" * 60, flush=True)
            print(f"[startup] Akun admin dibuat: username '{ADMIN_USERNAME}'", flush=True)
            if not ADMIN_PASSWORD:
                print(f"[startup] ADMIN_PASSWORD kosong, password acak: {pw}", flush=True)
            print("[startup] Wajib ganti password saat login pertama.", flush=True)
            print("=" * 60, flush=True)
            audit_event("system", "SEED_USERS", "/startup", None, {"users": [u[0] for u in users]})

app = FastAPI(title="Inventory Management API", version="1.0-MVP", docs_url="/api/docs", openapi_url="/api/openapi.json")

@app.on_event("startup")
def _startup():
    init_db()
    inventory.initialize(engine, SessionLocal)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp

# ------------------------------------------------------------------ auth
@app.post("/api/auth/login")
async def login(request: Request, response: Response, db: Session = Depends(get_db)):
    body = await request.json()
    username = str(body.get("username", "")).strip().lower()
    password = str(body.get("password", ""))
    key = _rate_key(request, username)
    with _fail_lock:
        n, until = _fails.get(key, (0, 0))
        if until > time.time():
            raise HTTPException(429, f"Terlalu banyak percobaan. Coba lagi dalam {int(until - time.time()) // 60 + 1} menit.")
    u = db.query(User).filter(User.username == username).first()
    if not u or not u.is_active or not verify_pw(password, u.password_hash):
        with _fail_lock:
            n += 1
            _fails[key] = (n, time.time() + 300 if n >= 5 else 0)
        audit_event(username or "-", "LOGIN_FAILED", "/api/auth/login", None, {"ip": request.client.host if request.client else None})
        raise HTTPException(401, "Username atau password salah.")
    with _fail_lock:
        _fails.pop(key, None)
    tok = secrets.token_urlsafe(32)
    db.query(UserSession).filter(UserSession.expires_at < utcnow()).delete()
    db.add(UserSession(token_hash=hashlib.sha256(tok.encode()).hexdigest(), user_id=u.id, expires_at=utcnow() + timedelta(hours=SESSION_HOURS)))
    db.commit()
    response.set_cookie(COOKIE, tok, max_age=SESSION_HOURS * 3600, httponly=True, samesite="lax", secure=COOKIE_SECURE, path="/")
    audit_event(u.username, "LOGIN", "/api/auth/login", None, {"ip": request.client.host if request.client else None})
    return {"user": user_dict(u), "config": {"demoData": DEMO_DATA}}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    tok = request.cookies.get(COOKIE)
    if tok:
        db.query(UserSession).filter(UserSession.token_hash == hashlib.sha256(tok.encode()).hexdigest()).delete()
        db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}

@app.get("/api/auth/me")
def me(u: User = Depends(current_user)):
    return {"user": user_dict(u), "config": {"demoData": DEMO_DATA}}

@app.post("/api/auth/password")
async def change_password(request: Request, u: User = Depends(current_user), db: Session = Depends(get_db)):
    body = await request.json()
    if not verify_pw(str(body.get("old", "")), u.password_hash):
        raise HTTPException(400, "Password lama salah.")
    new = str(body.get("new", ""))
    check_pw_policy(new)
    if new == body.get("old"):
        raise HTTPException(400, "Password baru harus berbeda.")
    u.password_hash = hash_pw(new); u.must_change_password = False
    db.commit()
    audit_event(u.username, "CHANGE_PASSWORD", "/api/auth/password")
    return {"user": user_dict(u)}

# ------------------------------------------------------------------ users (admin)
def _validate_user_body(body, db, uid=None):
    name = str(body.get("name", "")).strip()
    role = body.get("role")
    if not name or len(name) > 80:
        raise HTTPException(400, "Nama wajib, maks. 80 karakter.")
    if role not in ROLES:
        raise HTTPException(400, "Peran tidak valid.")
    wh = body.get("warehouseId")
    wh = int(wh) if wh not in (None, "", 0, "0") else None
    return name, role, wh

@app.get("/api/users")
def list_users(_: User = Depends(ready_user), db: Session = Depends(get_db)):
    return [user_dict(u) for u in db.query(User).order_by(User.id).all()]

@app.post("/api/users")
async def create_user(request: Request, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    body = await request.json()
    name, role, wh = _validate_user_body(body, db)
    username = str(body.get("username", "")).strip().lower()
    import re
    if not re.fullmatch(r"[a-z0-9_.]{3,30}", username):
        raise HTTPException(400, "Username 3–30 karakter: huruf kecil, angka, titik, garis bawah.")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(400, "Username sudah dipakai.")
    pw = str(body.get("password", ""))
    check_pw_policy(pw)
    u = User(username=username, name=name, role=role, warehouse_id=wh, password_hash=hash_pw(pw), must_change_password=True)
    db.add(u); db.commit(); db.refresh(u)
    audit_event(admin.username, "CREATE_USER", "/api/users", None, user_dict(u))
    return user_dict(u)

@app.put("/api/users/{uid}")
async def update_user(uid: int, request: Request, admin: User = Depends(admin_user), db: Session = Depends(get_db)):
    body = await request.json()
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Pengguna tidak ditemukan.")
    before = user_dict(u)
    if "name" in body or "role" in body:
        name, role, wh = _validate_user_body({**before, **body}, db)
        if u.id == admin.id and role != "admin":
            raise HTTPException(400, "Anda tidak bisa menurunkan peran akun sendiri.")
        u.name, u.role, u.warehouse_id = name, role, wh
    if "isActive" in body:
        if u.id == admin.id and not body["isActive"]:
            raise HTTPException(400, "Anda tidak bisa menonaktifkan akun sendiri.")
        u.is_active = bool(body["isActive"])
        if not u.is_active:
            db.query(UserSession).filter(UserSession.user_id == u.id).delete()
    if body.get("password"):
        check_pw_policy(str(body["password"]))
        u.password_hash = hash_pw(str(body["password"])); u.must_change_password = True
        db.query(UserSession).filter(UserSession.user_id == u.id).delete()
    if u.role != "admin" or not u.is_active:
        if db.query(User).filter(User.role == "admin", User.is_active == True, User.id != u.id).count() == 0:  # noqa: E712
            raise HTTPException(400, "Harus ada minimal satu Admin aktif.")
    db.commit()
    audit_event(admin.username, "UPDATE_USER" + ("_PASSWORD_RESET" if body.get("password") else ""), f"/api/users/{uid}", before, user_dict(u))
    return user_dict(u)

# ------------------------------------------------------------------ state (optimistic locking)
@app.get("/api/state")
def get_state(u: User = Depends(ready_user), db: Session = Depends(get_db)):
    row = db.get(AppState, 1)
    users = [user_dict(x) for x in db.query(User).order_by(User.id).all()]
    return {"version": row.version if row else 0, "data": json.loads(row.data) if row else None,
            "users": users, "foundationActive": inventory.control(db).active}

@app.get("/api/state/version")
def get_version(u: User = Depends(ready_user), db: Session = Depends(get_db)):
    row = db.get(AppState, 1)
    return {"version": row.version if row else 0}

@app.put("/api/state")
async def put_state(request: Request, u: User = Depends(ready_user), db: Session = Depends(get_db)):
    body = await request.json()
    identity = inventory.legacy_write_guard(db, u)
    base = int(body.get("version", -1))
    data = body.get("data")
    if not isinstance(data, dict):
        raise HTTPException(400, "Data tidak valid.")
    data.pop("users", None); data.pop("currentUserId", None)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    now = utcnow()
    if base == 0:
        try:
            db.add(AppState(id=1, version=1, data=payload, updated_at=now, updated_by=identity.username)); db.commit()
            new_version = 1
        except IntegrityError:
            db.rollback()
            return JSONResponse({"detail": "Data sudah diubah pengguna lain."}, status_code=409)
    else:
        res = db.execute(text("UPDATE app_state SET data=:d, version=version+1, updated_at=:t, updated_by=:u WHERE id=1 AND version=:v"),
                         {"d": payload, "t": now, "u": identity.username, "v": base})
        if res.rowcount != 1:
            db.rollback()
            return JSONResponse({"detail": "Data sudah diubah pengguna lain."}, status_code=409)
        db.commit()
        new_version = base + 1
    entries = []
    for e in body.get("audit") or []:
        if not isinstance(e, dict):
            continue
        if e.get("role") != "system":   # identitas diambil dari sesi, bukan dari browser
            e["user_id"] = identity.username; e["role"] = identity.role
        e["state_version"] = new_version
        entries.append(e)
    write_audit(entries)
    return {"version": new_version}

@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}

# ------------------------------------------------------------------ frontend
@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), headers={"Cache-Control": "no-cache"})


inventory.install(app, SessionLocal, engine, ready_user, get_db, AppState, User, STATIC_DIR)

