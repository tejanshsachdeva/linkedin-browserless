#!/usr/bin/env python3
"""Interactive helper to configure LinkedIn session credentials."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.client.session import generate_jsessionid  # noqa: E402


INSTRUCTIONS = """
LinkedIn Session Setup
======================

1. Log into LinkedIn in your browser.
2. Open DevTools (F12) → Application → Cookies → https://www.linkedin.com
3. Find the cookie named "li_at" and copy its value.
   WARNING: li_at is password-equivalent. Never commit it to git.

4. Optionally copy "JSESSIONID" (must match csrf-token header if set).
   If omitted, one will be auto-generated as ajax:<19-digit-number>.

5. Paste values below when prompted, or pass --li-at on the command line.
""".strip()


def write_session_state(path: Path, li_at: str, jsessionid: str) -> None:
    payload = {"cookies": {"li_at": li_at, "JSESSIONID": jsessionid}}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote session to {path}")


def write_env_snippet(path: Path, li_at: str, jsessionid: str) -> None:
    snippet = (
        f"LINKEDIN_LI_AT={li_at}\n"
        f"LINKEDIN_JSESSIONID={jsessionid}\n"
    )
    path.write_text(snippet, encoding="utf-8")
    print(f"Wrote .env snippet to {path} (merge into your .env manually)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure LinkedIn session credentials")
    parser.add_argument("--li-at", help="Value of the li_at cookie")
    parser.add_argument("--jsessionid", help="Value of JSESSIONID cookie (optional)")
    parser.add_argument(
        "--session-path",
        default="session_state.json",
        help="Path to write session_state.json",
    )
    parser.add_argument(
        "--env-snippet",
        default=".env.session",
        help="Path to write a .env snippet",
    )
    args = parser.parse_args()

    print(INSTRUCTIONS)
    print()

    li_at = args.li_at or input("li_at cookie value: ").strip()
    if not li_at:
        print("Error: li_at is required.", file=sys.stderr)
        sys.exit(1)

    jsessionid = args.jsessionid or input("JSESSIONID (press Enter to auto-generate): ").strip()
    if not jsessionid:
        jsessionid = generate_jsessionid()
        print(f"Generated JSESSIONID: {jsessionid}")

    write_session_state(Path(args.session_path), li_at, jsessionid)
    write_env_snippet(Path(args.env_snippet), li_at, jsessionid)
    print("\nDone. Start the API with: uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
