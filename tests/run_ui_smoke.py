"""Launch a disposable SQLite instance and exercise its UI with Playwright.

Requires the Node playwright package and a local Chromium installation. This
script never connects to a production database or uses an external account.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import timedelta

import uvicorn

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="inventory-ui-") as directory:
    folder = Path(directory)
    os.environ["DATABASE_URL"] = "sqlite:///" + str(folder / "inventory.db")
    os.environ["SEED_DEMO_USERS"] = "false"
    os.environ["ADMIN_PASSWORD"] = secrets.token_urlsafe(25)
    os.environ["AUDIT_LOG_PATH"] = str(folder / "audit.jsonl")
    sys.path.insert(0, str(root / "app"))
    import main
    import inventory

    main.init_db()
    inventory.initialize(main.engine, main.SessionLocal)
    with main.SessionLocal() as db:
        user = db.query(main.User).filter_by(username="admin").one()
        user.must_change_password = False
        token = secrets.token_urlsafe(32)
        db.add(main.UserSession(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                               expires_at=main.utcnow() + timedelta(hours=1)))
        db.commit()
    session_file = folder / "session.json"
    session_file.write_text(json.dumps({"token": token}))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(main.app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("Test server failed to start")
            time.sleep(0.05)
        environment = {**os.environ, "INVENTORY_SMOKE_URL": f"http://127.0.0.1:{port}",
                       "INVENTORY_SMOKE_SESSION_FILE": str(session_file)}
        subprocess.run(["node", str(root / "tests" / "ui_smoke.cjs")], env=environment, check=True, timeout=120)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
