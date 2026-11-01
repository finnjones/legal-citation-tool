"""SQLite store for paid use (only touched when AGLC_PAYMENTS is set).

One file, `$AGLC_DATA_DIR/aglc.db`, in WAL mode so the web workers can read while a
webhook writes. The schema is versioned with `PRAGMA user_version`: append a migration
to MIGRATIONS, never edit one that has shipped.

    documents       one row per processed upload; unlocked_at is set only with an entitlement
                    (entitlement_id), or by a re-scan of one
    orders          one row per checkout; status pending -> paid -> refunding -> refunded.
                    A document's order has its session id; a credit pack's may have none
    webhook_events  every webhook applied, keyed by the provider's event id (idempotency)
    credit_codes    one per credit pack bought: a hash of its redeem code, never the code,
                    and the credits left (aglc/credits.py)
    credit_ledger   every grant, spend and refund of credits, with the document a spend
                    unlocked and the pack's payment id
    code_pickup     a new pack's code, held only until the buyer's browser confirms it has it
                    (or the retention window ends); only that browser can collect it
    fingerprints    keyed hashes of each upload's footnotes (aglc/fingerprint.py), never the
                    text; kept $AGLC_FINGERPRINT_DAYS
    fingerprint_index  footnote hash -> session, for free previews only: finds an essay
                    that has had its free preview already
    entitlements    one per document paid for (by card or credits): its tier, the paid
                    document's fingerprint, a hashed re-scan token and the free re-scans
                    left until expires_at (aglc/billing.py)
    meta            small settings, eg the salt for hashing IP addresses
"""

from __future__ import annotations

import json
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
    # 2: free re-runs of footnotes the model failed to read
    """
    ALTER TABLE documents ADD COLUMN reruns INTEGER NOT NULL DEFAULT 0;
    """,
    # 3: retention (aglc/retention.py): when a document's files were deleted
    """
    ALTER TABLE documents ADD COLUMN purged_at TEXT;
    CREATE INDEX documents_created ON documents(created_at);
    """,
    # 4: credit packs. orders.session_id may be NULL (a pack bought on its own), which
    # SQLite can only allow by rebuilding the table (same columns, same order).
    """
    CREATE TABLE orders_new (
        id                   TEXT PRIMARY KEY,
        session_id           TEXT REFERENCES documents(session_id),
        product              TEXT NOT NULL,
        amount               INTEGER NOT NULL,
        currency             TEXT NOT NULL,
        provider             TEXT NOT NULL,
        status               TEXT NOT NULL DEFAULT 'pending',
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
    INSERT INTO orders_new SELECT * FROM orders;
    DROP TABLE orders;
    ALTER TABLE orders_new RENAME TO orders;
    CREATE INDEX orders_session ON orders(session_id);
    CREATE UNIQUE INDEX orders_provider_order ON orders(provider, provider_order_id);

    CREATE TABLE credit_codes (
        id                 TEXT PRIMARY KEY,
        code_hash          TEXT NOT NULL UNIQUE,
        order_id           TEXT NOT NULL UNIQUE REFERENCES orders(id),  -- one code per pack
        credits_total      INTEGER NOT NULL,
        credits_remaining  INTEGER NOT NULL CHECK (credits_remaining >= 0),
        created_at         TEXT NOT NULL,
        revoked_at         TEXT                                         -- the pack was refunded
    );

    CREATE TABLE credit_ledger (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        code_id     TEXT NOT NULL REFERENCES credit_codes(id),
        delta       INTEGER NOT NULL,          -- + grant, - spend or refund
        reason      TEXT NOT NULL,             -- grant | spend | refund | return
        session_id  TEXT,                      -- the document a spend unlocked
        order_id    TEXT,                      -- the pack's order
        payment_id  TEXT,                      -- the pack's payment
        created_at  TEXT NOT NULL
    );
    CREATE INDEX credit_ledger_code ON credit_ledger(code_id);

    CREATE TABLE code_pickup (
        order_id    TEXT PRIMARY KEY REFERENCES orders(id),
        code        TEXT NOT NULL,
        emailed     INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT NOT NULL
    );
    """,
    # 5: fingerprints, and documents that were refused a second free preview ("seen")
    """
    ALTER TABLE documents ADD COLUMN kind TEXT NOT NULL DEFAULT 'free';  -- free | seen
    ALTER TABLE documents ADD COLUMN seen_of TEXT;                       -- the earlier preview it matched

    CREATE TABLE fingerprints (
        session_id  TEXT PRIMARY KEY,
        doc_hash    TEXT NOT NULL,
        hashes      TEXT NOT NULL,             -- JSON list of the counted footnotes' hashes
        indexed     INTEGER NOT NULL DEFAULT 0, -- in fingerprint_index: a free preview
        created_at  TEXT NOT NULL
    );
    CREATE INDEX fingerprints_created ON fingerprints(created_at);

    CREATE TABLE fingerprint_index (
        hash        TEXT NOT NULL,
        session_id  TEXT NOT NULL,
        PRIMARY KEY (hash, session_id)
    ) WITHOUT ROWID;
    CREATE INDEX fingerprint_index_session ON fingerprint_index(session_id);
    """,
    # 6: entitlements (a paid document's record, with its free re-scans). Documents paid for
    # before this get one each, with no fingerprint or token yet (both are filled in on demand).
    """
    CREATE TABLE entitlements (
        id                 TEXT PRIMARY KEY,
        session_id         TEXT NOT NULL UNIQUE REFERENCES documents(session_id),
        tier               TEXT NOT NULL,          -- essay | long
        source             TEXT NOT NULL,          -- the order id, or credit:<code id>
        fingerprint        TEXT,                   -- JSON: per paid footnote, its hashes as written and as corrected
        token_hash         TEXT UNIQUE,            -- the re-scan token's SHA-256, NULL until one is made
        rescans_remaining  INTEGER NOT NULL CHECK (rescans_remaining >= 0),
        paid_at            TEXT NOT NULL,
        expires_at         TEXT NOT NULL,          -- re-scans end
        revoked_at         TEXT                    -- refunded
    );
    ALTER TABLE documents ADD COLUMN entitlement_id TEXT;
    INSERT INTO entitlements (id, session_id, tier, source, rescans_remaining, paid_at, expires_at)
        SELECT lower(hex(randomblob(16))), session_id,
               CASE WHEN footnote_count > 150 THEN 'long' ELSE 'essay' END,
               COALESCE(unlocked_by, 'legacy'), 3, unlocked_at,
               strftime('%Y-%m-%dT%H:%M:%S+00:00', unlocked_at, '+14 days')
        FROM documents WHERE unlocked_at IS NOT NULL;
    UPDATE documents SET entitlement_id =
        (SELECT e.id FROM entitlements e WHERE e.session_id = documents.session_id)
        WHERE unlocked_at IS NOT NULL
    """,
    # 7: a seen upload is shown the earlier preview only if the same browser made it
    """
    ALTER TABLE documents ADD COLUMN seen_shown INTEGER NOT NULL DEFAULT 0
    """,
    # 8: a pack's code is given only to the browser that bought it (its aglc_anon cookie)
    """
    ALTER TABLE orders ADD COLUMN buyer_anon TEXT;
    CREATE INDEX orders_buyer ON orders(buyer_anon, created_at)
    """,
]

# A document whose retention window (see aglc/retention.py) ended before :cutoff: uploaded,
# paid for (if it was) and last sent to a still-pending checkout all before then.
_EXPIRED = """
    d.purged_at IS NULL AND d.created_at < :cutoff
    AND (d.unlocked_at IS NULL OR d.unlocked_at < :cutoff)
    AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.session_id = d.session_id
                    AND o.status = 'pending' AND o.updated_at >= :cutoff)
"""


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
        conn.execute("PRAGMA secure_delete=ON")  # deleted rows (eg a collected pack code) are overwritten
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

    def add_document(self, session_id: str, filename: str, *, ip_hash: str | None, anon_id: str | None,
                     limits: tuple[int, int, int] | None = None, footnote_count: int = 0, kind: str = "free",
                     status: str = "processing", seen_of: str | None = None, seen_shown: bool = False) -> str | None:
        """Record a document. With `limits` (per IP, per browser, global), only while today's
        free uses are under them: the count and the insert are one transaction, so two
        uploads at once can't both take the last free run. Returns the limit that refused it
        ('global' or 'visitor'), or None when recorded."""
        with self.transaction() as conn:
            if limits is not None:
                per_ip, per_browser, global_cap = limits
                by_ip, by_browser, total = self._free_uses(conn, ip_hash=ip_hash, anon_id=anon_id)
                if total >= global_cap:
                    return "global"
                if by_browser >= per_browser or by_ip >= per_ip:
                    return "visitor"
            conn.execute(
                "INSERT INTO documents (session_id, filename, ip_hash, anon_id, day, created_at, footnote_count, kind,"
                " status, seen_of, seen_shown) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, filename, ip_hash, anon_id, today(), now(), footnote_count, kind, status, seen_of,
                 int(seen_shown)),
            )
        return None

    def finish_document(self, session_id: str, *, status: str, footnote_count: int = 0) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE documents SET status = ?, footnote_count = ? WHERE session_id = ?",
                (status, footnote_count, session_id),
            )

    def claim_rerun(self, session_id: str, limit: int) -> bool:
        """Use one of the document's free re-runs; False when they are used up."""
        with self.transaction() as conn:
            return conn.execute(
                "UPDATE documents SET reruns = reruns + 1 WHERE session_id = ? AND reruns < ?", (session_id, limit)
            ).rowcount == 1

    def document(self, session_id: str) -> sqlite3.Row | None:
        with self.read() as conn:
            return conn.execute("SELECT * FROM documents WHERE session_id = ?", (session_id,)).fetchone()

    def purged_states(self, session_ids: list[str]) -> dict[str, bool]:
        """{session id: whether it was purged} for those of `session_ids` with a row."""
        states: dict[str, bool] = {}
        with self.read() as conn:
            for i in range(0, len(session_ids), 500):  # SQLite's limit on query parameters
                chunk = session_ids[i : i + 500]
                rows = conn.execute(
                    f"SELECT session_id, purged_at FROM documents WHERE session_id IN ({','.join('?' * len(chunk))})",
                    chunk,
                ).fetchall()
                states.update({r["session_id"]: bool(r["purged_at"]) for r in rows})
        return states

    def expired_documents(self, cutoff: str) -> list[tuple[str, bool]]:
        """(session id, has an old pending order) for each document past its window."""
        with self.read() as conn:
            rows = conn.execute(
                f"SELECT d.session_id, EXISTS (SELECT 1 FROM orders o WHERE o.session_id = d.session_id"
                f" AND o.status = 'pending') AS pending FROM documents d WHERE {_EXPIRED}",
                {"cutoff": cutoff},
            ).fetchall()
        return [(r["session_id"], bool(r["pending"])) for r in rows]

    def purge_document(self, session_id: str, cutoff: str) -> bool:
        """Mark a document deleted (and forget its filename) if it is still past its window,
        checked in the same transaction a webhook would unlock it in. True if marked."""
        with self.transaction() as conn:
            return conn.execute(
                "UPDATE documents AS d SET purged_at = :now, filename = '',"
                # who processed it isn't needed once it's gone; today's rows still count for quotas
                " anon_id = CASE WHEN d.day < :today THEN NULL ELSE d.anon_id END,"
                " ip_hash = CASE WHEN d.day < :today THEN NULL ELSE d.ip_hash END"
                f" WHERE d.session_id = :sid AND {_EXPIRED}",
                {"now": now(), "sid": session_id, "cutoff": cutoff, "today": today()},
            ).rowcount == 1

    def free_uses_today(self, *, ip_hash: str | None, anon_id: str | None) -> tuple[int, int, int]:
        """Documents processed today and not paid for: (by this IP, by this browser, by everyone).
        A run that failed doesn't count against the person, but does against the global cap."""
        with self.read() as conn:
            return self._free_uses(conn, ip_hash=ip_hash, anon_id=anon_id)

    @staticmethod
    def _free_uses(conn: sqlite3.Connection, *, ip_hash: str | None, anon_id: str | None) -> tuple[int, int, int]:
        def count(where: str, *args) -> int:
            # A re-scan is paid for (and one that failed is given back), so never a free use. A
            # "seen" upload runs no model but is one, so the check can't be used as a lookup service.
            sql = f"SELECT COUNT(*) FROM documents WHERE day = ? AND unlocked_at IS NULL AND kind != 'rescan' AND {where}"
            return conn.execute(sql, (today(), *args)).fetchone()[0]

        return (
            count("ip_hash = ? AND status != 'failed'", ip_hash) if ip_hash else 0,
            count("anon_id = ? AND status != 'failed'", anon_id) if anon_id else 0,
            count("1"),
        )

    def set_status(self, session_id: str, status: str, *, expect: str | None = None) -> bool:
        """Set a document's status (only if it is `expect`, when given); True if it was set."""
        with self.transaction() as conn:
            if expect is None:
                return conn.execute("UPDATE documents SET status = ? WHERE session_id = ?",
                                    (status, session_id)).rowcount == 1
            return conn.execute("UPDATE documents SET status = ? WHERE session_id = ? AND status = ?",
                                (status, session_id, expect)).rowcount == 1

    # ---- fingerprints -------------------------------------------------------- #

    def add_fingerprint(self, session_id: str, doc_hash: str, hashes: tuple[str, ...]) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO fingerprints (session_id, doc_hash, hashes, indexed, created_at)"
                " VALUES (?, ?, ?, 0, ?)",
                (session_id, doc_hash, json.dumps(list(hashes)), now()),
            )

    def fingerprint(self, session_id: str) -> tuple[str, ...] | None:
        with self.read() as conn:
            row = conn.execute("SELECT hashes FROM fingerprints WHERE session_id = ?", (session_id,)).fetchone()
        return tuple(json.loads(row["hashes"])) if row else None

    def index_fingerprint(self, session_id: str) -> None:
        """Make a free preview's fingerprint findable by later uploads (once)."""
        with self.transaction() as conn:
            row = conn.execute("SELECT hashes FROM fingerprints WHERE session_id = ? AND indexed = 0",
                               (session_id,)).fetchone()
            if row is None:
                return
            conn.executemany("INSERT OR IGNORE INTO fingerprint_index (hash, session_id) VALUES (?, ?)",
                             [(h, session_id) for h in json.loads(row["hashes"])])
            conn.execute("UPDATE fingerprints SET indexed = 1 WHERE session_id = ?", (session_id,))

    def fingerprint_candidates(self, hashes: tuple[str, ...], at_least: int, limit: int = 50) -> list[tuple[str, int]]:
        """Indexed (free preview) sessions sharing at least `at_least` of `hashes`, as
        (session id, how many), most shared first, then newest first. One query, the hashes
        passed as a single JSON parameter and the threshold applied in SQL, so a citation
        common to many essays can't hit SQLite's limit on parameters or slow an upload."""
        with self.read() as conn:
            rows = conn.execute(
                "SELECT fi.session_id, COUNT(*) AS n, MAX(f.created_at) AS created"
                " FROM json_each(?) AS up JOIN fingerprint_index AS fi ON fi.hash = up.value"
                " JOIN fingerprints AS f ON f.session_id = fi.session_id"
                " GROUP BY fi.session_id HAVING COUNT(*) >= ? ORDER BY n DESC, created DESC LIMIT ?",
                (json.dumps(list(dict.fromkeys(hashes))), at_least, limit),
            ).fetchall()
        return [(r["session_id"], r["n"]) for r in rows]

    def end_rescans(self, at: str) -> int:
        """Forget the fingerprint and re-scan token of entitlements whose re-scans have ended
        (expired or refunded) by `at`; the rest of the record stays with the order."""
        with self.transaction() as conn:
            return conn.execute(
                "UPDATE entitlements SET fingerprint = NULL, token_hash = NULL"
                " WHERE (expires_at < ? OR revoked_at IS NOT NULL) AND (fingerprint IS NOT NULL OR token_hash IS NOT NULL)",
                (at,),
            ).rowcount

    def purge_fingerprints(self, cutoff: str) -> int:
        """Delete fingerprints made before `cutoff` (the retention sweep)."""
        with self.transaction() as conn:
            conn.execute("DELETE FROM fingerprint_index WHERE session_id IN"
                         " (SELECT session_id FROM fingerprints WHERE created_at < ?)", (cutoff,))
            return conn.execute("DELETE FROM fingerprints WHERE created_at < ?", (cutoff,)).rowcount

    # ---- orders ------------------------------------------------------------- #

    def add_order(self, order_id: str, session_id: str | None, *, product: str, amount: int, currency: str,
                  provider: str, buyer_anon: str | None = None) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO orders (id, session_id, product, amount, currency, provider, created_at, updated_at,"
                " buyer_anon) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (order_id, session_id, product, amount, currency, provider, now(), now(), buyer_anon),
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

    def latest_pack_order(self, buyer_anon: str) -> sqlite3.Row | None:
        """This browser's credit pack: the newest with a code waiting to be collected, else
        the newest paid, else the newest (an abandoned checkout is never preferred)."""
        with self.read() as conn:
            return conn.execute(
                "SELECT o.* FROM orders o WHERE o.buyer_anon = ? AND o.product LIKE 'pack%'"
                " ORDER BY EXISTS (SELECT 1 FROM code_pickup p WHERE p.order_id = o.id) DESC,"
                " o.status = 'paid' DESC, o.created_at DESC, o.rowid DESC LIMIT 1", (buyer_anon,),
            ).fetchone()

    def purge_pickups(self, cutoff: str) -> int:
        """Forget pack codes nobody collected before `cutoff` (the retention sweep)."""
        with self.transaction() as conn:
            deleted = conn.execute("DELETE FROM code_pickup WHERE created_at < ?", (cutoff,)).rowcount
        if deleted:
            self.scrub_wal()
        return deleted

    def scrub_wal(self) -> None:
        """Copy the write-ahead log into the database and empty it, so a deleted secret (with
        secure_delete on) is left in neither file. Best effort: readers can hold it back."""
        with self.read() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

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
