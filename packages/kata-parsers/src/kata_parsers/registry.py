"""Parser registry: map a scanner_key to its parser class."""

from __future__ import annotations

from .base import ParserError, ScannerParser

_REGISTRY: dict[str, type[ScannerParser]] = {}


def register(parser_cls: type[ScannerParser]) -> type[ScannerParser]:
    key = parser_cls.scanner_key
    if key in _REGISTRY:
        raise RuntimeError(f"duplicate parser registration: {key}")
    _REGISTRY[key] = parser_cls
    return parser_cls


def get_parser(scanner_key: str) -> ScannerParser:
    try:
        return _REGISTRY[scanner_key]()
    except KeyError:
        raise ParserError(f"unsupported scanner: {scanner_key}") from None


def registered_keys() -> list[str]:
    return sorted(_REGISTRY)
