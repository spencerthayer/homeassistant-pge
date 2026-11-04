"""Require successful latest main-push CI and Prek runs for an exact SHA."""

from __future__ import annotations

import json
import re
import sys

REQUIRED = (".github/workflows/ci.yml", ".github/workflows/prek-check.yaml")
PENDING = {"queued", "in_progress", "waiting", "pending", "requested", "waiting_for_concurrency"}
_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_SHA = re.compile(r"[0-9a-f]{40}")


def _latest_required_runs(pages: list[dict], sha: str) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for page in pages:
        for run in page["workflow_runs"]:
            path = run["path"]
            if path not in REQUIRED or run["head_sha"] != sha or run["event"] != "push" or run["head_branch"] != "main":
                continue
            if path not in latest or run["id"] > latest[path]["id"]:
                latest[path] = run
    return latest


def release_ci_status(pages: list[dict], sha: str) -> str:
    """Return ready, wait, or fail for the latest main-push CI and Prek runs."""
    if not _SHA.fullmatch(sha):
        raise ValueError("full lowercase release SHA required")
    latest = _latest_required_runs(pages, sha)
    waiting = False
    for path in REQUIRED:
        run = latest.get(path)
        if not run or run.get("status") in PENDING:
            waiting = True
            continue
        if run.get("status") != "completed" or run.get("conclusion") != "success":
            return "fail"
    if waiting:
        return "wait"
    return "ready"


def validate_release_ci(pages: list[dict], sha: str) -> None:
    if release_ci_status(pages, sha) != "ready":
        raise ValueError("required workflow has not passed")


def plan_release(version: str, head: str, tagged: str | None) -> str:
    """publish when the version tag is new, skip when it already points here, otherwise bump."""
    if not _SEMVER.fullmatch(version):
        raise ValueError("SemVer required")
    if not _SHA.fullmatch(head):
        raise ValueError("full lowercase release SHA required")
    if tagged is None:
        return "publish"
    if not _SHA.fullmatch(tagged):
        raise ValueError("full lowercase tag SHA required")
    if tagged == head:
        return "skip"
    return "bump"


def next_patch(version: str) -> str:
    if not _SEMVER.fullmatch(version):
        raise ValueError("SemVer required")
    major, minor, patch = (int(part) for part in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


if __name__ == "__main__":
    try:
        command = sys.argv[1]
        if command == "--status":
            print(release_ci_status(json.load(sys.stdin), sys.argv[2]))
        elif command == "--plan":
            tagged = None if sys.argv[4] == "missing" else sys.argv[4]
            print(plan_release(sys.argv[2], sys.argv[3], tagged))
        elif command == "--next-patch":
            print(next_patch(sys.argv[2]))
        else:
            validate_release_ci(json.load(sys.stdin), command)
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise SystemExit(str(exc)) from exc
