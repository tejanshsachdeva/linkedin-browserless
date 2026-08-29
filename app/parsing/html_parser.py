"""Tier A (top-card) field extraction from server-rendered profile HTML."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import unquote

from bs4 import BeautifulSoup, Tag

from app.models.schemas import ImageRenditions, OpenToWork
from app.parsing import selectors as sel


@dataclass
class TopCardData:
    name: Optional[str] = None
    headline: Optional[str] = None
    location: Optional[str] = None
    pronouns: Optional[str] = None
    connection_degree: Optional[str] = None
    connections_count: Optional[str] = None
    current_company: Optional[str] = None
    current_school: Optional[str] = None
    profile_picture: Optional[ImageRenditions] = None
    background_image: Optional[ImageRenditions] = None
    profile_id: Optional[str] = None
    member_urn: Optional[str] = None
    open_to_work: Optional[OpenToWork] = None
    client_version: Optional[str] = None
    csrf_token: Optional[str] = None


def parse_top_card(html: str) -> TopCardData:
    soup = BeautifulSoup(html, "lxml")
    data = TopCardData()

    data.name = _extract_name(soup)
    paragraphs = _collect_paragraph_texts(soup)
    data.headline = _extract_headline(paragraphs, data.name)
    data.location = _extract_location(soup, paragraphs)
    data.pronouns = _extract_pronouns(paragraphs)
    data.connection_degree = _extract_connection_degree(paragraphs)
    data.connections_count = _extract_connections_count(soup)
    data.current_company, data.current_school = _extract_entity_rows(soup)
    if data.headline:
        headline_company = _extract_company_from_headline(data.headline)
        if headline_company:
            data.current_company = headline_company
    data.profile_picture = _extract_profile_picture(soup)
    data.background_image = _extract_background_image(soup)
    data.profile_id = _most_frequent_match(sel.PROFILE_ID_RE, html)
    data.member_urn = _most_frequent_match(sel.MEMBER_URN_RE, html)
    data.open_to_work = _extract_open_to_work(soup)
    data.client_version = _extract_client_version(soup)
    data.csrf_token = _extract_csrf_token(soup)

    return data


def _collect_paragraph_texts(soup: BeautifulSoup) -> list[str]:
    texts: list[str] = []
    for p in soup.find_all(sel.PARAGRAPH_TAG):
        text = _clean_text(p.get_text(" ", strip=True))
        if text:
            texts.append(text)
    return texts


def _extract_name(soup: BeautifulSoup) -> Optional[str]:
    h1 = soup.find(sel.H1_TAG)
    if h1:
        name = _clean_text(h1.get_text(strip=True))
        if name:
            return name

    title = soup.find(sel.TITLE_TAG)
    if title and title.string:
        title_text = title.string.strip()
        if sel.TITLE_SUFFIX in title_text:
            return title_text.split(sel.TITLE_SUFFIX)[0].strip()
        return title_text or None
    return None


def _extract_headline(paragraphs: list[str], name: Optional[str]) -> Optional[str]:
    skip = {name} if name else set()
    for text in paragraphs:
        if text in skip:
            continue
        if sel.PRONOUNS_RE.match(text):
            continue
        if sel.CONNECTION_DEGREE_RE.match(text):
            continue
        if sel.CONNECTIONS_INLINE_RE.match(text):
            continue
        if sel.CONNECTIONS_COUNT_RE.match(text):
            continue
        if text.lower() == sel.CONNECTIONS_TEXT:
            continue
        if sel.CONTACT_INFO_TEXT.lower() in text.lower():
            continue
        if len(text) > 10 and not text.startswith("·"):
            return text
    return None


def _extract_location(soup: BeautifulSoup, paragraphs: list[str]) -> Optional[str]:
    for p in soup.find_all(sel.PARAGRAPH_TAG):
        text = _clean_text(p.get_text(" ", strip=True))
        if not text or sel.PRONOUNS_RE.match(text):
            continue
        sibling_texts = [
            _clean_text(s.get_text(" ", strip=True))
            for s in p.find_next_siblings(sel.PARAGRAPH_TAG, limit=3)
        ]
        block = " ".join([text, *sibling_texts])
        if "·" in block and sel.CONTACT_INFO_TEXT in block:
            return text
    for text in paragraphs:
        if sel.PRONOUNS_RE.match(text):
            continue
        if sel.CONNECTION_DEGREE_RE.match(text):
            continue
        if sel.CONNECTIONS_COUNT_RE.match(text):
            continue
        if text.lower() == sel.CONNECTIONS_TEXT:
            continue
        if "," in text and not text.startswith("·") and sel.CONTACT_INFO_TEXT not in text:
            return text
    return None


def _extract_pronouns(paragraphs: list[str]) -> Optional[str]:
    for text in paragraphs:
        if sel.PRONOUNS_RE.match(text):
            return text
    return None


def _extract_connection_degree(paragraphs: list[str]) -> Optional[str]:
    for text in paragraphs:
        match = sel.CONNECTION_DEGREE_RE.match(text)
        if match:
            return match.group(1)
        inline = re.search(r"·\s*(1st|2nd|3rd|Out of network)\b", text, re.IGNORECASE)
        if inline:
            return inline.group(1)
    return None


def _extract_connections_count(soup: BeautifulSoup) -> Optional[str]:
    for p in soup.find_all(sel.PARAGRAPH_TAG):
        text = _clean_text(p.get_text(strip=True))
        inline = sel.CONNECTIONS_INLINE_RE.match(text)
        if inline:
            return inline.group(1)
        if text.lower() == sel.CONNECTIONS_TEXT:
            prev = p.find_previous(sel.PARAGRAPH_TAG)
            if prev:
                prev_text = _clean_text(prev.get_text(strip=True))
                if sel.CONNECTIONS_COUNT_RE.match(prev_text):
                    return prev_text
    return None


def _extract_company_from_headline(headline: str) -> Optional[str]:
    for pattern in (sel.HEADLINE_COMPANY_RE, sel.HEADLINE_COMPANY_AT_RE):
        match = pattern.search(headline)
        if match:
            company = _clean_text(match.group(1))
            if company:
                return company
    return None


def _extract_entity_rows(soup: BeautifulSoup) -> tuple[Optional[str], Optional[str]]:
    """
    Top-card entity rows: first is current company, second is current school.
    Heuristic: anchor rows with links to /company/ and /school/.
    """
    companies: list[str] = []
    schools: list[str] = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        text = _clean_text(anchor.get_text(strip=True))
        if not text:
            continue
        if "/company/" in href and text not in companies:
            companies.append(text)
        elif "/school/" in href and text not in schools:
            schools.append(text)

    company = companies[0] if companies else None
    school = schools[0] if schools else None
    return company, school


def _parse_srcset(srcset: str) -> dict[str, str]:
    renditions: dict[str, str] = {}
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        pieces = part.split()
        if len(pieces) < 2:
            continue
        url, descriptor = pieces[0], pieces[1]
        width = descriptor.rstrip("w")
        if width.isdigit():
            renditions[width] = url
        else:
            match = sel.SRCSET_WIDTH_RE.search(url)
            if match:
                renditions[match.group(1)] = url
    return renditions


def _build_image_renditions(renditions: dict[str, str]) -> Optional[ImageRenditions]:
    if not renditions:
        return None
    sorted_keys = sorted(renditions.keys(), key=lambda k: int(k))
    primary = renditions[sorted_keys[-1]]
    return ImageRenditions(primary=primary, renditions=renditions)


def _is_background_image_url(url: str) -> bool:
    lower = url.lower()
    return any(marker in lower for marker in sel.BACKGROUND_IMAGE_URL_MARKERS)


def _is_profile_photo_url(url: str) -> bool:
    lower = url.lower()
    if "media.licdn.com" not in lower:
        return False
    if _is_background_image_url(url):
        return False
    if any(marker in lower for marker in sel.PROFILE_PHOTO_URL_MARKERS):
        return True
    # Legacy/generic CDN paths used in preload tags (e.g. photo800/800_800).
    return "displaybackgroundimage" not in lower


def _filter_profile_renditions(renditions: dict[str, str]) -> dict[str, str]:
    return {width: url for width, url in renditions.items() if _is_profile_photo_url(url)}


def _extract_profile_picture(soup: BeautifulSoup) -> Optional[ImageRenditions]:
    for preload in soup.select(sel.PROFILE_PRELOAD_LINK):
        srcset = preload.get("imagesrcset") or preload.get("imageSrcSet")
        if not srcset:
            continue
        renditions = _filter_profile_renditions(_parse_srcset(srcset))
        built = _build_image_renditions(renditions)
        if built:
            return built

    for img in soup.find_all(sel.IMG_TAG):
        srcset = img.get("srcset") or img.get("srcSet")
        if not srcset or "media.licdn.com" not in srcset:
            continue
        renditions = _filter_profile_renditions(_parse_srcset(srcset))
        built = _build_image_renditions(renditions)
        if built:
            return built
    return None


def _extract_background_image(soup: BeautifulSoup) -> Optional[ImageRenditions]:
    for figure in soup.find_all(sel.FIGURE_TAG):
        img = figure.find(sel.IMG_TAG)
        if not img:
            continue
        src = img.get("src") or ""
        srcset = img.get("srcset") or img.get("srcSet") or ""
        combined = f"{src} {srcset}".lower()
        if any(marker in combined for marker in sel.BACKGROUND_PLACEHOLDER_MARKERS):
            continue
        if src and "media.licdn.com" in src and _is_background_image_url(src):
            return ImageRenditions(primary=src, renditions={"default": src})
        if srcset:
            renditions = {
                width: url
                for width, url in _parse_srcset(srcset).items()
                if _is_background_image_url(url)
            }
            built = _build_image_renditions(renditions)
            if built:
                return built
    return None


def _most_frequent_match(pattern: re.Pattern[str], text: str) -> Optional[str]:
    matches = pattern.findall(text)
    if not matches:
        return None
    return Counter(matches).most_common(1)[0][0]


def _inside_non_visible_tag(element: object) -> bool:
    parent = getattr(element, "parent", None)
    while isinstance(parent, Tag):
        if parent.name in ("script", "style", "noscript", "head"):
            return True
        parent = parent.parent
    return False


def _extract_open_to_work(soup: BeautifulSoup) -> Optional[OpenToWork]:
    for element in soup.find_all(string=re.compile(sel.OPEN_TO_WORK_TEXT, re.I)):
        if _inside_non_visible_tag(element):
            continue
        parent = element.parent
        if not isinstance(parent, Tag):
            continue
        container = parent
        for _ in range(4):
            if container.parent and isinstance(container.parent, Tag):
                container = container.parent
        texts = [
            _clean_text(t.get_text(" ", strip=True))
            for t in container.find_all(["strong", "p", "span"])
            if _clean_text(t.get_text(" ", strip=True))
        ]
        if not texts:
            continue
        headline = texts[0]
        if not sel.OPEN_TO_WORK_HEADLINE_RE.match(headline):
            continue
        if headline.lower() in sel.OPEN_TO_WORK_NAV_LABELS:
            continue
        detail = texts[1] if len(texts) > 1 else None
        if detail and detail.lower() in sel.OPEN_TO_WORK_NAV_LABELS:
            detail = None
        return OpenToWork(headline=headline, detail=detail)
    return None


def _extract_client_version(soup: BeautifulSoup) -> Optional[str]:
    meta = soup.select_one(sel.COMO_META)
    if not meta:
        return None
    content = meta.get("content") or ""
    try:
        payload = json.loads(unquote(content))
        return payload.get("serviceVersion")
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_csrf_token(soup: BeautifulSoup) -> Optional[str]:
    script = soup.select_one(sel.CDN_MONITOR_SCRIPT)
    if script:
        return script.get("data-csrf")
    return None


def _clean_text(value: str) -> str:
    return " ".join(value.split())
