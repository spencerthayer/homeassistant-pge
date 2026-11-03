"""Require successful latest main-push CI and Prek runs for an exact SHA."""
from __future__ import annotations

import json
import re
import sys

REQUIRED = (".github/workflows/ci.yml", ".github/workflows/prek-check.yaml")


def validate_release_ci(pages: list[dict], sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("full lowercase release SHA required")
    latest: dict[str, dict] = {}
    for page in pages:
        for run in page["workflow_runs"]:
            path = run["path"]
            if (path not in REQUIRED or run["head_sha"] != sha
                    or run["event"] != "push" or run["head_branch"] != "main"):
                continue
            if path not in latest or run["id"] > latest[path]["id"]:
                latest[path] = run
    for path in REQUIRED:
        run = latest.get(path)
        if not run or run["status"] != "completed" or run["conclusion"] != "success":
            raise ValueError(f"required workflow has not passed: {path}")


if __name__ == "__main__":
    try:
        validate_release_ci(json.load(sys.stdin), sys.argv[1])
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise SystemExit(str(exc)) from exc
