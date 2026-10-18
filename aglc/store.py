"""SQLite store for paid use (only touched when AGLC_PAYMENTS is set).

One file, `$AGLC_DATA_DIR/aglc.db`, in WAL mode so the web workers can read while a
webhook writes. The schema is versioned with `PRAGMA user_version`: append a migration
to MIGRATIONS, never edit one that has shipped.

    documents       one row per processed upload (the session id is the entitlement in v1)
    orders          one row per checkout; status pending -> paid -> refunding -> refunded
    webhook_events  every webhook applied, keyed by the provider's event id (idempotency)
    meta            small settings, eg the salt for hashing IP addresses
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS: list[str] = [
    # 1: initial schema
    """
    CREATE TABLE documents (
        session_id     TEXT PRIMARY KEY,
        filename       TEXT NOT NULL,
        status         TEXT NOT NULL DEFAULT 'processing',  -- processing | ready | failed
        footnote_count INTEGER NOT NULL DEFAULT 0,
        ip_hash        TEXT,
        anon_id        TEXT,
        day            TEXT NOT NULL,                        -- UTC date, for quotas
        created_at     TEXT NOT NULL,
        unlocked_at    TEXT,
        unlocked_by    TEXT                                  -- orders.id
    );
    CREATE INDEX documents_day_ip ON documents(day, ip_hash);
    CREATE INDEX documents_day_anon ON documents(day, anon_id);

    CREATE TABLE orders (
        id                   TEXT PRIMARY KEY,
        session_id           TEXT NOT NULL REFERENCES documents(session_id),
        product              TEXT NOT NULL,
        amount               INTEGER NOT NULL,
        currency             TEXT NOT NULL,
        provider             TEXT NOT NULL,
        status               TEXT NOT NULL DEFAULT 'pending',  -- pending | paid | refunding | refunded | refund_failed | failed
        checkout_id          TEXT,
        checkout_url         TEXT,
        provider_order_id    TEXT,
        payment_id           TEXT,
        refund_id            TEXT,
        note                 TEXT,
        created_at           TEXT NOT NULL,
        updated_at           TEXT NOT NULL,
        paid_at              TEXT,
        refunded_at          TEXT
    );
    CREATE INDEX orders_session ON orders(session_id);
    CREATE UNIQUE INDEX orders_provider_order ON orders(provider, provider_order_id);

    CREATE TABLE webhook_events (
        event_id     TEXT PRIMARY KEY,
        provider     TEXT NOT NULL,
        type         TEXT NOT NULL,
        order_id     TEXT,
        outcome      TEXT NOT NULL,
        received_at  TEXT NOT NULL
    );

    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def data_dir() -> Path:
    return Path(os.environ.get("AGLC_DATA_DIR") or Path.home() / ".aglc")


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            self._migrate(conn)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)  # we BEGIN ourselves
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for i, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in filter(str.strip, sql.split(";")):
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {i}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """A write transaction: BEGIN IMMEDIATE so concurrent writers queue instead of failing."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()

    # ---- meta --------------------------------------------------------------- #

    def secret(self, key: str) -> str:
        """A random value created on first use and kept, eg the IP hashing salt."""
        with self.transaction() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            if row:
                return row["value"]
            value = secrets.token_hex(32)
            conn.execute("INSERT INTO meta (key, value) VALUES (?, ?)", (key, value))
            return value

    # ---- documents ---------------------------------------------------------- #

    def add_document(self, session_id: str, filename: str, *, ip_hash: str | None, anon_id: str | None) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO documents (session_id, filename, ip_hash, anon_id, day, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, filename, ip_hash, anon_id, today(), now()),
            )

    def finish_document(self, session_id: str, *, status: str, footnote_count: int = 0) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE documents SET status = ?, footnote_count = ? WHERE session_id = ?",
                (status, footnote_count, session_id),
            )

    def document(self, session_id: str) -> sqlite3.Row | None:
        with self.read() as conn:
            return conn.execute("SELECT * FROM documents WHERE session_id = ?", (session_id,)).fetchone()

    def free_uses_today(self, *, ip_hash: str | None, anon_id: str | None) -> tuple[int, int, int]:
        """Documents processed today and not paid for: (by this IP, by this browser, by everyone).
        A run that failed doesn't count against the person, but does against the global cap."""
        with self.read() as conn:
            def count(where: str, *args) -> int:
                sql = f"SELECT COUNT(*) FROM documents WHERE day = ? AND unlocked_at IS NULL AND {where}"
                return conn.execute(sql, (today(), *args)).fetchone()[0]

            return (
                count("ip_hash = ? AND status != 'failed'", ip_hash) if ip_hash else 0,
                count("anon_id = ? AND status != 'failed'", anon_id) if anon_id else 0,
                count("1"),
            )

    # ---- orders ------------------------------------------------------------- #

    def add_order(self, order_id: str, session_id: str, *, product: str, amount: int, currency: str, provider: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO orders (id, session_id, product, amount, currency, provider, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, session_id, product, amount, currency, provider, now(), now()),
            )

    def update_order(self, order_id: str, conn: sqlite3.Connection | None = None, **fields) -> None:
        fields["updated_at"] = now()
        sql = f"UPDATE orders SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?"
        if conn is not None:
            conn.execute(sql, (*fields.values(), order_id))
            return
        with self.transaction() as c:
            c.execute(sql, (*fields.values(), order_id))

    def order(self, order_id: str) -> sqlite3.Row | None:
        with self.read() as conn:
            return conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()

    def orders_for(self, session_id: str) -> list[sqlite3.Row]:
        with self.read() as conn:
            return conn.execute(
                "SELECT * FROM orders WHERE session_id = ? ORDER BY created_at DESC, rowid DESC", (session_id,)
            ).fetchall()


_stores: dict[Path, Store] = {}
_lock = threading.Lock()


def get_store() -> Store:
    """The store for the current $AGLC_DATA_DIR (opened, and migrated, once)."""
    path = data_dir() / "aglc.db"
    with _lock:
        if path not in _stores:
            _stores[path] = Store(path)
        return _stores[path]
