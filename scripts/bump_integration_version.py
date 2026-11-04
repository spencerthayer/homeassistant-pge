"""Move the integration version and the frontend cache key together."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def bump_integration_version(root: Path, old: str, new: str) -> None:
    if not _SEMVER.fullmatch(old) or not _SEMVER.fullmatch(new):
        raise ValueError("SemVer required")
    const_path = root / "custom_components/pge_energy/const.py"
    const = const_path.read_text()
    updated, count = re.subn(
        rf'^VERSION = "{re.escape(old)}"',
        f'VERSION = "{new}"',
        const,
        count=1,
        flags=re.M,
    )
    if count != 1:
        raise ValueError("const.py VERSION did not match")
    const_path.write_text(updated)

    manifest_path = root / "custom_components/pge_energy/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("version") != old:
        raise ValueError("manifest version did not match")
    manifest["version"] = new
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    readme_path = root / "README.md"
    readme = readme_path.read_text()
    needle = f"`{old}`"
    if needle not in readme:
        raise ValueError("README version example did not match")
    readme_path.write_text(readme.replace(needle, f"`{new}`", 1))

    frontend = root / "custom_components/pge_energy/frontend"
    replacements = 0
    for path in frontend.glob("*.js"):
        text = path.read_text()
        updated = text.replace(f"?v={old}", f"?v={new}")
        if updated != text:
            path.write_text(updated)
            replacements += 1
    if replacements == 0:
        raise ValueError("frontend cache key did not match")


if __name__ == "__main__":
    try:
        bump_integration_version(Path.cwd(), sys.argv[1], sys.argv[2])
    except (ValueError, OSError, json.JSONDecodeError, IndexError) as exc:
        raise SystemExit(str(exc)) from exc
