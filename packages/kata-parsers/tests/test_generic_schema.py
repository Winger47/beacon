"""The Kata Generic v1 format has a published JSON Schema (project.md Phase 2 task).

These tests pin the contract: the sample fixture must validate, the schema must reject the
documented violations, and whatever the schema accepts the streaming parser must also accept.
The parser never loads a whole report; validation here is for small, trusted conformance
documents only.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import jsonschema
import pytest

from kata_parsers import generic_schema
from kata_parsers.generic import GenericJsonParser

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict[str, object]:
    data: dict[str, object] = json.loads((FIXTURES / name).read_text())
    return data


def test_schema_is_valid_draft() -> None:
    schema = generic_schema()
    # Raises SchemaError if the schema itself is malformed against its declared dialect.
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$id"].endswith("kata-generic-v1.schema.json")  # type: ignore[attr-defined]


def test_sample_fixture_validates() -> None:
    jsonschema.validate(_load("generic_sample.json"), generic_schema())


def test_schema_accepts_minimal_finding() -> None:
    jsonschema.validate({"findings": [{"title": "x"}]}, generic_schema())


@pytest.mark.parametrize(
    "doc",
    [
        {"findings": [{"severity": "high"}]},  # missing required title
        {"findings": [{"title": "x", "cvss_v3_score": 42}]},  # score out of range
        {"findings": [{"title": "x", "vuln_ids": [1, 2]}]},  # vuln_ids must be strings
        {"findings": [{"title": "x", "locations": [{"foo": "bar"}]}]},  # location needs kind
        {"schema": "kata-generic-v2", "findings": []},  # wrong schema literal
        {"not_findings": []},  # missing findings
    ],
)
def test_schema_rejects_bad_documents(doc: dict[str, object]) -> None:
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, generic_schema())


def test_schema_accepted_doc_is_parseable() -> None:
    """Contract coherence: a schema-valid document parses without raising."""
    doc = {
        "schema": "kata-generic-v1",
        "findings": [
            {"title": "a", "severity": "low"},
            {"title": "b", "severity": "critical", "vuln_ids": ["CVE-2026-1"], "cwe": 79},
        ],
    }
    jsonschema.validate(doc, generic_schema())
    findings = list(GenericJsonParser().parse(io.BytesIO(json.dumps(doc).encode())))
    assert [f.title for f in findings] == ["a", "b"]
    assert findings[1].severity.label == "critical"
