#!/usr/bin/env python3
"""Sanitize PGE fixture data by replacing real account IDs with synthetic values."""

import argparse
from pathlib import Path


def sanitize_json(path: Path, real_id: str, synthetic_id: str) -> None:
    content = path.read_text(encoding="utf-8")
    if real_id in content:
        content = content.replace(real_id, synthetic_id)
        path.write_text(content, encoding="utf-8")
        print(f"Sanitized: {path}")
    else:
        print(f"Already clean: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace real PGE account IDs with synthetic values.")
    parser.add_argument("paths", nargs="+", help="Files or directories to sanitize")
    parser.add_argument("--real-id", required=True, help="Real account ID to replace")
    parser.add_argument("--synthetic-id", default="0000000000", help="Replacement ID")
    args = parser.parse_args()

    for arg in args.paths:
        path = Path(arg)
        if path.is_file():
            sanitize_json(path, args.real_id, args.synthetic_id)
        elif path.is_dir():
            for json_file in path.rglob("*.json"):
                sanitize_json(json_file, args.real_id, args.synthetic_id)
        else:
            print(f"Not found: {path}")


if __name__ == "__main__":
    main()
