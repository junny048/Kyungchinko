import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from random import SystemRandom
from urllib.parse import parse_qs, urlparse

DB_PATH = os.getenv("DB_PATH", "app.db")
ADMIN_KEY = os.getenv("ADMIN_KEY", "dev-admin-key")
WEBHOOK_TOKEN = os.getenv("WEBHOOK_TOKEN", "dev-webhook-token")
SPIN_SIGNING_KEY = os.getenv("SPIN_SIGNING_KEY", "dev-spin-signing-key")
WEB_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "web"))

_rng = SystemRandom()
_rate_lock = threading.Lock()
_rate_windows = {}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(v: str) -> datetime:
    return datetime.fromisoformat(v)


def hash_password(password: str) -> str:
    salt = os.getenv("PASSWORD_SALT", "change-me-in-production")
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def spin_signature(payload: str) -> str:
    return hmac.new(SPIN_SIGNING_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def check_rate_limit(scope: str, key: str, max_requests: int, window_seconds: int) -> bool:
    ts = now_dt().timestamp()
    k = (scope, key)
    with _rate_lock:
        arr = [x for x in _rate_windows.get(k, []) if ts - x < window_seconds]
        if len(arr) >= max_requests:
            _rate_windows[k] = arr
            return False
        arr.append(ts)
        _rate_windows[k] = arr
    return True


def weighted_choice(rows):
    total = sum(x["weight"] for x in rows if x["weight"] > 0)
    if total <= 0:
        raise ValueError("invalid probability weights")
    target = _rng.uniform(0, total)
    acc = 0.0
    for row in rows:
        if row["weight"] <= 0:
            continue
        acc += row["weight"]
        if target <= acc:
            return row
    return rows[-1]


def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_probability_version(conn: sqlite3.Connection, machine_id: int, notes: str, tiers, rewards, publish: bool):
    ver = conn.execute(
        "SELECT COALESCE(MAX(version_number), 0) + 1 FROM probability_versions WHERE machine_id = ?",
        (machine_id,),
    ).fetchone()[0]
    ts = now_iso()
    status = "PUBLISHED" if publish else "DRAFT"
    published_at = ts if publish else None
    cur = conn.execute(
        "INSERT INTO probability_versions (machine_id, version_number, notes, status, published_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (machine_id, ver, notes, status, published_at, ts),
    )
    pv_id = cur.lastrowid

    for t in tiers:
        conn.execute(
            "INSERT INTO probability_tiers (probability_version_id, rarity, weight) VALUES (?, ?, ?)",
            (pv_id, t["rarity"], int(t["weight"])),
        )

    for r in rewards:
        rr = conn.execute("SELECT id, rarity FROM reward_catalog WHERE id = ?", (int(r["rewardId"]),)).fetchone()
        if not rr:
            raise ValueError(f"rewardId not found: {r['rewardId']}")
        conn.execute(
            "INSERT INTO reward_pool_items (probability_version_id, reward_id, rarity, weight) VALUES (?, ?, ?, ?)",
            (pv_id, rr[0], rr[1], int(r["weight"])),
        )

    if publish:
        conn.execute("UPDATE probability_versions SET status = 'ARCHIVED' WHERE machine_id = ? AND id != ? AND status = 'PUBLISHED'", (machine_id, pv_id))
        conn.execute("UPDATE machines SET probability_version_id = ?, updated_at = ? WHERE id = ?", (pv_id, ts, machine_id))

    return pv_id


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            age_verified INTEGER NOT NULL DEFAULT 0,
            self_excluded_until TEXT,
            ban_reason TEXT,
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
        CREATE TABLE IF NOT EXISTS responsible_limits (
            user_id INTEGER PRIMARY KEY,
            daily_charge_limit INTEGER,
            weekly_charge_limit INTEGER,
            monthly_charge_limit INTEGER,
            cooldown_until TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS shop_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            amount_krw INTEGER NOT NULL,
            point_granted INTEGER NOT NULL,
            bonus_point INTEGER NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            package_id INTEGER NOT NULL,
            order_id TEXT UNIQUE NOT NULL,
            amount_krw INTEGER NOT NULL,
            point_granted INTEGER NOT NULL,
            status TEXT NOT NULL,
            provider_payload TEXT,
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
            probability_version_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS probability_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            machine_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'DRAFT',
            published_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(machine_id, version_number)
        );
        CREATE TABLE IF NOT EXISTS probability_tiers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            probability_version_id INTEGER NOT NULL,
            rarity TEXT NOT NULL,
            weight INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reward_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            rarity TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            stackable INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reward_pool_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            probability_version_id INTEGER NOT NULL,
            reward_id INTEGER NOT NULL,
            rarity TEXT NOT NULL,
            weight INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS spins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            machine_id INTEGER NOT NULL,
            cost INTEGER NOT NULL,
            used_ticket INTEGER NOT NULL DEFAULT 0,
            probability_version_id INTEGER NOT NULL,
            result_rarity TEXT NOT NULL,
            result_reward_id INTEGER NOT NULL,
            client_idempotency_key TEXT NOT NULL,
            result_signature TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, client_idempotency_key)
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
        CREATE TABLE IF NOT EXISTS equipped_items (
            user_id INTEGER NOT NULL,
            slot TEXT NOT NULL,
            reward_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, slot)
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            badge_text TEXT,
            starts_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )

    if conn.execute("SELECT COUNT(*) FROM shop_packages").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO shop_packages (name, amount_krw, point_granted, bonus_point, sort_order, is_active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
            [
                ("Starter 5,000P", 5000, 5000, 500, 1, now_iso()),
                ("Standard 10,000P", 10000, 10000, 1200, 2, now_iso()),
                ("Jumbo 30,000P", 30000, 30000, 4500, 3, now_iso()),
            ],
        )

    if conn.execute("SELECT COUNT(*) FROM reward_catalog").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO reward_catalog (type, name, rarity, metadata_json, stackable, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("cosmetic", "Neon Frame", "Rare", json.dumps({"slot": "frame"}), 0, now_iso()),
                ("cosmetic", "Dragon Aura", "Legendary", json.dumps({"slot": "effect"}), 0, now_iso()),
                ("cosmetic", "Arcade Background", "Epic", json.dumps({"slot": "background"}), 0, now_iso()),
                ("currency", "Dust", "Common", json.dumps({"currency": "dust", "value": 25}), 1, now_iso()),
                ("currency", "Spin Ticket", "Rare", json.dumps({"currency": "ticket", "value": 1}), 1, now_iso()),
                ("access", "Season Pass EXP 100", "Common", json.dumps({"exp": 100}), 1, now_iso()),
            ],
        )

    if conn.execute("SELECT COUNT(*) FROM machines").fetchone()[0] == 0:
        ts = now_iso()
        cur = conn.execute(
            "INSERT INTO machines (name, theme, cost_per_spin, is_active, rules_text, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?, ?)",
            ("Neon Jackpot", "cyber-city", 100, "Digital rewards only. No cash-out.", ts, ts),
        )
        mid = cur.lastrowid
        create_probability_version(
            conn,
            mid,
            "seed",
            [
                {"rarity": "Common", "weight": 70},
                {"rarity": "Rare", "weight": 20},
                {"rarity": "Epic", "weight": 8},
                {"rarity": "Legendary", "weight": 2},
            ],
            [
                {"rewardId": 4, "weight": 70},
                {"rewardId": 6, "weight": 15},
                {"rewardId": 5, "weight": 8},
                {"rewardId": 1, "weight": 4},
                {"rewardId": 3, "weight": 2},
                {"rewardId": 2, "weight": 1},
            ],
            True,
        )

    if conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0:
        ts = now_iso()
        conn.execute(
            "INSERT INTO events (title, body, badge_text, starts_at, ends_at, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            ("Welcome Season", "Launch event.", "SEASON", ts, (now_dt() + timedelta(days=14)).isoformat(), ts, ts),
        )

    conn.commit()
    conn.close()

class AppHandler(BaseHTTPRequestHandler):
    server_version = "KyungchinkoMVP/1.0"

    def parse_json_body(self):
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n > 0 else b"{}"
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

    def write_file(self, file_path: str):
        if not os.path.isfile(file_path):
            self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        with open(file_path, "rb") as f:
            body = f.read()
        mime = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def require_admin(self) -> bool:
        if self.headers.get("X-Admin-Key", "") != ADMIN_KEY:
            self.write_json({"error": "Admin access required"}, HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def require_auth_user(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self.write_json({"error": "Missing bearer token"}, HTTPStatus.UNAUTHORIZED)
            return None
        token = auth.split(" ", 1)[1].strip()
        conn = get_conn()
        user = conn.execute(
            "SELECT u.id, u.status FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
            (token,),
        ).fetchone()
        conn.close()
        if not user:
            self.write_json({"error": "Invalid token"}, HTTPStatus.UNAUTHORIZED)
            return None
        if user["status"] != "active":
            self.write_json({"error": "User is not active"}, HTTPStatus.FORBIDDEN)
            return None
        return user["id"]

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            return self.write_file(os.path.join(WEB_ROOT, "index.html"))
        if path.startswith("/static/"):
            rel = path.removeprefix("/static/")
            if ".." in rel or rel.startswith("/"):
                return self.write_json({"error": "Bad path"}, HTTPStatus.BAD_REQUEST)
            return self.write_file(os.path.join(WEB_ROOT, "static", rel))

        if path == "/health":
            return self.write_json({"ok": True, "time": now_iso()})
        if path == "/api/shop/packages":
            return self.handle_get_shop_packages()
        if path == "/api/machines":
            return self.handle_get_machines()
        if path == "/api/events":
            return self.handle_get_events()

        if path == "/api/wallet":
            uid = self.require_auth_user()
            if not uid:
                return
            return self.handle_get_wallet(uid)
        if path == "/api/inventory":
            uid = self.require_auth_user()
            if not uid:
                return
            return self.handle_get_inventory(uid, query)
        if path == "/api/me/history":
            uid = self.require_auth_user()
            if not uid:
                return
            return self.handle_get_history(uid, query)
        if path == "/api/me/responsible-limit":
            uid = self.require_auth_user()
            if not uid:
                return
            return self.handle_get_responsible_limit(uid)

        m = re.fullmatch(r"/api/machines/(\d+)", path)
        if m:
            return self.handle_get_machine(int(m.group(1)))

        m = re.fullmatch(r"/api/admin/users/(\d+)", path)
        if m:
            if not self.require_admin():
                return
            return self.handle_admin_get_user(int(m.group(1)))

        self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/api/auth/signup":
            return self.handle_signup()
        if path == "/api/auth/login":
            return self.handle_login()
        if path == "/api/auth/logout":
            uid = self.require_auth_user()
            if not uid:
                return
            return self.handle_logout()

        if path == "/api/payments/create-order":
            uid = self.require_auth_user()
            if not uid:
                return
            return self.handle_create_order(uid)
        if path.startswith("/api/payments/webhook/"):
            return self.handle_payment_webhook(path.rsplit("/", 1)[-1])

        if path == "/api/inventory/equip":
            uid = self.require_auth_user()
            if not uid:
                return
            return self.handle_inventory_equip(uid)
        if path == "/api/me/responsible-limit":
            uid = self.require_auth_user()
            if not uid:
                return
            return self.handle_set_responsible_limit(uid)
        if path == "/api/me/self-exclusion":
            uid = self.require_auth_user()
            if not uid:
                return
            return self.handle_set_self_exclusion(uid)

        m = re.fullmatch(r"/api/machines/(\d+)/spin", path)
        if m:
            uid = self.require_auth_user()
            if not uid:
                return
            return self.handle_spin(uid, int(m.group(1)))

        if path == "/api/admin/machines":
            if not self.require_admin():
                return
            return self.handle_admin_create_machine()
        if path == "/api/admin/events":
            if not self.require_admin():
                return
            return self.handle_admin_create_event()

        m = re.fullmatch(r"/api/admin/machines/(\d+)/probability/versions", path)
        if m:
            if not self.require_admin():
                return
            return self.handle_admin_create_probability_version(int(m.group(1)))

        m = re.fullmatch(r"/api/admin/users/(\d+)/adjust-points", path)
        if m:
            if not self.require_admin():
                return
            return self.handle_admin_adjust_points(int(m.group(1)))

        self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        path = urlparse(self.path).path

        m = re.fullmatch(r"/api/admin/machines/(\d+)", path)
        if m:
            if not self.require_admin():
                return
            return self.handle_admin_update_machine(int(m.group(1)))

        m = re.fullmatch(r"/api/admin/probability/versions/(\d+)/publish", path)
        if m:
            if not self.require_admin():
                return
            return self.handle_admin_publish_probability_version(int(m.group(1)))

        self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def handle_signup(self):
        body = self.parse_json_body()
        if body is None:
            return
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        age_verified = 1 if bool(body.get("ageVerified", False)) else 0
        if not email or len(password) < 8:
            return self.write_json({"error": "email and password(>=8 chars) are required"}, HTTPStatus.BAD_REQUEST)

        conn = get_conn()
        try:
            ts = now_iso()
            cur = conn.execute("INSERT INTO users (email, password_hash, age_verified, created_at) VALUES (?, ?, ?, ?)", (email, hash_password(password), age_verified, ts))
            uid = cur.lastrowid
            conn.execute("INSERT INTO wallets (user_id, balance_point, updated_at) VALUES (?, 0, ?)", (uid, ts))
            conn.execute("INSERT INTO responsible_limits (user_id, daily_charge_limit, weekly_charge_limit, monthly_charge_limit, cooldown_until, updated_at) VALUES (?, NULL, NULL, NULL, NULL, ?)", (uid, ts))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return self.write_json({"error": "Email already exists"}, HTTPStatus.CONFLICT)
        conn.close()
        self.write_json({"id": uid, "email": email, "ageVerified": bool(age_verified)}, HTTPStatus.CREATED)

    def handle_login(self):
        body = self.parse_json_body()
        if body is None:
            return
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        conn = get_conn()
        user = conn.execute("SELECT id, email, password_hash, age_verified, status FROM users WHERE email = ?", (email,)).fetchone()
        if not user or user["password_hash"] != hash_password(password):
            conn.close()
            return self.write_json({"error": "Invalid credentials"}, HTTPStatus.UNAUTHORIZED)
        token = secrets.token_hex(24)
        conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)", (token, user["id"], now_iso()))
        conn.commit()
        conn.close()
        self.write_json({"token": token, "user": {"id": user["id"], "email": user["email"], "ageVerified": bool(user["age_verified"]), "status": user["status"]}})

    def handle_logout(self):
        token = self.headers.get("Authorization", "").split(" ", 1)[1].strip()
        conn = get_conn()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
        self.write_json({"ok": True})

    def handle_get_shop_packages(self):
        conn = get_conn()
        rows = conn.execute("SELECT id, name, amount_krw, point_granted, bonus_point FROM shop_packages WHERE is_active = 1 ORDER BY sort_order, id").fetchall()
        conn.close()
        self.write_json({"items": [{"id": r["id"], "name": r["name"], "amountKRW": r["amount_krw"], "pointGranted": r["point_granted"], "bonusPoint": r["bonus_point"], "totalPoint": r["point_granted"] + r["bonus_point"]} for r in rows]})

    def handle_get_wallet(self, uid: int):
        conn = get_conn()
        wallet = conn.execute("SELECT user_id, balance_point, updated_at FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        txs = conn.execute("SELECT id, type, amount, ref_type, ref_id, created_at FROM wallet_transactions WHERE user_id = ? ORDER BY id DESC LIMIT 30", (uid,)).fetchall()
        conn.close()
        self.write_json({"userId": wallet["user_id"], "balancePoint": wallet["balance_point"], "updatedAt": wallet["updated_at"], "recentTransactions": [dict(x) for x in txs]})

    def handle_create_order(self, uid: int):
        if not check_rate_limit("create-order", str(uid), 20, 60):
            return self.write_json({"error": "Too many payment attempts"}, HTTPStatus.TOO_MANY_REQUESTS)
        body = self.parse_json_body()
        if body is None:
            return
        package_id = to_int(body.get("packageId"))
        provider = str(body.get("provider", "mockpay")).strip().lower()
        if package_id is None:
            return self.write_json({"error": "packageId is required"}, HTTPStatus.BAD_REQUEST)

        conn = get_conn()
        pkg = conn.execute("SELECT id, amount_krw, point_granted, bonus_point FROM shop_packages WHERE id = ? AND is_active = 1", (package_id,)).fetchone()
        if not pkg:
            conn.close()
            return self.write_json({"error": "Invalid package"}, HTTPStatus.BAD_REQUEST)

        limit = conn.execute("SELECT daily_charge_limit, weekly_charge_limit, monthly_charge_limit FROM responsible_limits WHERE user_id = ?", (uid,)).fetchone()

        def charged_since(days):
            return conn.execute("SELECT COALESCE(SUM(amount), 0) FROM wallet_transactions WHERE user_id = ? AND type = 'CHARGE' AND created_at >= ?", (uid, (now_dt() - timedelta(days=days)).isoformat())).fetchone()[0]

        points = pkg["point_granted"] + pkg["bonus_point"]
        if limit and limit["daily_charge_limit"] is not None and charged_since(1) + points > limit["daily_charge_limit"]:
            conn.close(); return self.write_json({"error": "Daily charge limit exceeded"}, HTTPStatus.FORBIDDEN)
        if limit and limit["weekly_charge_limit"] is not None and charged_since(7) + points > limit["weekly_charge_limit"]:
            conn.close(); return self.write_json({"error": "Weekly charge limit exceeded"}, HTTPStatus.FORBIDDEN)
        if limit and limit["monthly_charge_limit"] is not None and charged_since(30) + points > limit["monthly_charge_limit"]:
            conn.close(); return self.write_json({"error": "Monthly charge limit exceeded"}, HTTPStatus.FORBIDDEN)

        order_id = f"ORD-{secrets.token_hex(8).upper()}"
        conn.execute("INSERT INTO payments (user_id, provider, package_id, order_id, amount_krw, point_granted, status, provider_payload, created_at) VALUES (?, ?, ?, ?, ?, ?, 'CREATED', ?, ?)", (uid, provider, pkg["id"], order_id, pkg["amount_krw"], points, json.dumps({"requestedAt": now_iso()}), now_iso()))
        conn.commit(); conn.close()
        self.write_json({"orderId": order_id, "provider": provider, "amountKRW": pkg["amount_krw"], "pointGranted": points, "status": "CREATED"}, HTTPStatus.CREATED)

    def handle_payment_webhook(self, provider: str):
        if self.headers.get("X-Webhook-Token", "") != WEBHOOK_TOKEN:
            return self.write_json({"error": "Invalid webhook token"}, HTTPStatus.UNAUTHORIZED)
        body = self.parse_json_body()
        if body is None:
            return
        order_id = str(body.get("orderId", "")).strip()
        status = str(body.get("status", "")).strip().upper()
        payload = body.get("payload", {})
        if not order_id or status not in {"PAID", "FAILED", "CANCELED"}:
            return self.write_json({"error": "orderId and valid status are required"}, HTTPStatus.BAD_REQUEST)

        conn = get_conn(); conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            payment = conn.execute("SELECT id, user_id, point_granted, status FROM payments WHERE order_id = ? AND provider = ?", (order_id, provider)).fetchone()
            if not payment:
                conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Payment not found"}, HTTPStatus.NOT_FOUND)
            if payment["status"] in {"PAID", "FAILED", "CANCELED"}:
                conn.execute("COMMIT"); conn.close(); return self.write_json({"ok": True, "idempotent": True, "status": payment["status"]})
            ts = now_iso()
            if status == "PAID":
                conn.execute("UPDATE payments SET status = 'PAID', paid_at = ?, provider_payload = ? WHERE id = ?", (ts, json.dumps(payload), payment["id"]))
                conn.execute("UPDATE wallets SET balance_point = balance_point + ?, updated_at = ? WHERE user_id = ?", (payment["point_granted"], ts, payment["user_id"]))
                conn.execute("INSERT INTO wallet_transactions (user_id, type, amount, ref_type, ref_id, created_at) VALUES (?, 'CHARGE', ?, 'PAYMENT', ?, ?)", (payment["user_id"], payment["point_granted"], order_id, ts))
            else:
                conn.execute("UPDATE payments SET status = ?, provider_payload = ? WHERE id = ?", (status, json.dumps(payload), payment["id"]))
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Webhook processing failed", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        conn.close()
        self.write_json({"ok": True, "status": status})

    def handle_get_machines(self):
        conn = get_conn()
        badge = conn.execute("SELECT badge_text FROM events WHERE is_active = 1 AND starts_at <= ? AND ends_at >= ? ORDER BY id DESC LIMIT 1", (now_iso(), now_iso())).fetchone()
        rows = conn.execute("SELECT id, name, theme, cost_per_spin, is_active, rules_text, probability_version_id, updated_at FROM machines WHERE is_active = 1 ORDER BY id").fetchall()
        out = []
        for r in rows:
            jackpot = None
            if r["probability_version_id"]:
                p = conn.execute("SELECT SUM(weight) total, SUM(CASE WHEN rarity='Legendary' THEN weight ELSE 0 END) legend FROM probability_tiers WHERE probability_version_id = ?", (r["probability_version_id"],)).fetchone()
                if p and p["total"]:
                    jackpot = round((p["legend"] or 0) * 100.0 / p["total"], 4)
            out.append({"id": r["id"], "name": r["name"], "theme": r["theme"], "costPerSpin": r["cost_per_spin"], "isActive": bool(r["is_active"]), "rulesText": r["rules_text"], "jackpotPercent": jackpot, "eventBadge": badge["badge_text"] if badge else None, "updatedAt": r["updated_at"]})
        conn.close()
        self.write_json({"items": out})

    def handle_get_machine(self, machine_id: int):
        conn = get_conn()
        m = conn.execute("SELECT id, name, theme, cost_per_spin, is_active, rules_text, probability_version_id, created_at, updated_at FROM machines WHERE id = ?", (machine_id,)).fetchone()
        if not m:
            conn.close(); return self.write_json({"error": "Machine not found"}, HTTPStatus.NOT_FOUND)

        prob = {"versionId": None, "tiers": []}; rewards = []
        if m["probability_version_id"]:
            pv = conn.execute("SELECT id, version_number, notes, status, published_at FROM probability_versions WHERE id = ?", (m["probability_version_id"],)).fetchone()
            tiers = conn.execute("SELECT rarity, weight FROM probability_tiers WHERE probability_version_id = ? ORDER BY id", (pv["id"],)).fetchall()
            pool = conn.execute("SELECT rpi.reward_id, rpi.rarity, rpi.weight, rc.type, rc.name, rc.stackable, rc.metadata_json FROM reward_pool_items rpi JOIN reward_catalog rc ON rc.id = rpi.reward_id WHERE rpi.probability_version_id = ? ORDER BY rpi.weight DESC, rpi.id", (pv["id"],)).fetchall()
            prob = {"versionId": pv["id"], "versionNumber": pv["version_number"], "status": pv["status"], "publishedAt": pv["published_at"], "notes": pv["notes"], "tiers": [dict(t) for t in tiers]}
            rewards = [{"rewardId": p["reward_id"], "name": p["name"], "type": p["type"], "rarity": p["rarity"], "weight": p["weight"], "stackable": bool(p["stackable"]), "metadata": json.loads(p["metadata_json"])} for p in pool]

        recent = conn.execute("SELECT s.id, s.result_rarity, rc.name, s.created_at FROM spins s JOIN reward_catalog rc ON rc.id = s.result_reward_id WHERE s.machine_id = ? ORDER BY s.id DESC LIMIT 10", (machine_id,)).fetchall()
        conn.close()
        self.write_json({"id": m["id"], "name": m["name"], "theme": m["theme"], "costPerSpin": m["cost_per_spin"], "isActive": bool(m["is_active"]), "rulesText": m["rules_text"], "probability": prob, "rewardPool": rewards, "recentWins": [{"spinId": x["id"], "rarity": x["result_rarity"], "rewardName": x["name"], "createdAt": x["created_at"]} for x in recent], "createdAt": m["created_at"], "updatedAt": m["updated_at"]})

    def handle_spin(self, uid: int, machine_id: int):
        if not check_rate_limit("spin", str(uid), 60, 60):
            return self.write_json({"error": "Too many spin requests"}, HTTPStatus.TOO_MANY_REQUESTS)
        body = self.parse_json_body()
        if body is None:
            return
        idem = str(body.get("idempotencyKey", "")).strip()
        use_ticket = bool(body.get("useTicket", False))
        if not idem:
            return self.write_json({"error": "idempotencyKey is required"}, HTTPStatus.BAD_REQUEST)

        conn = get_conn(); conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT s.id, s.cost, s.used_ticket, s.result_rarity, s.result_reward_id, s.probability_version_id, s.result_signature, s.created_at, rc.name reward_name FROM spins s JOIN reward_catalog rc ON rc.id = s.result_reward_id WHERE s.user_id = ? AND s.client_idempotency_key = ?", (uid, idem)).fetchone()
            if old:
                conn.execute("COMMIT"); conn.close(); return self.write_json({"idempotent": True, "spinId": old["id"], "cost": old["cost"], "usedTicket": bool(old["used_ticket"]), "rarity": old["result_rarity"], "reward": {"id": old["result_reward_id"], "name": old["reward_name"]}, "probabilityVersionId": old["probability_version_id"], "signature": old["result_signature"], "createdAt": old["created_at"]})

            user = conn.execute("SELECT self_excluded_until FROM users WHERE id = ?", (uid,)).fetchone()
            lim = conn.execute("SELECT cooldown_until FROM responsible_limits WHERE user_id = ?", (uid,)).fetchone()
            if user and user["self_excluded_until"] and now_dt() < parse_iso(user["self_excluded_until"]):
                conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": f"Self-excluded until {user['self_excluded_until']}"}, HTTPStatus.FORBIDDEN)
            if lim and lim["cooldown_until"] and now_dt() < parse_iso(lim["cooldown_until"]):
                conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": f"Cooldown active until {lim['cooldown_until']}"}, HTTPStatus.FORBIDDEN)

            m = conn.execute("SELECT id, cost_per_spin, is_active, probability_version_id FROM machines WHERE id = ?", (machine_id,)).fetchone()
            if not m: conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Machine not found"}, HTTPStatus.NOT_FOUND)
            if m["is_active"] != 1: conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Machine is inactive"}, HTTPStatus.BAD_REQUEST)
            if not m["probability_version_id"]: conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Machine has no published probability"}, HTTPStatus.BAD_REQUEST)

            cost = m["cost_per_spin"]; used_ticket = 0
            if use_ticket:
                tid = conn.execute("SELECT id FROM reward_catalog WHERE name = 'Spin Ticket' LIMIT 1").fetchone()
                inv = conn.execute("SELECT id, qty FROM inventory WHERE user_id = ? AND reward_id = ? ORDER BY id LIMIT 1", (uid, tid["id"])).fetchone() if tid else None
                if not inv or inv["qty"] <= 0: conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "No ticket available"}, HTTPStatus.BAD_REQUEST)
                conn.execute("UPDATE inventory SET qty = qty - 1 WHERE id = ?", (inv["id"],)); conn.execute("DELETE FROM inventory WHERE id = ? AND qty <= 0", (inv["id"],))
                cost = 0; used_ticket = 1
            else:
                bal = conn.execute("SELECT balance_point FROM wallets WHERE user_id = ?", (uid,)).fetchone()
                if bal["balance_point"] < cost: conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Insufficient points"}, HTTPStatus.BAD_REQUEST)
                conn.execute("UPDATE wallets SET balance_point = balance_point - ?, updated_at = ? WHERE user_id = ?", (cost, now_iso(), uid))
                conn.execute("INSERT INTO wallet_transactions (user_id, type, amount, ref_type, ref_id, created_at) VALUES (?, 'SPEND', ?, 'SPIN', ?, ?)", (uid, -cost, f"machine:{machine_id}", now_iso()))

            pv = m["probability_version_id"]
            tiers = conn.execute("SELECT rarity, weight FROM probability_tiers WHERE probability_version_id = ?", (pv,)).fetchall()
            pool = conn.execute("SELECT rpi.reward_id, rpi.rarity, rpi.weight, rc.name, rc.type, rc.stackable, rc.metadata_json FROM reward_pool_items rpi JOIN reward_catalog rc ON rc.id = rpi.reward_id WHERE rpi.probability_version_id = ?", (pv,)).fetchall()
            if not tiers or not pool: conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Probability table is not complete"}, HTTPStatus.INTERNAL_SERVER_ERROR)

            tier = weighted_choice([{"rarity": t["rarity"], "weight": t["weight"]} for t in tiers])
            cand = [x for x in pool if x["rarity"] == tier["rarity"]] or pool
            reward = weighted_choice([{"rewardId": r["reward_id"], "rarity": r["rarity"], "weight": r["weight"], "name": r["name"], "type": r["type"], "stackable": r["stackable"], "metadata": r["metadata_json"]} for r in cand])

            ts = now_iso(); sig = spin_signature(f"{uid}|{machine_id}|{pv}|{reward['rewardId']}|{reward['rarity']}|{ts}|{idem}")
            sid = conn.execute("INSERT INTO spins (user_id, machine_id, cost, used_ticket, probability_version_id, result_rarity, result_reward_id, client_idempotency_key, result_signature, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (uid, machine_id, cost, used_ticket, pv, reward["rarity"], reward["rewardId"], idem, sig, ts)).lastrowid

            if reward["stackable"] == 1:
                row = conn.execute("SELECT id FROM inventory WHERE user_id = ? AND reward_id = ? AND source_spin_id IS NULL LIMIT 1", (uid, reward["rewardId"])).fetchone()
                if row: conn.execute("UPDATE inventory SET qty = qty + 1, obtained_at = ? WHERE id = ?", (ts, row["id"]))
                else: conn.execute("INSERT INTO inventory (user_id, reward_id, qty, obtained_at, source_spin_id) VALUES (?, ?, 1, ?, NULL)", (uid, reward["rewardId"], ts))
            else:
                conn.execute("INSERT INTO inventory (user_id, reward_id, qty, obtained_at, source_spin_id) VALUES (?, ?, 1, ?, ?)", (uid, reward["rewardId"], ts, sid))

            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Spin failed", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        bal = conn.execute("SELECT balance_point FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance_point"]
        conn.close()
        self.write_json({"spinId": sid, "cost": cost, "usedTicket": bool(used_ticket), "rarity": reward["rarity"], "reward": {"id": reward["rewardId"], "name": reward["name"], "type": reward["type"], "metadata": json.loads(reward["metadata"])}, "probabilityVersionId": pv, "signature": sig, "walletBalance": bal, "createdAt": ts}, HTTPStatus.CREATED)

    def handle_get_inventory(self, uid: int, query):
        rarity = query.get("rarity", [None])[0]
        typ = query.get("type", [None])[0]
        sql = "SELECT i.id, i.reward_id, i.qty, i.obtained_at, i.source_spin_id, rc.type, rc.name, rc.rarity, rc.metadata_json, rc.stackable FROM inventory i JOIN reward_catalog rc ON rc.id = i.reward_id WHERE i.user_id = ?"
        params = [uid]
        if rarity: sql += " AND rc.rarity = ?"; params.append(rarity)
        if typ: sql += " AND rc.type = ?"; params.append(typ)
        sql += " ORDER BY i.obtained_at DESC, i.id DESC"
        conn = get_conn()
        rows = conn.execute(sql, tuple(params)).fetchall()
        eq = conn.execute("SELECT e.slot, e.reward_id, rc.name FROM equipped_items e JOIN reward_catalog rc ON rc.id = e.reward_id WHERE e.user_id = ?", (uid,)).fetchall()
        conn.close()
        self.write_json({"items": [{"inventoryId": r["id"], "rewardId": r["reward_id"], "name": r["name"], "type": r["type"], "rarity": r["rarity"], "qty": r["qty"], "stackable": bool(r["stackable"]), "metadata": json.loads(r["metadata_json"]), "obtainedAt": r["obtained_at"], "sourceSpinId": r["source_spin_id"]} for r in rows], "equipped": [dict(x) for x in eq]})

    def handle_inventory_equip(self, uid: int):
        body = self.parse_json_body()
        if body is None:
            return
        slot = str(body.get("slot", "")).strip().lower()
        reward_id = to_int(body.get("rewardId"))
        if not slot or reward_id is None:
            return self.write_json({"error": "slot and rewardId are required"}, HTTPStatus.BAD_REQUEST)
        conn = get_conn()
        own = conn.execute("SELECT rc.metadata_json FROM inventory i JOIN reward_catalog rc ON rc.id = i.reward_id WHERE i.user_id = ? AND i.reward_id = ? AND i.qty > 0 LIMIT 1", (uid, reward_id)).fetchone()
        if not own: conn.close(); return self.write_json({"error": "Reward not in inventory"}, HTTPStatus.BAD_REQUEST)
        expected = json.loads(own["metadata_json"]).get("slot")
        if expected and expected != slot: conn.close(); return self.write_json({"error": f"Reward slot mismatch. expected={expected}"}, HTTPStatus.BAD_REQUEST)
        ts = now_iso()
        conn.execute("INSERT INTO equipped_items (user_id, slot, reward_id, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(user_id, slot) DO UPDATE SET reward_id = excluded.reward_id, updated_at = excluded.updated_at", (uid, slot, reward_id, ts))
        conn.commit(); conn.close()
        self.write_json({"ok": True, "slot": slot, "rewardId": reward_id, "updatedAt": ts})

    def handle_get_history(self, uid: int, query):
        typ = (query.get("type", ["all"])[0] or "all").lower()
        conn = get_conn(); out = {}
        if typ in {"all", "payments"}:
            out["payments"] = [dict(x) for x in conn.execute("SELECT order_id, provider, amount_krw, point_granted, status, created_at, paid_at FROM payments WHERE user_id = ? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()]
        if typ in {"all", "spins"}:
            out["spins"] = [dict(x) for x in conn.execute("SELECT s.id, s.machine_id, s.cost, s.used_ticket, s.result_rarity, rc.name reward_name, s.created_at FROM spins s JOIN reward_catalog rc ON rc.id = s.result_reward_id WHERE s.user_id = ? ORDER BY s.id DESC LIMIT 50", (uid,)).fetchall()]
        if typ in {"all", "rewards"}:
            out["rewards"] = [dict(x) for x in conn.execute("SELECT i.id, i.reward_id, rc.name, rc.rarity, i.qty, i.obtained_at, i.source_spin_id FROM inventory i JOIN reward_catalog rc ON rc.id = i.reward_id WHERE i.user_id = ? ORDER BY i.id DESC LIMIT 50", (uid,)).fetchall()]
        conn.close(); self.write_json(out)

    def handle_get_events(self):
        conn = get_conn(); rows = conn.execute("SELECT id, title, body, badge_text, starts_at, ends_at FROM events WHERE is_active = 1 AND starts_at <= ? AND ends_at >= ? ORDER BY id DESC", (now_iso(), now_iso())).fetchall(); conn.close()
        self.write_json({"items": [dict(x) for x in rows]})

    def handle_get_responsible_limit(self, uid: int):
        conn = get_conn(); row = conn.execute("SELECT daily_charge_limit, weekly_charge_limit, monthly_charge_limit, cooldown_until, updated_at FROM responsible_limits WHERE user_id = ?", (uid,)).fetchone(); conn.close()
        if not row: return self.write_json({"error": "Limit profile not found"}, HTTPStatus.NOT_FOUND)
        self.write_json(dict(row))

    def handle_set_responsible_limit(self, uid: int):
        body = self.parse_json_body()
        if body is None:
            return
        def norm(v):
            if v is None:
                return None
            i = to_int(v)
            if i is None:
                raise ValueError("invalid limit")
            return i if i > 0 else None
        try:
            daily = norm(body.get("dailyChargeLimit"))
            weekly = norm(body.get("weeklyChargeLimit"))
            monthly = norm(body.get("monthlyChargeLimit"))
        except ValueError:
            return self.write_json({"error": "charge limits must be integer or null"}, HTTPStatus.BAD_REQUEST)
        cooldown = body.get("cooldownMinutes"); cooldown_until = None
        if cooldown is not None:
            c = to_int(cooldown)
            if c is None:
                return self.write_json({"error": "cooldownMinutes must be integer"}, HTTPStatus.BAD_REQUEST)
            if c < 0: return self.write_json({"error": "cooldownMinutes must be >= 0"}, HTTPStatus.BAD_REQUEST)
            if c > 0: cooldown_until = (now_dt() + timedelta(minutes=c)).isoformat()
        ts = now_iso(); conn = get_conn()
        conn.execute("INSERT INTO responsible_limits (user_id, daily_charge_limit, weekly_charge_limit, monthly_charge_limit, cooldown_until, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET daily_charge_limit=excluded.daily_charge_limit, weekly_charge_limit=excluded.weekly_charge_limit, monthly_charge_limit=excluded.monthly_charge_limit, cooldown_until=excluded.cooldown_until, updated_at=excluded.updated_at", (uid, daily, weekly, monthly, cooldown_until, ts))
        conn.commit(); conn.close(); self.write_json({"dailyChargeLimit": daily, "weeklyChargeLimit": weekly, "monthlyChargeLimit": monthly, "cooldownUntil": cooldown_until, "updatedAt": ts})

    def handle_set_self_exclusion(self, uid: int):
        body = self.parse_json_body()
        if body is None: return
        days = to_int(body.get("days", 0))
        if days is None:
            return self.write_json({"error": "days must be integer"}, HTTPStatus.BAD_REQUEST)
        if days <= 0: return self.write_json({"error": "days must be > 0"}, HTTPStatus.BAD_REQUEST)
        until = (now_dt() + timedelta(days=days)).isoformat(); conn = get_conn(); conn.execute("UPDATE users SET self_excluded_until = ? WHERE id = ?", (until, uid)); conn.commit(); conn.close(); self.write_json({"ok": True, "selfExcludedUntil": until})

    def handle_admin_get_user(self, uid: int):
        conn = get_conn()
        u = conn.execute("SELECT id, email, status, age_verified, self_excluded_until, ban_reason, created_at FROM users WHERE id = ?", (uid,)).fetchone()
        if not u: conn.close(); return self.write_json({"error": "User not found"}, HTTPStatus.NOT_FOUND)
        w = conn.execute("SELECT balance_point, updated_at FROM wallets WHERE user_id = ?", (uid,)).fetchone()
        s = conn.execute("SELECT id, machine_id, cost, result_rarity, result_reward_id, created_at FROM spins WHERE user_id = ? ORDER BY id DESC LIMIT 20", (uid,)).fetchall()
        p = conn.execute("SELECT order_id, provider, amount_krw, point_granted, status, created_at, paid_at FROM payments WHERE user_id = ? ORDER BY id DESC LIMIT 20", (uid,)).fetchall()
        conn.close(); self.write_json({"id": u["id"], "email": u["email"], "status": u["status"], "ageVerified": bool(u["age_verified"]), "selfExcludedUntil": u["self_excluded_until"], "banReason": u["ban_reason"], "createdAt": u["created_at"], "wallet": {"balancePoint": w["balance_point"], "updatedAt": w["updated_at"]}, "recentSpins": [dict(x) for x in s], "recentPayments": [dict(x) for x in p]})

    def handle_admin_adjust_points(self, uid: int):
        body = self.parse_json_body()
        if body is None: return
        try: amount = int(body.get("amount", 0))
        except (TypeError, ValueError): return self.write_json({"error": "amount must be integer"}, HTTPStatus.BAD_REQUEST)
        if amount == 0: return self.write_json({"error": "amount must not be 0"}, HTTPStatus.BAD_REQUEST)
        reason = str(body.get("reason", "admin-adjust")).strip(); ts = now_iso(); conn = get_conn(); conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            w = conn.execute("SELECT balance_point FROM wallets WHERE user_id = ?", (uid,)).fetchone()
            if not w: conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "User wallet not found"}, HTTPStatus.NOT_FOUND)
            if w["balance_point"] + amount < 0: conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Insufficient balance for deduction"}, HTTPStatus.BAD_REQUEST)
            conn.execute("UPDATE wallets SET balance_point = balance_point + ?, updated_at = ? WHERE user_id = ?", (amount, ts, uid))
            conn.execute("INSERT INTO wallet_transactions (user_id, type, amount, ref_type, ref_id, created_at) VALUES (?, 'ADJUST', ?, 'ADMIN', ?, ?)", (uid, amount, reason, ts))
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "adjust failed", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        bal = conn.execute("SELECT balance_point FROM wallets WHERE user_id = ?", (uid,)).fetchone()["balance_point"]; conn.close(); self.write_json({"ok": True, "balancePoint": bal})

    def handle_admin_create_machine(self):
        body = self.parse_json_body()
        if body is None: return
        name = str(body.get("name", "")).strip(); theme = str(body.get("theme", "")).strip(); rules = str(body.get("rulesText", "")).strip()
        try: cost = int(body.get("costPerSpin", 0))
        except (TypeError, ValueError): cost = 0
        active = 1 if bool(body.get("isActive", True)) else 0
        if not name or not theme or not rules or cost <= 0: return self.write_json({"error": "name, theme, rulesText, costPerSpin(>0) are required"}, HTTPStatus.BAD_REQUEST)
        ts = now_iso(); conn = get_conn(); mid = conn.execute("INSERT INTO machines (name, theme, cost_per_spin, is_active, rules_text, probability_version_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)", (name, theme, cost, active, rules, ts, ts)).lastrowid; conn.commit(); conn.close(); self.write_json({"id": mid}, HTTPStatus.CREATED)

    def handle_admin_update_machine(self, machine_id: int):
        body = self.parse_json_body();
        if body is None: return
        fields = []; vals = []
        if "name" in body: fields.append("name = ?"); vals.append(str(body["name"]).strip())
        if "theme" in body: fields.append("theme = ?"); vals.append(str(body["theme"]).strip())
        if "rulesText" in body: fields.append("rules_text = ?"); vals.append(str(body["rulesText"]).strip())
        if "costPerSpin" in body:
            try: c = int(body["costPerSpin"])
            except (TypeError, ValueError): return self.write_json({"error": "costPerSpin must be integer"}, HTTPStatus.BAD_REQUEST)
            if c <= 0: return self.write_json({"error": "costPerSpin must be > 0"}, HTTPStatus.BAD_REQUEST)
            fields.append("cost_per_spin = ?"); vals.append(c)
        if "isActive" in body: fields.append("is_active = ?"); vals.append(1 if bool(body["isActive"]) else 0)
        if not fields: return self.write_json({"error": "No fields to update"}, HTTPStatus.BAD_REQUEST)
        fields.append("updated_at = ?"); vals.append(now_iso()); vals.append(machine_id)
        conn = get_conn(); rc = conn.execute(f"UPDATE machines SET {', '.join(fields)} WHERE id = ?", tuple(vals)).rowcount; conn.commit(); conn.close()
        self.write_json({"ok": True} if rc else {"error": "Machine not found"}, HTTPStatus.OK if rc else HTTPStatus.NOT_FOUND)

    def handle_admin_create_probability_version(self, machine_id: int):
        body = self.parse_json_body();
        if body is None: return
        tiers = body.get("tiers"); rewards = body.get("rewards"); notes = str(body.get("notes", "")).strip(); publish = bool(body.get("publish", False))
        if not isinstance(tiers, list) or not tiers: return self.write_json({"error": "tiers(list) is required"}, HTTPStatus.BAD_REQUEST)
        if not isinstance(rewards, list) or not rewards: return self.write_json({"error": "rewards(list) is required"}, HTTPStatus.BAD_REQUEST)
        conn = get_conn(); m = conn.execute("SELECT id FROM machines WHERE id = ?", (machine_id,)).fetchone()
        if not m: conn.close(); return self.write_json({"error": "Machine not found"}, HTTPStatus.NOT_FOUND)
        try: vid = create_probability_version(conn, machine_id, notes, tiers, rewards, publish); conn.commit()
        except Exception as exc: conn.rollback(); conn.close(); return self.write_json({"error": "Failed to create probability version", "detail": str(exc)}, HTTPStatus.BAD_REQUEST)
        conn.close(); self.write_json({"id": vid, "published": publish}, HTTPStatus.CREATED)

    def handle_admin_publish_probability_version(self, version_id: int):
        conn = get_conn(); pv = conn.execute("SELECT id, machine_id FROM probability_versions WHERE id = ?", (version_id,)).fetchone()
        if not pv: conn.close(); return self.write_json({"error": "Probability version not found"}, HTTPStatus.NOT_FOUND)
        ts = now_iso(); conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE probability_versions SET status = 'ARCHIVED' WHERE machine_id = ? AND status = 'PUBLISHED' AND id != ?", (pv["machine_id"], version_id))
            conn.execute("UPDATE probability_versions SET status = 'PUBLISHED', published_at = ? WHERE id = ?", (ts, version_id))
            conn.execute("UPDATE machines SET probability_version_id = ?, updated_at = ? WHERE id = ?", (version_id, ts, pv["machine_id"]))
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK"); conn.close(); return self.write_json({"error": "Publish failed", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
        conn.close(); self.write_json({"ok": True, "publishedVersionId": version_id})

    def handle_admin_create_event(self):
        body = self.parse_json_body();
        if body is None: return
        title = str(body.get("title", "")).strip(); event_body = str(body.get("body", "")).strip(); badge = str(body.get("badgeText", "")).strip() or None
        starts = str(body.get("startsAt", "")).strip(); ends = str(body.get("endsAt", "")).strip(); active = 1 if bool(body.get("isActive", True)) else 0
        if not title or not event_body or not starts or not ends: return self.write_json({"error": "title, body, startsAt, endsAt are required"}, HTTPStatus.BAD_REQUEST)
        try: parse_iso(starts); parse_iso(ends)
        except ValueError: return self.write_json({"error": "startsAt/endsAt must be ISO datetime"}, HTTPStatus.BAD_REQUEST)
        ts = now_iso(); conn = get_conn(); eid = conn.execute("INSERT INTO events (title, body, badge_text, starts_at, ends_at, is_active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (title, event_body, badge, starts, ends, active, ts, ts)).lastrowid; conn.commit(); conn.close(); self.write_json({"id": eid}, HTTPStatus.CREATED)


def run() -> None:
    init_db()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    with ThreadingHTTPServer((host, port), AppHandler) as server:
        print(f"Kyungchinko MVP API listening on http://{host}:{port}")
        server.serve_forever()


if __name__ == "__main__":
    run()
