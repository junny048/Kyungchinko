import hashlib
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

DB_PATH = os.getenv("DB_PATH", "app.db")
ADMIN_KEY = os.getenv("ADMIN_KEY", "dev-admin-key")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_password(password: str) -> str:
    salt = os.getenv("PASSWORD_SALT", "change-me-in-production")
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


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
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS wallets (
            user_id INTEGER PRIMARY KEY,
            balance_point INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            ref_type TEXT,
            ref_id TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
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
        """
    )

    machine_count = conn.execute("SELECT COUNT(*) FROM machines").fetchone()[0]
    if machine_count == 0:
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO machines (name, theme, cost_per_spin, is_active, rules_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Neon Jackpot",
                "cyber-city",
                100,
                1,
                "Spin once per round. Rewards are digital-only and non-refundable.",
                ts,
                ts,
            ),
        )

    conn.commit()
    conn.close()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class AppHandler(BaseHTTPRequestHandler):
    server_version = "KyungchinkoMVP/0.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/health":
            return self.write_json({"ok": True, "time": now_iso()})

        if path == "/api/wallet":
            user = self.require_auth_user()
            if not user:
                return
            return self.handle_get_wallet(user["id"])

        if path == "/api/machines":
            return self.handle_get_machines()

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
            user = self.require_auth_user()
            if not user:
                return
            return self.handle_logout()
        if path == "/api/admin/machines":
            if not self.require_admin():
                return
            return self.handle_admin_create_machine()

        self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_PUT(self):
        path = urlparse(self.path).path
        m = re.fullmatch(r"/api/admin/machines/(\d+)", path)
        if m:
            if not self.require_admin():
                return
            return self.handle_admin_update_machine(int(m.group(1)))

        self.write_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def parse_json_body(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
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

    def require_admin(self) -> bool:
        key = self.headers.get("X-Admin-Key", "")
        if key != ADMIN_KEY:
            self.write_json({"error": "Admin access required"}, HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def require_auth_user(self):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self.write_json({"error": "Missing bearer token"}, HTTPStatus.UNAUTHORIZED)
            return None

        token = auth.removeprefix("Bearer ").strip()
        conn = get_conn()
        row = conn.execute(
            """
            SELECT u.id, u.email, u.status, u.age_verified, u.created_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
        conn.close()

        if not row:
            self.write_json({"error": "Invalid token"}, HTTPStatus.UNAUTHORIZED)
            return None

        return row

    def handle_signup(self):
        body = self.parse_json_body()
        if body is None:
            return

        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        age_verified = 1 if bool(body.get("ageVerified", False)) else 0

        if not email or not password or len(password) < 8:
            return self.write_json(
                {"error": "email and password(>=8 chars) are required"},
                HTTPStatus.BAD_REQUEST,
            )

        conn = get_conn()
        try:
            ts = now_iso()
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, age_verified, created_at) VALUES (?, ?, ?, ?)",
                (email, hash_password(password), age_verified, ts),
            )
            user_id = cur.lastrowid
            conn.execute(
                "INSERT INTO wallets (user_id, balance_point, updated_at) VALUES (?, 0, ?)",
                (user_id, ts),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return self.write_json({"error": "Email already exists"}, HTTPStatus.CONFLICT)

        conn.close()
        self.write_json({"id": user_id, "email": email, "ageVerified": bool(age_verified)}, HTTPStatus.CREATED)

    def handle_login(self):
        body = self.parse_json_body()
        if body is None:
            return

        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))

        conn = get_conn()
        user = conn.execute(
            "SELECT id, email, password_hash, age_verified, status FROM users WHERE email = ?",
            (email,),
        ).fetchone()

        if not user or user["password_hash"] != hash_password(password):
            conn.close()
            return self.write_json({"error": "Invalid credentials"}, HTTPStatus.UNAUTHORIZED)

        token = secrets.token_hex(24)
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            (token, user["id"], now_iso()),
        )
        conn.commit()
        conn.close()

        self.write_json(
            {
                "token": token,
                "user": {
                    "id": user["id"],
                    "email": user["email"],
                    "ageVerified": bool(user["age_verified"]),
                    "status": user["status"],
                },
            }
        )

    def handle_logout(self):
        auth = self.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        conn = get_conn()
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
        conn.close()
        self.write_json({"ok": True})

    def handle_get_wallet(self, user_id: int):
        conn = get_conn()
        wallet = conn.execute(
            "SELECT user_id, balance_point, updated_at FROM wallets WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        txs = conn.execute(
            """
            SELECT id, type, amount, ref_type, ref_id, created_at
            FROM wallet_transactions
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT 20
            """,
            (user_id,),
        ).fetchall()
        conn.close()

        self.write_json(
            {
                "userId": wallet["user_id"],
                "balancePoint": wallet["balance_point"],
                "updatedAt": wallet["updated_at"],
                "recentTransactions": [dict(tx) for tx in txs],
            }
        )

    def handle_get_machines(self):
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT id, name, theme, cost_per_spin, is_active, rules_text, updated_at
            FROM machines
            WHERE is_active = 1
            ORDER BY id ASC
            """
        ).fetchall()
        conn.close()

        self.write_json(
            {
                "items": [
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "theme": row["theme"],
                        "costPerSpin": row["cost_per_spin"],
                        "isActive": bool(row["is_active"]),
                        "rulesText": row["rules_text"],
                        "updatedAt": row["updated_at"],
                    }
                    for row in rows
                ]
            }
        )

    def handle_get_machine(self, machine_id: int):
        conn = get_conn()
        row = conn.execute(
            """
            SELECT id, name, theme, cost_per_spin, is_active, rules_text, created_at, updated_at
            FROM machines
            WHERE id = ?
            """,
            (machine_id,),
        ).fetchone()
        conn.close()

        if not row:
            return self.write_json({"error": "Machine not found"}, HTTPStatus.NOT_FOUND)

        self.write_json(
            {
                "id": row["id"],
                "name": row["name"],
                "theme": row["theme"],
                "costPerSpin": row["cost_per_spin"],
                "isActive": bool(row["is_active"]),
                "rulesText": row["rules_text"],
                "createdAt": row["created_at"],
                "updatedAt": row["updated_at"],
            }
        )

    def handle_admin_get_user(self, user_id: int):
        conn = get_conn()
        user = conn.execute(
            "SELECT id, email, status, age_verified, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            conn.close()
            return self.write_json({"error": "User not found"}, HTTPStatus.NOT_FOUND)

        wallet = conn.execute(
            "SELECT balance_point, updated_at FROM wallets WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()

        self.write_json(
            {
                "id": user["id"],
                "email": user["email"],
                "status": user["status"],
                "ageVerified": bool(user["age_verified"]),
                "createdAt": user["created_at"],
                "wallet": {
                    "balancePoint": wallet["balance_point"],
                    "updatedAt": wallet["updated_at"],
                },
            }
        )

    def handle_admin_create_machine(self):
        body = self.parse_json_body()
        if body is None:
            return

        name = str(body.get("name", "")).strip()
        theme = str(body.get("theme", "")).strip()
        rules_text = str(body.get("rulesText", "")).strip()
        try:
            cost_per_spin = int(body.get("costPerSpin", 0))
        except (TypeError, ValueError):
            cost_per_spin = 0
        is_active = 1 if bool(body.get("isActive", True)) else 0

        if not name or not theme or not rules_text or cost_per_spin <= 0:
            return self.write_json(
                {"error": "name, theme, rulesText, costPerSpin(>0) are required"},
                HTTPStatus.BAD_REQUEST,
            )

        ts = now_iso()
        conn = get_conn()
        cur = conn.execute(
            """
            INSERT INTO machines (name, theme, cost_per_spin, is_active, rules_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, theme, cost_per_spin, is_active, rules_text, ts, ts),
        )
        conn.commit()
        machine_id = cur.lastrowid
        conn.close()

        self.write_json({"id": machine_id}, HTTPStatus.CREATED)

    def handle_admin_update_machine(self, machine_id: int):
        body = self.parse_json_body()
        if body is None:
            return

        fields = []
        values = []
        if "name" in body:
            fields.append("name = ?")
            values.append(str(body["name"]).strip())
        if "theme" in body:
            fields.append("theme = ?")
            values.append(str(body["theme"]).strip())
        if "rulesText" in body:
            fields.append("rules_text = ?")
            values.append(str(body["rulesText"]).strip())
        if "costPerSpin" in body:
            try:
                c = int(body["costPerSpin"])
            except (TypeError, ValueError):
                return self.write_json({"error": "costPerSpin must be integer"}, HTTPStatus.BAD_REQUEST)
            if c <= 0:
                return self.write_json({"error": "costPerSpin must be > 0"}, HTTPStatus.BAD_REQUEST)
            fields.append("cost_per_spin = ?")
            values.append(c)
        if "isActive" in body:
            fields.append("is_active = ?")
            values.append(1 if bool(body["isActive"]) else 0)

        if not fields:
            return self.write_json({"error": "No fields to update"}, HTTPStatus.BAD_REQUEST)

        fields.append("updated_at = ?")
        values.append(now_iso())
        values.append(machine_id)

        conn = get_conn()
        cur = conn.execute(
            f"UPDATE machines SET {', '.join(fields)} WHERE id = ?",
            tuple(values),
        )
        conn.commit()
        changed = cur.rowcount
        conn.close()

        if changed == 0:
            return self.write_json({"error": "Machine not found"}, HTTPStatus.NOT_FOUND)

        self.write_json({"ok": True})


def run() -> None:
    init_db()
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    with ThreadingHTTPServer((host, port), AppHandler) as server:
        print(f"Kyungchinko MVP API listening on http://{host}:{port}")
        server.serve_forever()


if __name__ == "__main__":
    run()
