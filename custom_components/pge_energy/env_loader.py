"""Opt-in .env loading for the local CLI / live-test harness.

Never imported by the Home Assistant integration package path used at runtime
for config entries. Callers must pass an explicit path (e.g. --env-file .env).
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

# Map owner .env keys → PGE_* names consumed by the CLI.
ENV_KEY_MAP: dict[str, str] = {
    "email": "PGE_EMAIL",
    "password": "PGE_PASSWORD",
    "account_number": "PGE_ACCOUNT_HINT",
    "username": "PGE_USERNAME",
    # Also accept already-prefixed keys.
    "PGE_EMAIL": "PGE_EMAIL",
    "PGE_PASSWORD": "PGE_PASSWORD",
    "PGE_ACCOUNT_ID": "PGE_ACCOUNT_ID",
    "PGE_ACCOUNT_HINT": "PGE_ACCOUNT_HINT",
    "PGE_USERNAME": "PGE_USERNAME",
    "PGE_BEARER_TOKEN": "PGE_BEARER_TOKEN",
    "PGE_ENCRYPTED_PERSON_ID": "PGE_ENCRYPTED_PERSON_ID",
    "PGE_REFRESH_CREDENTIAL": "PGE_REFRESH_CREDENTIAL",
}


@dataclass(frozen=True, slots=True)
class EnvLoadResult:
    path: Path
    mapped_keys: tuple[str, ...]
    mode: int
    world_or_group_readable: bool


class EnvPermissionError(RuntimeError):
    """Raised when a secret file is group/world readable and refuse is requested."""


def _parse_dotenv(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def load_env_file(
    path: str | Path,
    *,
    environ: dict[str, str] | None = None,
    override: bool = False,
    refuse_insecure: bool = True,
) -> EnvLoadResult:
    """Load mapped keys from path into environ (default: os.environ).

    Existing process env wins unless override=True.
    """
    env_path = Path(path).expanduser().resolve()
    if not env_path.is_file():
        raise FileNotFoundError(f"env file not found: {env_path}")

    mode = env_path.stat().st_mode
    insecure = bool(mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH))
    if insecure and refuse_insecure:
        raise EnvPermissionError(
            f"{env_path} is group/world-readable (mode {oct(mode & 0o777)}). Run: chmod 600 " + str(env_path)
        )

    target = environ if environ is not None else os.environ
    parsed = _parse_dotenv(env_path.read_text(encoding="utf-8"))
    mapped: list[str] = []
    for src_key, dest_key in ENV_KEY_MAP.items():
        if src_key not in parsed:
            continue
        if not override and dest_key in target and target[dest_key]:
            continue
        target[dest_key] = parsed[src_key]
        mapped.append(dest_key)

    return EnvLoadResult(
        path=env_path,
        mapped_keys=tuple(sorted(set(mapped))),
        mode=mode & 0o777,
        world_or_group_readable=insecure,
    )
