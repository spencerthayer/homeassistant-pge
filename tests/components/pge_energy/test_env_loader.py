from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from custom_components.pge_energy.env_loader import (
    EnvPermissionError,
    load_env_file,
)


def test_maps_owner_keys(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "email=user@example.com\npassword=secret\naccount_number=0000000001\n",
        encoding="utf-8",
    )
    os.chmod(env_path, 0o600)
    target: dict[str, str] = {}
    result = load_env_file(env_path, environ=target)
    assert target["PGE_EMAIL"] == "user@example.com"
    assert target["PGE_PASSWORD"] == "secret"
    assert target["PGE_ACCOUNT_HINT"] == "0000000001"
    assert "PGE_EMAIL" in result.mapped_keys


def test_existing_env_wins_without_override(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text("email=fromfile@example.com\n", encoding="utf-8")
    os.chmod(env_path, 0o600)
    target = {"PGE_EMAIL": "already@example.com"}
    load_env_file(env_path, environ=target, override=False)
    assert target["PGE_EMAIL"] == "already@example.com"


def test_refuse_insecure_permissions(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text("email=user@example.com\n", encoding="utf-8")
    os.chmod(env_path, 0o644)
    with pytest.raises(EnvPermissionError):
        load_env_file(env_path, environ={}, refuse_insecure=True)
    # Mode still world/group readable
    assert env_path.stat().st_mode & (stat.S_IROTH | stat.S_IRGRP)


def test_allow_insecure_with_flag(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text("email=user@example.com\n", encoding="utf-8")
    os.chmod(env_path, 0o644)
    target: dict[str, str] = {}
    result = load_env_file(env_path, environ=target, refuse_insecure=False)
    assert result.world_or_group_readable is True
    assert target["PGE_EMAIL"] == "user@example.com"
