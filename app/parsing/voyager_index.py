"""Index and resolve LinkedIn Voyager normalized JSON references."""

from __future__ import annotations

from typing import Any


def build_included_index(included: list[Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entry in included:
        if not isinstance(entry, dict):
            continue
        urn = entry.get("entityUrn")
        if isinstance(urn, str):
            index[urn] = entry
    return index


def resolve_ref(index: dict[str, dict[str, Any]], ref: Any) -> dict[str, Any] | None:
    if isinstance(ref, str) and ref in index:
        return index[ref]
    return None


def resolve_entry_ref(
    index: dict[str, dict[str, Any]],
    entry: dict[str, Any],
    *keys: str,
) -> dict[str, Any] | None:
    for key in keys:
        target = resolve_ref(index, entry.get(key))
        if target is not None:
            return target
    return None
