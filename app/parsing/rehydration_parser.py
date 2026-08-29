"""Extract SDUI AsyncComponentRequest descriptors from rehydration blob."""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from app.models.schemas import AsyncSectionDescriptor
from app.parsing import selectors as sel

ASYNC_COMPONENT_TYPE = "proto.sdui.actions.core.AsyncComponentRequest"
ASYNC_COMPONENT_MARKER = f'"$type":"{ASYNC_COMPONENT_TYPE}"'
NEW_COMPONENT_ID_RE = re.compile(r'"newComponentId"\s*:\s*"([^"]+)"')
VIEWEE_PROFILE_ID_RE = re.compile(r'"vieweeProfileId"\s*:\s*"([^"]+)"')


def unescape_rehydration_blob(blob: str) -> str:
    """Unescape React Flight string literals in the rehydration script."""
    return blob.replace('\\"', '"').replace("\\\\", "\\")


def parse_rehydration(html: str) -> list[AsyncSectionDescriptor]:
    blob = _extract_rehydration_blob(html)
    if not blob:
        return []

    descriptors: list[AsyncSectionDescriptor] = []
    seen_ids: set[str] = set()

    for raw_obj in _find_async_component_objects(blob):
        descriptor = _parse_descriptor_object(raw_obj)
        if descriptor and descriptor.new_component_id not in seen_ids:
            seen_ids.add(descriptor.new_component_id)
            descriptors.append(descriptor)

    if not descriptors:
        descriptors = _fallback_scan(unescape_rehydration_blob(blob))

    return descriptors


def _extract_rehydration_blob(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    script = soup.select_one(sel.REHYDRATE_SCRIPT)
    if script and script.string:
        return _strip_rehydration_prefix(script.string)

    inline_match = re.search(
        r"window\.__como_rehydration__\s*=\s*(\[.*?\]);",
        html,
        re.DOTALL,
    )
    if inline_match:
        return inline_match.group(1)
    return ""


def _strip_rehydration_prefix(blob: str) -> str:
    text = blob.strip()
    if text.startswith("window.__como_rehydration__"):
        text = text.split("=", 1)[1].strip()
    if text.endswith(";"):
        text = text[:-1].strip()
    return text


def _find_async_component_objects(blob: str) -> list[str]:
    unescaped = unescape_rehydration_blob(blob)
    if ASYNC_COMPONENT_MARKER not in unescaped:
        return _find_legacy_async_objects(unescaped)

    objects: list[str] = []
    idx = 0
    while True:
        pos = unescaped.find(ASYNC_COMPONENT_MARKER, idx)
        if pos == -1:
            break
        start = unescaped.rfind("{", 0, pos)
        if start == -1:
            break
        raw_obj = _extract_balanced_object(unescaped, start)
        if raw_obj:
            objects.append(raw_obj)
        idx = pos + len(ASYNC_COMPONENT_MARKER)
    return objects


def _find_legacy_async_objects(blob: str) -> list[str]:
    """Support simplified test fixtures with plain AsyncComponentRequest markers."""
    objects: list[str] = []
    marker = "AsyncComponentRequest"
    start = 0
    while True:
        idx = blob.find(marker, start)
        if idx == -1:
            break
        brace_start = blob.find("{", idx)
        if brace_start == -1:
            break
        raw_obj = _extract_balanced_object(blob, brace_start)
        if raw_obj:
            objects.append(raw_obj)
        start = idx + len(marker)
    return objects


def _extract_balanced_object(text: str, start: int) -> Optional[str]:
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        char = text[idx]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def _parse_descriptor_object(raw_obj: str) -> Optional[AsyncSectionDescriptor]:
    try:
        parsed = json.loads(raw_obj)
    except json.JSONDecodeError:
        return _parse_descriptor_object_legacy(raw_obj)

    if not isinstance(parsed, dict):
        return None

    new_component_id = parsed.get("newComponentId")
    if not isinstance(new_component_id, str):
        return None

    requested_arguments = parsed.get("requestedArguments") or {}
    if not isinstance(requested_arguments, dict):
        requested_arguments = {}

    profile_component_state = _extract_profile_component_state(requested_arguments)
    viewee_profile_id = _extract_viewee_profile_id(requested_arguments, parsed)

    return AsyncSectionDescriptor(
        new_component_id=new_component_id,
        requested_arguments=requested_arguments,
        viewee_profile_id=viewee_profile_id,
        profile_component_state=profile_component_state,
    )


def _parse_descriptor_object_legacy(raw_obj: str) -> Optional[AsyncSectionDescriptor]:
    component_match = NEW_COMPONENT_ID_RE.search(raw_obj)
    if not component_match:
        return None

    new_component_id = component_match.group(1)
    viewee_match = VIEWEE_PROFILE_ID_RE.search(raw_obj)
    viewee_profile_id = viewee_match.group(1) if viewee_match else None

    requested_arguments = _extract_json_block(raw_obj, "requestedArguments") or {}
    profile_component_state = _extract_json_block(raw_obj, "profileComponentState")

    if not viewee_profile_id:
        payload = requested_arguments.get("payload", {})
        if isinstance(payload, dict):
            viewee_profile_id = payload.get("vieweeProfileId")

    return AsyncSectionDescriptor(
        new_component_id=new_component_id,
        requested_arguments=requested_arguments,
        viewee_profile_id=viewee_profile_id,
        profile_component_state=profile_component_state,
    )


def _extract_profile_component_state(
    requested_arguments: dict[str, Any],
) -> Optional[dict[str, Any]]:
    payload = requested_arguments.get("payload")
    if not isinstance(payload, dict):
        return None
    state = payload.get("profileComponentState")
    return state if isinstance(state, dict) else None


def _extract_viewee_profile_id(
    requested_arguments: dict[str, Any],
    parsed: dict[str, Any],
) -> Optional[str]:
    viewee = parsed.get("vieweeProfileId")
    if isinstance(viewee, str):
        return viewee
    payload = requested_arguments.get("payload")
    if isinstance(payload, dict):
        vid = payload.get("vieweeProfileId")
        if isinstance(vid, str):
            return vid
    return None


def _extract_json_block(raw_obj: str, key: str) -> Optional[dict[str, Any]]:
    pattern = re.compile(rf'"{key}"\s*:\s*(\{{)', re.DOTALL)
    match = pattern.search(raw_obj)
    if not match:
        return None

    start = match.start(1)
    fragment = _extract_balanced_object(raw_obj, start)
    if not fragment:
        return None
    try:
        parsed = json.loads(fragment)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _fallback_scan(blob: str) -> list[AsyncSectionDescriptor]:
    """Scan for newComponentId strings when full AsyncComponentRequest parse fails."""
    descriptors: list[AsyncSectionDescriptor] = []
    seen: set[str] = set()
    for component_id in NEW_COMPONENT_ID_RE.findall(blob):
        if component_id in seen:
            continue
        seen.add(component_id)
        descriptors.append(
            AsyncSectionDescriptor(
                new_component_id=component_id,
                requested_arguments={},
            )
        )
    return descriptors
