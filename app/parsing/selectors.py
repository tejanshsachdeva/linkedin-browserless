"""
All CSS selectors and text-pattern anchors for LinkedIn profile HTML.

LinkedIn ships obfuscated, rotating class names. Anchor on stable things
(h1, id anchors, aria-label, srcSet URL patterns) — never on generated
classes like _31136337.
"""
from __future__ import annotations

import re

# --- Element selectors ---
TITLE_TAG = "title"
H1_TAG = "h1"
PARAGRAPH_TAG = "p"
IMG_TAG = "img"
FIGURE_TAG = "figure"
LINK_TAG = "link"
SCRIPT_TAG = "script"
META_TAG = "meta"

PROFILE_PRELOAD_LINK = 'link[rel="preload"][imagesrcset]'
CDN_MONITOR_SCRIPT = 'script#cdn-monitor'
REHYDRATE_SCRIPT = 'script#rehydrate-data'
COMO_META = 'meta[name="como-t"]'

CONTACT_INFO_TEXT = "Contact info"
CONNECTIONS_TEXT = "connections"
OPEN_TO_WORK_TEXT = "open to work"
OPEN_TO_WORK_HEADLINE_RE = re.compile(r"^#?open to work\b", re.IGNORECASE)
OPEN_TO_WORK_NAV_LABELS = frozenset(
    {
        "home",
        "my network",
        "jobs",
        "messaging",
        "notifications",
        "me",
        "work",
        "learning",
        "for business",
    }
)

# --- Text regex patterns ---
PRONOUNS_RE = re.compile(
    r"^(he/him|she/her|they/them|he/they|she/they|ze/hir|xe/xem|any pronouns)$",
    re.IGNORECASE,
)
CONNECTION_DEGREE_RE = re.compile(r"^·\s*(1st|2nd|3rd|Out of network)$", re.IGNORECASE)
CONNECTIONS_COUNT_RE = re.compile(r"^\d+\+?$")
CONNECTIONS_INLINE_RE = re.compile(r"^(\d+\+?)\s+connections$", re.IGNORECASE)
HEADLINE_COMPANY_RE = re.compile(r"@\s*([^|]+?)(?:\s*\||$)")
HEADLINE_COMPANY_AT_RE = re.compile(r"\bat\s+([^|]+?)(?:\s*\||$)", re.IGNORECASE)
PROFILE_ID_RE = re.compile(r"ACoAA[A-Za-z0-9_-]+")
MEMBER_URN_RE = re.compile(r"urn:li:member:\d+")

TITLE_SUFFIX = " | LinkedIn"

# Profile picture srcSet width suffixes in LinkedIn CDN URLs
SRCSET_WIDTH_RE = re.compile(r"/(\d+)_\1/")

# Placeholder background detection
BACKGROUND_PLACEHOLDER_MARKERS = (
    "placeholder",
    "default-background",
    "data:image/svg",
)

# LinkedIn CDN path markers
PROFILE_PHOTO_URL_MARKERS = (
    "profile-displayphoto",
    "displayphoto-shrink",
)
BACKGROUND_IMAGE_URL_MARKERS = (
    "profile-displaybackgroundimage",
    "backgroundimage-shrink",
)
