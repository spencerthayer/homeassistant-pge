#!/usr/bin/env python3
"""Fail if known secret patterns or real account identifiers appear in the repo.

Personal identifiers are never hardcoded here. When a local ``.env`` exists,
its account/email values are loaded at runtime and scanned for as forbidden
literals (so deleting ``.env`` also removes those checks).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# JWT-like values, with or without Bearer prefix.
JWTISH = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
EMAILISH = re.compile(
    r"\b[A-Za-z0-9._%+-]+@(?:gmail|yahoo|hotmail|outlook|icloud|comcast|aol)\.[A-Za-z]{2,}\b",
    re.IGNORECASE,
)
# Long opaque secrets that look like session/refresh tokens (exclude synthetic fixtures).
OPAQUE_SECRET = re.compile(r"(?i)(refresh[_-]?token|session[_-]?id|cookie)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{32,}")

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    ".ruff_cache",
    ".cursor",
    "outputs",  # local HA UAT / live state (gitignored)
}
ALLOW_EMAIL_PATHS = {
    "AUTH_DISCOVERY.md",  # may document example.com patterns only
}
SKIP_FILES = {
    ".env",
    "scripts/scan_secrets.py",
}


def _parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _forbidden_from_env() -> tuple[str, ...]:
    """Load personal identifiers from local .env only (never committed literals)."""
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return ()
    try:
        values = _parse_dotenv(env_path.read_text(encoding="utf-8"))
    except OSError:
        return ()
    found: list[str] = []
    for key in ("account_number", "PGE_ACCOUNT_ID", "PGE_ACCOUNT_HINT", "email", "PGE_EMAIL", "username"):
        value = (values.get(key) or "").strip()
        if value and value not in found:
            found.append(value)
    return tuple(found)


def main() -> int:
    forbidden = _forbidden_from_env()
    hits: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = str(path.relative_to(ROOT))
        if rel in SKIP_FILES or path.name == ".env":
            continue
        if path.suffix not in {".py", ".md", ".json", ".yaml", ".yml", ".txt", ".csv", ".har"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lit in forbidden:
            if lit in text:
                hits.append(f"{rel}: forbidden local .env value leaked")
        if JWTISH.search(text) and "sanitize" not in path.name:
            hits.append(f"{rel}: JWT-like token")
        if OPAQUE_SECRET.search(text) and "sanitize" not in path.name:
            hits.append(f"{rel}: opaque session/refresh secret")
        if EMAILISH.search(text) and rel not in ALLOW_EMAIL_PATHS:
            # Allow synthetic example.com / test fixtures only.
            for match in EMAILISH.finditer(text):
                if match.group(0).lower().endswith("@example.com"):
                    continue
                hits.append(f"{rel}: consumer email-like address {match.group(0)}")

    if hits:
        print("Secret scan failed:")
        for hit in hits:
            print(f"  - {hit}")
        return 1
    print("Secret scan passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
