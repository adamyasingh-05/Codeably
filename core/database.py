"""
core/database.py
PostgreSQL connection + schema for Codeably.
Tables: sessions, messages, tool_logs, projects, config
Gracefully degrades if psycopg2 is not installed or DATABASE_URL is not set.
"""

import os, json
from datetime import datetime

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    path        TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
    id          SERIAL PRIMARY KEY,
    project_id  INTEGER REFERENCES projects(id),
    title       TEXT,
    provider    TEXT,
    model       TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id          SERIAL PRIMARY KEY,
    session_id  INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tool_logs (
    id          SERIAL PRIMARY KEY,
    session_id  INTEGER REFERENCES sessions(id) ON DELETE CASCADE,
    tool_name   TEXT NOT NULL,
    input       JSONB,
    output      TEXT,
    duration_ms INTEGER,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMP DEFAULT NOW()
);
"""

class DB:
    def __init__(self, dsn: str = None):
        self.dsn = dsn or os.environ.get("DATABASE_URL")
        self.conn = None
        if not HAS_PSYCOPG2:
            return
        if self.dsn:
            try:
                self._connect()
            except Exception as e:
                print(f"[DB] Could not connect: {e}. Running without database.")

    def _connect(self):
        self.conn = psycopg2.connect(self.dsn)
        self.conn.autocommit = True

    def init_schema(self):
        if not self.conn: return
        with self.conn.cursor() as cur:
            cur.execute(SCHEMA)

    def execute(self, sql: str, params=None):
        if not self.conn: return []
        with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            try: return cur.fetchall()
            except: return []

    # ── Sessions ──────────────────────────────────────────────────────────────

    def create_session(self, project_id=None, title=None, provider=None, model=None) -> int:
        rows = self.execute(
            "INSERT INTO sessions(project_id,title,provider,model) VALUES(%s,%s,%s,%s) RETURNING id",
            (project_id, title, provider, model))
        return rows[0]["id"] if rows else None

    def get_sessions(self, project_id=None):
        if project_id:
            return self.execute("SELECT * FROM sessions WHERE project_id=%s ORDER BY created_at DESC", (project_id,))
        return self.execute("SELECT * FROM sessions ORDER BY created_at DESC LIMIT 50")

    # ── Messages ──────────────────────────────────────────────────────────────

    def save_message(self, session_id: int, role: str, content: str):
        self.execute(
            "INSERT INTO messages(session_id,role,content) VALUES(%s,%s,%s)",
            (session_id, role, content))

    def get_messages(self, session_id: int):
        return self.execute(
            "SELECT role, content FROM messages WHERE session_id=%s ORDER BY created_at",
            (session_id,))

    # ── Tool logs ─────────────────────────────────────────────────────────────

    def log_tool(self, session_id: int, tool_name: str, input_: dict, output: str, duration_ms: int):
        self.execute(
            "INSERT INTO tool_logs(session_id,tool_name,input,output,duration_ms) VALUES(%s,%s,%s,%s,%s)",
            (session_id, tool_name, json.dumps(input_), output, duration_ms))

    # ── Config ────────────────────────────────────────────────────────────────

    def set_config(self, key: str, value: str):
        self.execute(
            "INSERT INTO config(key,value) VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=%s, updated_at=NOW()",
            (key, value, value))

    def get_config(self, key: str) -> str:
        rows = self.execute("SELECT value FROM config WHERE key=%s", (key,))
        return rows[0]["value"] if rows else None

    # ── Projects ──────────────────────────────────────────────────────────────

    def create_project(self, name: str, path: str) -> int:
        rows = self.execute(
            "INSERT INTO projects(name,path) VALUES(%s,%s) RETURNING id", (name, path))
        return rows[0]["id"] if rows else None

    def get_projects(self):
        return self.execute("SELECT * FROM projects ORDER BY created_at DESC")
