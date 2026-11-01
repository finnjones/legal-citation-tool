"""Fingerprints of a document's footnotes, so the free preview can't be had twice for one
essay (aglc/billing.py) and a paid document can be re-scanned when it is revised.

Each footnote's text is normalised (Unicode NFKC, lower case, curly quotes and dashes made
plain, then all punctuation dropped and whitespace collapsed) and hashed with HMAC-SHA256
under a random key kept in the database (`meta.fingerprint_key`). Only the hashes are kept,
never the text, and without the key they can't be checked against a guessed footnote. A
whole-document hash covers every footnote in order.

Footnotes too common to tell essays apart don't count for matching: anything under
MIN_CHARS once normalised, a bare Ibid (with or without a pinpoint) and a bare subsequent
reference such as "Mabo (n 1) 60" or "Mabo, above n 1, 60".

Two documents match when enough of the *new* document's counted footnotes appear in the
earlier one: at least `share` of them (containment of the new set, not Jaccard, so cutting
footnotes out of an essay still matches it) and at least MIN_MATCHES of them, so short
documents with a few common citations don't collide. A document with fewer than
MIN_MATCHES counted footnotes never matches anything.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import unicodedata
from dataclasses import dataclass

MIN_CHARS = 12
MIN_MATCHES = 5
DEFAULT_SEEN_OVERLAP = 0.6  # $AGLC_SEEN_OVERLAP: a free upload this like an earlier preview is "seen"
DEFAULT_DAYS = 180  # $AGLC_FINGERPRINT_DAYS: how long fingerprints are kept

_QUOTES = str.maketrans({c: "'" for c in "‘’‚‛′`´"} | {c: '"' for c in "“”„‟″"}
                        | {c: "-" for c in "‐‑‒–—―−"})
_IBID = re.compile(r"^ibid\b[\w ]{0,30}$")
_SHORT_REF = re.compile(r"^(?:see |see also |cf )?(?:[\w ]{0,40} )?(?:above )?n \d+(?: (?:at )?[\d ]+)?(?: per [\w ]+)?$")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").translate(_QUOTES).lower()
    text = re.sub(r"[^\w\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def counts(normalised: str) -> bool:
    """Whether a normalised footnote is distinctive enough to count for matching."""
    return len(normalised) >= MIN_CHARS and not _IBID.match(normalised) and not _SHORT_REF.match(normalised)


@dataclass(frozen=True)
class Fingerprint:
    doc_hash: str
    hashes: tuple[str, ...]  # the counted footnotes' hashes, each once, in document order


def _mac(key: str, text: str) -> str:
    return hmac.new(key.encode(), text.encode(), hashlib.sha256).hexdigest()[:32]


def compute(texts: list[str], key: str) -> Fingerprint:
    """The fingerprint of a document whose footnotes read `texts`."""
    normalised = [normalise(t) for t in texts]
    hashes = dict.fromkeys(_mac(key, n) for n in normalised if counts(n))
    return Fingerprint(doc_hash=_mac(key, "\n".join(normalised)), hashes=tuple(hashes))


def overlap(new: set[str] | tuple[str, ...], earlier: set[str] | tuple[str, ...]) -> tuple[int, float]:
    """(how many of `new`'s hashes are in `earlier`, as a share of `new`)."""
    new, earlier = set(new), set(earlier)
    matches = len(new & earlier)
    return matches, (matches / len(new) if new else 0.0)


def matches(new, earlier, share: float) -> bool:
    found, fraction = overlap(new, earlier)
    return share > 0 and found >= MIN_MATCHES and fraction >= share


def footnote_hash(text: str, key: str) -> str | None:
    """One footnote's hash, or None if it doesn't count for matching."""
    normalised = normalise(text)
    return _mac(key, normalised) if counts(normalised) else None


NEW_SHARE = 0.5  # a revision may add at most this share of the paid document's footnotes


def is_revision(new, paid: list[list[str]], share: float) -> bool:
    """Whether an upload (its counted hashes) is a revision of a paid document, given as one
    group of hashes per counted footnote (as written, and as corrected). Both ways round, so
    a few of its footnotes can't stand in for the essay, nor the essay for a new one:
    - at least `share` of the upload's footnotes, and MIN_MATCHES, are the paid document's;
    - at least `share` of the paid document's footnotes are in the upload;
    - it adds no more than NEW_SHARE as many new footnotes as the paid document had."""
    new, groups = set(new), [set(g) for g in paid if g]
    if share <= 0 or not new or not groups:
        return False
    known = set().union(*groups)
    found = len(new & known)
    present = sum(1 for g in groups if g & new)
    return (found >= MIN_MATCHES and found / len(new) >= share and present / len(groups) >= share
            and len(new) - found <= NEW_SHARE * len(groups))


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def seen_overlap() -> float:
    """$AGLC_SEEN_OVERLAP (default 0.6); 0 turns the seen-essay check off."""
    return min(1.0, max(0.0, _float_env("AGLC_SEEN_OVERLAP", DEFAULT_SEEN_OVERLAP)))


def keep_days() -> float:
    """$AGLC_FINGERPRINT_DAYS (default 180, at least 1)."""
    return max(1.0, _float_env("AGLC_FINGERPRINT_DAYS", DEFAULT_DAYS))
