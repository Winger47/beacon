"""Finding hash computation and match-key derivation (project.md 3.7.2, ADR-0011).

A finding's dedup identity is either the scanner's own unique id or a SHA-256 ``hash_code``
over a per-scanner field list (``scanner_config.hash_fields``), plus an always-included set.
``match_key`` collapses the configured algorithm down to the single string the reconciler and
reimport diff compare on (so the hot path is a plain index lookup, not a CASE expression).

This module is pure and has no DB or ORM dependency: callers pass a field mapping. Keeping it
side-effect free is what makes it cheap to property-test (idempotent normalization, order and
whitespace invariance) — see tests/test_hashing.py.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence

_WS = re.compile(r"\s+")

# Appended to every same-tool hash so two tools never share a hash namespace. Cross-tool
# dedup uses a separate, scanner-independent key (see compute_hash_code(always=())).
ALWAYS_FIELDS: tuple[str, ...] = ("scanner_key",)

# The three dedup algorithms Kata implements (skip DefectDojo's `legacy`).
ALGO_UID = "unique_id_from_tool"
ALGO_HASH = "hash_code"
ALGO_UID_OR_HASH = "unique_id_from_tool_or_hash_code"
VALID_ALGORITHMS = frozenset({ALGO_UID, ALGO_HASH, ALGO_UID_OR_HASH})


def _norm(value: object) -> str:
    """Normalize one value for hashing: lists sort, everything trims/lowercases/collapses ws.

    Idempotent: ``_norm(_norm(x)) == _norm(x)``. ``None`` and empty collections both map to
    ``""`` so a missing field and a blank field hash identically.
    """
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set, frozenset)):
        return ",".join(sorted(_norm(v) for v in value))
    # casefold(), not lower(): lower() is not round-trip stable in Unicode (e.g. 'µ' U+00B5
    # vs 'μ' U+03BC after .upper().lower()), which would split one finding into two hashes.
    text = str(value).strip().casefold()
    return _WS.sub(" ", text)


def compute_hash_code(
    fields: Mapping[str, object],
    field_names: Sequence[str],
    always: Sequence[str] = ALWAYS_FIELDS,
) -> str:
    """SHA-256 over ``field=value`` parts for ``field_names`` then ``always`` (in order).

    Field names are embedded in the hashed string so swapping values between two fields
    cannot collide. ``field_names`` order is preserved as given (dedup config is ordered);
    list *values* are sorted inside ``_norm`` so scanner output order does not matter.
    """
    parts = [f"{name}={_norm(fields.get(name))}" for name in (*field_names, *always)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def match_key(
    *,
    algorithm: str,
    unique_id_from_tool: str | None,
    hash_code: str | None,
) -> str:
    """The single string two findings are compared on, per the scanner's algorithm.

    - ``unique_id_from_tool``: the tool's id (endpoints ignored).
    - ``hash_code``: the computed hash.
    - ``unique_id_from_tool_or_hash_code``: the id if present, else the hash (the COALESCE in
      project.md 3.7.4).

    Raises ``ValueError`` for an unknown algorithm or when the chosen source is empty (a
    finding with no usable key is a bug upstream, not something to silently bucket together).
    """
    uid = (unique_id_from_tool or "").strip()
    h = (hash_code or "").strip()
    if algorithm == ALGO_UID:
        key = uid
    elif algorithm == ALGO_HASH:
        key = h
    elif algorithm == ALGO_UID_OR_HASH:
        key = uid or h
    else:
        raise ValueError(f"unknown dedup algorithm: {algorithm!r}")
    if not key:
        raise ValueError(
            f"empty match key for algorithm {algorithm!r} "
            f"(uid={uid!r}, hash={'set' if h else 'empty'})"
        )
    return key
