"""Extract connection degree from embedded profile HTML metadata."""

from __future__ import annotations

import re

_NETWORK_DISTANCE_RE = re.compile(r'networkDistance\\":(-?\d+)')
_DISTANCE_ENUM_RE = re.compile(r"DISTANCE_(\d+)", re.IGNORECASE)
_DEGREE_LABELS = {
    1: "1st",
    2: "2nd",
    3: "3rd",
}


def parse_connection_degree_from_html(html: str) -> str | None:
    for pattern in (_NETWORK_DISTANCE_RE, _DISTANCE_ENUM_RE):
        for match in pattern.finditer(html):
            raw = match.group(1)
            try:
                distance = int(raw)
            except ValueError:
                continue
            if distance in _DEGREE_LABELS:
                return _DEGREE_LABELS[distance]
            if distance <= 0:
                continue
    if re.search(r"Out of network", html, re.IGNORECASE):
        return "Out of network"
    return None
