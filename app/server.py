import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from random import SystemRandom
from urllib.parse import urlparse

BASE_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
WEB_DIR = os.path.join(BASE_DIR, "web")
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "app.db"))
ADMIN_KEY = os.getenv("ADMIN_KEY", "dev-admin-key")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "dev-webhook-token")
SPIN_SIGNING_KEY = os.getenv("SPIN_SIGNING_KEY", "dev-spin-signing-key")

RNG = SystemRandom()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def password_hash(password: str) -> str:
    salt = os.getenv("PASSWORD_SALT", "change-me")
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def sign_payload(payload: str) -> str:
    return hmac.new(SPIN_SIGNING_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def pick_weighted(rows):
    total = sum(max(0, r["weight"]) for r in rows)
    if total <= 0:
        raise ValueError("invalid weight table")
    target = RNG.uniform(0, total)
    acc = 0.0
    for r in rows:
        w = max(0, r["weight"])
        acc += w
        if target <= acc:
            return r
    return rows[-1]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wallets (
            user_id INTEGER PRIMARY KEY,
            balance_point INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            ref_type TEXT,
            ref_id TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS shop_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount_krw INTEGER NOT NULL,
            point_granted INTEGER NOT NULL,
            bonus_point INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            order_id TEXT UNIQUE NOT NULL,
            amount_krw INTEGER NOT NULL,
            point_granted INTEGER NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            paid_at TEXT
        );

        CREATE TABLE IF NOT EXISTS machines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            theme TEXT NOT NULL,
            cost_per_spin INTEGER NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            rules_text TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reward_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            rarity TEXT NOT NULL,
            item_type TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            stackable INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reward_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id INTEGER NOT NULL,
            reward_id INTEGER NOT NULL,
            weight INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS spins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            machine_id INTEGER NOT NULL,
            cost INTEGER NOT NULL,
            result_reward_id INTEGER NOT NULL,
            result_signature TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, idempotency_key)
        );

        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reward_id INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            obtained_at TEXT NOT NULL,
            source_spin_id INTEGER,
            UNIQUE(user_id, reward_id, source_spin_id)
        );
        """
    )

    if conn.execute("SELECT COUNT(*) FROM shop_packages").fetchone()[0] == 0:
        ts = now_iso()
        conn.executemany(
            "INSERT INTO shop_packages (name, amount_krw, point_granted, bonus_point, is_active, sort_order, created_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
            [
                ("Starter 5,000P", 5000, 5000, 500, 1, ts),
                ("Standard 10,000P", 10000, 10000, 1200, 2, ts),
                ("Jumbo 30,000P", 30000, 30000, 4500, 3, ts),
            ],
        )

    if conn.execute("SELECT COUNT(*) FROM machines").fetchone()[0] == 0:
        ts = now_iso()
        machine_id = conn.execute(
            "INSERT INTO machines (name, theme, cost_per_spin, is_active, rules_text, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
            ("Neon Jackpot", "cyber-city", 100, "Digital rewards only. No cash-out.", ts, ts),
        ).lastrowid

        conn.executemany(
            "INSERT INTO reward_catalog (name, rarity, item_type, metadata_json, stackable, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("Dust", "Common", "currency", json.dumps({"currency": "dust", "value": 25}), 1, ts),
                ("Spin Ticket", "Rare", "currency", json.dumps({"currency": "ticket", "value": 1}), 1, ts),
                ("Neon Frame", "Rare", "cosmetic", json.dumps({"slot": "frame"}), 0, ts),
                ("Arcade Background", "Epic", "cosmetic", json.dumps({"slot": "background"}), 0, ts),
                ("Dragon Aura", "Legendary", "cosmetic", json.dumps({"slot": "effect"}), 0, ts),
            ],
        )

        rewards = conn.execute("SELECT id, name FROM reward_catalog").fetchall()
        rid = {r["name"]: r["id"] for r in rewards}
        conn.executemany(
            "INSERT INTO reward_pool (machine_id, reward_id, weight) VALUES (?, ?, ?)",
            [
                (machine_id, rid["Dust"], 70),
                (machine_id, rid["Spin Ticket"], 12),
                (machine_id, rid["Neon Frame"], 10),
                (machine_id, rid["Arcade Background"], 6),
                (machine_id, rid["Dragon Aura"], 2),
            ],
        )

    conn.commit()
    conn.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "Kyungchinko/2.0"

    def parse_json(self):
        length = to_int(self.headers.get("Content-Length"), 0)
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.write_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return None

    def write_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_file(self, path):
        if not os.path.isfile(path):
            return self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
        with open(path, "rb") as f:
            body = f.read()
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def user_id(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self.write_json({"error": "Missing bearer token"}, HTTPStatus.UNAUTHORIZED)
            return None
        token = auth.split(" ", 1)[1].strip()
        conn = get_conn()
        row = conn.execute("SELECT u.id, u.status FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?", (token,)).fetchone()
        conn.close()
        if not row:
            self.write_json({"error": "Invalid token"}, HTTPStatus.UNAUTHORIZED)
            return None
        if row["status"] != "active":
            self.write_json({"error": "User is not active"}, HTTPStatus.FORBIDDEN)
            return None
        return row["id"]

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/":
            return self.write_file(os.path.join(WEB_DIR, "index.html"))
        if path.startswith("/static/"):
            rel = path.removeprefix("/static/")
            if ".." in rel:
                return self.write_json({"error": "Bad path"}, HTTPStatus.BAD_REQUEST)
            return self.write_file(os.path.join(WEB_DIR, "static", rel))

        if path == "/health":
            return self.write_json({"ok": True, "time": now_iso()})

        if path == "/api/shop/packages":
            conn = get_conn()
            rows = conn.execute("SELECT id,name,amount_krw,point_granted,bonus_point FROM shop_packages WHERE is_active=1 ORDER BY sort_order,id").fetchall()
            conn.close()
            return self.write_json({"items": [{"id": r["id"], "name": r["name"], "amountKRW": r["amount_krw"], "pointGranted": r["point_granted"], "bonusPoint": r["bonus_point"], "totalPoint": r["point_granted"] + r["bonus_point"]} for r in rows]})

        if path == "/api/machines":
            conn = get_conn()
            rows = conn.execute("SELECT id,name,theme,cost_per_spin,rules_text FROM machines WHERE is_active=1 ORDER BY id").fetchall()
            conn.close()
            return self.write_json({"items": [{"id": r["id"], "name": r["name"], "theme": r["theme"], "costPerSpin": r["cost_per_spin"], "rulesText": r["rules_text"]} for r in rows]})

        if path == "/api/wallet":
            uid = self.user_id()
            if not uid:
                return
            conn = get_conn()
            w = conn.execute("SELECT balance_point, updated_at FROM wallets WHERE user_id=?", (uid,)).fetchone()
            txs = conn.execute("SELECT id,type,amount,ref_type,ref_id,created_at FROM wallet_transactions WHERE user_id=? ORDER BY id DESC LIMIT 20", (uid,)).fetchall()
            conn.close()
            return self.write_json({"balancePoint": w["balance_point"], "updatedAt": w["updated_at"], "recentTransactions": [dict(x) for x in txs]})

        if path == "/api/inventory":
            uid = self.user_id()
            if not uid:
                return
            conn = get_conn()
            rows = conn.execute("SELECT i.id,i.qty,i.obtained_at,rc.id reward_id,rc.name,rc.rarity,rc.item_type,rc.metadata_json FROM inventory i JOIN reward_catalog rc ON rc.id=i.reward_id WHERE i.user_id=? ORDER BY i.obtained_at DESC", (uid,)).fetchall()
            conn.close()
            return self.write_json({"items": [{"inventoryId": r["id"], "rewardId": r["reward_id"], "name": r["name"], "rarity": r["rarity"], "type": r["item_type"], "qty": r["qty"], "metadata": json.loads(r["metadata_json"]), "obtainedAt": r["obtained_at"]} for r in rows]})

        return self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/auth/signup":
            body = self.parse_json()
            if body is None:
                return
            email = str(body.get("email", "")).strip().lower()
            pw = str(body.get("password", ""))
            if not email or len(pw) < 8:
                return self.write_json({"error": "email and password(>=8 chars) are required"}, HTTPStatus.BAD_REQUEST)
            conn = get_conn()
            try:
                ts = now_iso()
                uid = conn.execute("INSERT INTO users(email,password_hash,created_at) VALUES(?,?,?)", (email, password_hash(pw), ts)).lastrowid
                conn.execute("INSERT INTO wallets(user_id,balance_point,updated_at) VALUES(?,0,?)", (uid, ts))
                conn.commit()
            except sqlite3.IntegrityError:
                conn.close()
                return self.write_json({"error": "Email already exists"}, HTTPStatus.CONFLICT)
            conn.close()
            return self.write_json({"id": uid, "email": email}, HTTPStatus.CREATED)

        if path == "/api/auth/login":
            body = self.parse_json()
            if body is None:
                return
            email = str(body.get("email", "")).strip().lower()
            pw = str(body.get("password", ""))
            conn = get_conn()
            u = conn.execute("SELECT id,email,password_hash,status FROM users WHERE email=?", (email,)).fetchone()
            if not u or u["password_hash"] != password_hash(pw):
                conn.close()
                return self.write_json({"error": "Invalid credentials"}, HTTPStatus.UNAUTHORIZED)
            token = secrets.token_hex(24)
            conn.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,?)", (token, u["id"], now_iso()))
            conn.commit()
            conn.close()
            return self.write_json({"token": token, "user": {"id": u["id"], "email": u["email"], "status": u["status"]}})

        if path == "/api/auth/logout":
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                token = auth.split(" ", 1)[1].strip()
                conn = get_conn()
                conn.execute("DELETE FROM sessions WHERE token=?", (token,))
                conn.commit()
                conn.close()
            return self.write_json({"ok": True})

        if path == "/api/payments/create-order":
            uid = self.user_id()
            if not uid:
                return
            body = self.parse_json()
            if body is None:
                return
            package_id = to_int(body.get("packageId"))
            provider = str(body.get("provider", "mockpay")).strip().lower()
            if package_id is None:
                return self.write_json({"error": "packageId is required"}, HTTPStatus.BAD_REQUEST)
            conn = get_conn()
            pkg = conn.execute("SELECT id,amount_krw,point_granted,bonus_point FROM shop_packages WHERE id=? AND is_active=1", (package_id,)).fetchone()
            if not pkg:
                conn.close(); return self.write_json({"error": "Invalid package"}, HTTPStatus.BAD_REQUEST)
            points = pkg["point_granted"] + pkg["bonus_point"]
            order_id = f"ORD-{secrets.token_hex(8).upper()}"
            conn.execute("INSERT INTO payments(user_id,provider,order_id,amount_krw,point_granted,status,created_at) VALUES(?,?,?,?,?,'CREATED',?)", (uid, provider, order_id, pkg["amount_krw"], points, now_iso()))
            conn.commit(); conn.close()
            return self.write_json({"orderId": order_id, "provider": provider, "amountKRW": pkg["amount_krw"], "pointGranted": points, "status": "CREATED"}, HTTPStatus.CREATED)

        if path.startswith("/api/payments/webhook/"):
            if self.headers.get("X-Webhook-Token", "") != WEBHOOK_TOKEN:
                return self.write_json({"error": "Invalid webhook token"}, HTTPStatus.UNAUTHORIZED)
            provider = path.rsplit("/", 1)[-1]
            body = self.parse_json()
            if body is None:
                return
            order_id = str(body.get("orderId", "")).strip()
            status = str(body.get("status", "")).strip().upper()
            if not order_id or status not in {"PAID", "FAILED", "CANCELED"}:
                return self.write_json({"error": "orderId and valid status are required"}, HTTPStatus.BAD_REQUEST)
            conn = get_conn(); conn.isolation_level = None
            try:
                conn.execute("BEGIN IMMEDIATE")
                p = conn.execute("SELECT id,user_id,point_granted,status FROM payments WHERE order_id=? AND provider=?", (order_id, provider)).fetchone()
                if not p:
                    conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Payment not found"}, HTTPStatus.NOT_FOUND)
                if p["status"] in {"PAID", "FAILED", "CANCELED"}:
                    conn.execute("COMMIT"); conn.close(); return self.write_json({"ok": True, "idempotent": True, "status": p["status"]})
                ts = now_iso()
                conn.execute("UPDATE payments SET status=?, paid_at=? WHERE id=?", (status, ts if status == "PAID" else None, p["id"]))
                if status == "PAID":
                    conn.execute("UPDATE wallets SET balance_point=balance_point+?, updated_at=? WHERE user_id=?", (p["point_granted"], ts, p["user_id"]))
                    conn.execute("INSERT INTO wallet_transactions(user_id,type,amount,ref_type,ref_id,created_at) VALUES(?, 'CHARGE', ?, 'PAYMENT', ?, ?)", (p["user_id"], p["point_granted"], order_id, ts))
                conn.execute("COMMIT")
            except Exception as exc:
                conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Webhook failed", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            conn.close()
            return self.write_json({"ok": True, "status": status})

        if path.startswith("/api/machines/") and path.endswith("/spin"):
            uid = self.user_id()
            if not uid:
                return
            body = self.parse_json()
            if body is None:
                return
            idem = str(body.get("idempotencyKey", "")).strip()
            if not idem:
                return self.write_json({"error": "idempotencyKey is required"}, HTTPStatus.BAD_REQUEST)
            mid = to_int(path.split("/")[-2])
            if mid is None:
                return self.write_json({"error": "Invalid machine id"}, HTTPStatus.BAD_REQUEST)

            conn = get_conn(); conn.isolation_level = None
            try:
                conn.execute("BEGIN IMMEDIATE")
                old = conn.execute("SELECT s.id,s.cost,s.result_reward_id,s.result_signature,s.created_at,rc.name FROM spins s JOIN reward_catalog rc ON rc.id=s.result_reward_id WHERE s.user_id=? AND s.idempotency_key=?", (uid, idem)).fetchone()
                if old:
                    conn.execute("COMMIT"); conn.close(); return self.write_json({"idempotent": True, "spinId": old["id"], "cost": old["cost"], "reward": {"id": old["result_reward_id"], "name": old["name"]}, "signature": old["result_signature"], "createdAt": old["created_at"]})

                machine = conn.execute("SELECT id,cost_per_spin,is_active FROM machines WHERE id=?", (mid,)).fetchone()
                if not machine:
                    conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Machine not found"}, HTTPStatus.NOT_FOUND)
                if machine["is_active"] != 1:
                    conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Machine inactive"}, HTTPStatus.BAD_REQUEST)

                bal = conn.execute("SELECT balance_point FROM wallets WHERE user_id=?", (uid,)).fetchone()
                if bal["balance_point"] < machine["cost_per_spin"]:
                    conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Insufficient points"}, HTTPStatus.BAD_REQUEST)

                conn.execute("UPDATE wallets SET balance_point=balance_point-?, updated_at=? WHERE user_id=?", (machine["cost_per_spin"], now_iso(), uid))
                conn.execute("INSERT INTO wallet_transactions(user_id,type,amount,ref_type,ref_id,created_at) VALUES(?, 'SPEND', ?, 'SPIN', ?, ?)", (uid, -machine["cost_per_spin"], f"machine:{mid}", now_iso()))

                pool = conn.execute("SELECT rp.reward_id, rp.weight, rc.name, rc.rarity, rc.item_type, rc.metadata_json, rc.stackable FROM reward_pool rp JOIN reward_catalog rc ON rc.id = rp.reward_id WHERE rp.machine_id=?", (mid,)).fetchall()
                reward = pick_weighted([{"rewardId": r["reward_id"], "weight": r["weight"], "name": r["name"], "rarity": r["rarity"], "itemType": r["item_type"], "metadata": r["metadata_json"], "stackable": r["stackable"]} for r in pool])

                ts = now_iso()
                sig = sign_payload(f"{uid}|{mid}|{reward['rewardId']}|{ts}|{idem}")
                spin_id = conn.execute("INSERT INTO spins(user_id,machine_id,cost,result_reward_id,result_signature,idempotency_key,created_at) VALUES(?,?,?,?,?,?,?)", (uid, mid, machine["cost_per_spin"], reward["rewardId"], sig, idem, ts)).lastrowid

                if reward["stackable"] == 1:
                    row = conn.execute("SELECT id FROM inventory WHERE user_id=? AND reward_id=? AND source_spin_id IS NULL", (uid, reward["rewardId"])).fetchone()
                    if row:
                        conn.execute("UPDATE inventory SET qty=qty+1, obtained_at=? WHERE id=?", (ts, row["id"]))
                    else:
                        conn.execute("INSERT INTO inventory(user_id,reward_id,qty,obtained_at,source_spin_id) VALUES(?,?,1,?,NULL)", (uid, reward["rewardId"], ts))
                else:
                    conn.execute("INSERT INTO inventory(user_id,reward_id,qty,obtained_at,source_spin_id) VALUES(?,?,1,?,?)", (uid, reward["rewardId"], ts, spin_id))

                conn.execute("COMMIT")
            except Exception as exc:
                conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Spin failed", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

            balance_after = conn.execute("SELECT balance_point FROM wallets WHERE user_id=?", (uid,)).fetchone()["balance_point"]
            conn.close()
            return self.write_json({"spinId": spin_id, "cost": machine["cost_per_spin"], "reward": {"id": reward["rewardId"], "name": reward["name"], "rarity": reward["rarity"], "type": reward["itemType"], "metadata": json.loads(reward["metadata"])}, "signature": sig, "walletBalance": balance_after, "createdAt": ts}, HTTPStatus.CREATED)

        return self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)


def run():
    init_db()
    host = os.getenv("HOST", "127.0.0.1")
    port = to_int(os.getenv("PORT", "8000"), 8000)
    with ThreadingHTTPServer((host, port), Handler) as server:
        print(f"Kyungchinko server running at http://{host}:{port}")
        server.serve_forever()


if __name__ == "__main__":
    run()
