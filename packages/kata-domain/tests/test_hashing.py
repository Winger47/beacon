"""Property + unit tests for finding hash computation (project.md 3.7.2, ADR-0011).

The properties are the contract DefectDojo learned the hard way: normalization is idempotent,
dict field order is irrelevant, and case/whitespace variants hash identically. If any of these
break, dedup silently splits or merges findings.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from kata_domain import hashing

_FIELDS = ["title", "component_name", "component_version"]

# Text that may contain the whitespace/case variation we normalize away.
_text = st.text(max_size=40)


@given(_text)
def test_norm_is_idempotent(value: str) -> None:
    once = hashing._norm(value)
    assert hashing._norm(once) == once


@given(_text, _text, _text)
def test_dict_order_does_not_matter(a: str, b: str, c: str) -> None:
    f1 = {"title": a, "component_name": b, "component_version": c}
    f2 = {"component_version": c, "title": a, "component_name": b}
    assert hashing.compute_hash_code(f1, _FIELDS) == hashing.compute_hash_code(f2, _FIELDS)


@given(_text)
def test_case_and_whitespace_variants_collide(value: str) -> None:
    base = {"title": value, "component_name": "x", "component_version": "1"}
    noisy = {"title": f"  {value.upper()}  ", "component_name": "x", "component_version": "1"}
    # Only differences are case/leading-trailing ws, which _norm removes.
    assert hashing.compute_hash_code(base, _FIELDS) == hashing.compute_hash_code(noisy, _FIELDS)


@given(st.lists(_text, max_size=5))
def test_list_order_does_not_matter(items: list[str]) -> None:
    f1 = {"title": "t", "component_name": "c", "component_version": "1", "vuln_ids": items}
    f2 = {"title": "t", "component_name": "c", "component_version": "1",
          "vuln_ids": list(reversed(items))}
    fields = ["title", "vuln_ids"]
    assert hashing.compute_hash_code(f1, fields) == hashing.compute_hash_code(f2, fields)


def test_field_names_embedded_prevent_value_swap_collision() -> None:
    # Swapping values between two fields must NOT collide (names are in the hashed string).
    f1 = {"title": "a", "component_name": "b", "component_version": "1"}
    f2 = {"title": "b", "component_name": "a", "component_version": "1"}
    assert hashing.compute_hash_code(f1, _FIELDS) != hashing.compute_hash_code(f2, _FIELDS)


def test_none_and_empty_hash_identically() -> None:
    f1 = {"title": "t", "component_name": None, "component_version": ""}
    f2 = {"title": "t", "component_name": "", "component_version": None}
    assert hashing.compute_hash_code(f1, _FIELDS) == hashing.compute_hash_code(f2, _FIELDS)


def test_always_fields_namespace_two_scanners_apart() -> None:
    f = {"title": "t", "component_name": "c", "component_version": "1", "scanner_key": "trivy"}
    g = {"title": "t", "component_name": "c", "component_version": "1", "scanner_key": "grype"}
    assert hashing.compute_hash_code(f, _FIELDS) != hashing.compute_hash_code(g, _FIELDS)
    # ...but with always=() (cross-tool key) they match.
    assert hashing.compute_hash_code(f, _FIELDS, always=()) == hashing.compute_hash_code(
        g, _FIELDS, always=()
    )


# --- match_key ---------------------------------------------------------------
def test_match_key_uid() -> None:
    assert hashing.match_key(
        algorithm=hashing.ALGO_UID, unique_id_from_tool="U-1", hash_code="deadbeef"
    ) == "U-1"


def test_match_key_hash() -> None:
    assert hashing.match_key(
        algorithm=hashing.ALGO_HASH, unique_id_from_tool="U-1", hash_code="deadbeef"
    ) == "deadbeef"


def test_match_key_uid_or_hash_prefers_uid_then_falls_back() -> None:
    assert hashing.match_key(
        algorithm=hashing.ALGO_UID_OR_HASH, unique_id_from_tool="U-1", hash_code="h"
    ) == "U-1"
    assert hashing.match_key(
        algorithm=hashing.ALGO_UID_OR_HASH, unique_id_from_tool="", hash_code="h"
    ) == "h"


def test_match_key_empty_raises() -> None:
    with pytest.raises(ValueError):
        hashing.match_key(algorithm=hashing.ALGO_UID, unique_id_from_tool="", hash_code="h")


def test_match_key_unknown_algorithm_raises() -> None:
    with pytest.raises(ValueError):
        hashing.match_key(algorithm="legacy", unique_id_from_tool="x", hash_code="h")
