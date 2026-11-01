"""Credit packs: redeem codes, and the credits on them (used by aglc/billing.py).

A pack is bought through the same checkout as a document. When its payment is applied,
`grant` makes a random code such as `AFC-7KQ4-M9TX-3HWD` (12 characters from an alphabet
with no 0/O, 1/I/L or U/V lookalikes: about 58 bits, far beyond guessing online) and stores
only its SHA-256 hash with the credits left. A single essay uses 1 credit, a long document
2 (billing.TIERS). Credits never expire.

Every change to a code's credits is one row in `credit_ledger`: the grant (with the pack's
payment id), each spend (with the document it unlocked), a refund of the pack (its unspent
credits removed) and a return (a spend given back because the document's files had gone).
`spend` is a single conditional UPDATE inside the caller's write transaction, so two spends
at once can't both take the last credit, and credits can't go below zero.

Codes are never logged.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import uuid

from .store import now

ALPHABET = "23456789ABCDEFGHJKMNPQRSTWXYZ"  # no 0 O 1 I L U V: easy to read out and type
GROUPS, GROUP_LEN = 3, 4
PREFIX = "AFC"
_CODE = re.compile(rf"^{PREFIX}[{ALPHABET}]{{{GROUPS * GROUP_LEN}}}$")


def new_code() -> str:
    """A random redeem code, eg AFC-7KQ4-M9TX-3HWD."""
    chars = "".join(secrets.choice(ALPHABET) for _ in range(GROUPS * GROUP_LEN))
    return "-".join([PREFIX, *(chars[i:i + GROUP_LEN] for i in range(0, len(chars), GROUP_LEN))])


def normalise(code: str) -> str | None:
    """The canonical form of a typed code (any case, spaces or dashes), or None if it can't
    be one of ours."""
    compact = re.sub(r"[\s\-–—_]", "", code or "").upper()
    if len(compact) == GROUPS * GROUP_LEN:  # typed without the AFC
        compact = PREFIX + compact
    return compact if _CODE.match(compact) else None


def code_hash(code: str) -> str | None:
    """What is stored for a code. A plain hash is enough: the code itself is random."""
    canonical = normalise(code)
    return hashlib.sha256(f"aforecite-code:{canonical}".encode()).hexdigest() if canonical else None


def grant(conn: sqlite3.Connection, *, order_id: str, credits: int, payment_id: str | None) -> tuple[str, str]:
    """Make a pack's code with `credits` on it, in the caller's transaction; returns
    (code id, the code). The code is returned once, here, and stored only as a hash."""
    code, code_id = new_code(), uuid.uuid4().hex
    conn.execute(
        "INSERT INTO credit_codes (id, code_hash, order_id, credits_total, credits_remaining, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (code_id, code_hash(code), order_id, credits, credits, now()),
    )
    _ledger(conn, code_id, credits, "grant", order_id=order_id, payment_id=payment_id)
    return code_id, code


def find(conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    """The code's row, or None if it isn't one of ours."""
    digest = code_hash(code)
    if digest is None:
        return None
    return conn.execute("SELECT * FROM credit_codes WHERE code_hash = ?", (digest,)).fetchone()


def spend(conn: sqlite3.Connection, code_id: str, cost: int, *, session_id: str) -> bool:
    """Take `cost` credits from the code for `session_id`, in the caller's transaction.
    False (and nothing taken) if it hasn't that many left or the pack was refunded."""
    taken = conn.execute(
        "UPDATE credit_codes SET credits_remaining = credits_remaining - ?"
        " WHERE id = ? AND credits_remaining >= ? AND revoked_at IS NULL",
        (cost, code_id, cost),
    ).rowcount == 1
    if taken:
        order = conn.execute("SELECT order_id FROM credit_codes WHERE id = ?", (code_id,)).fetchone()
        _ledger(conn, code_id, -cost, "spend", session_id=session_id, order_id=order["order_id"])
    return taken


def give_back(conn: sqlite3.Connection, code_id: str, session_id: str) -> int:
    """Return what was spent on `session_id` (its files had gone); returns how many."""
    spent = -(conn.execute(
        "SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE code_id = ? AND session_id = ?"
        " AND reason IN ('spend', 'return')", (code_id, session_id),
    ).fetchone()[0])
    if spent <= 0:
        return 0
    conn.execute("UPDATE credit_codes SET credits_remaining = credits_remaining + ? WHERE id = ? AND revoked_at IS NULL",
                 (spent, code_id))
    _ledger(conn, code_id, spent, "return", session_id=session_id)
    return spent


def revoke(conn: sqlite3.Connection, order_id: str, *, payment_id: str | None) -> int | None:
    """The pack was refunded: remove its unspent credits (documents already unlocked stay
    unlocked). Returns how many were removed, or None if the order has no code yet."""
    row = conn.execute("SELECT * FROM credit_codes WHERE order_id = ?", (order_id,)).fetchone()
    conn.execute("DELETE FROM code_pickup WHERE order_id = ?", (order_id,))
    if row is None:
        return None
    left = row["credits_remaining"]
    conn.execute("UPDATE credit_codes SET credits_remaining = 0, revoked_at = COALESCE(revoked_at, ?) WHERE id = ?",
                 (now(), row["id"]))
    if left:
        _ledger(conn, row["id"], -left, "refund", order_id=order_id, payment_id=payment_id)
    return left


def _ledger(conn: sqlite3.Connection, code_id: str, delta: int, reason: str, *, session_id: str | None = None,
            order_id: str | None = None, payment_id: str | None = None) -> None:
    conn.execute(
        "INSERT INTO credit_ledger (code_id, delta, reason, session_id, order_id, payment_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (code_id, delta, reason, session_id, order_id, payment_id, now()),
    )
