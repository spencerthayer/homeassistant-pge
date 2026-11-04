from copy import deepcopy

import pytest

from scripts.bump_integration_version import bump_integration_version
from scripts.check_release_ci import REQUIRED, next_patch, plan_release, release_ci_status, validate_release_ci

SHA = "a" * 40


def green_pages():
    return [
        {
            "workflow_runs": [
                {
                    "id": index,
                    "path": path,
                    "head_sha": SHA,
                    "event": "push",
                    "head_branch": "main",
                    "status": "completed",
                    "conclusion": "success",
                }
                for index, path in enumerate(REQUIRED, 1)
            ]
        }
    ]


def test_all_required_runs_pass():
    validate_release_ci(green_pages(), SHA)


@pytest.mark.parametrize(
    "field,value",
    [
        ("head_sha", "b" * 40),
        ("event", "pull_request"),
        ("head_branch", "pr-59"),
        ("status", "in_progress"),
        ("conclusion", "failure"),
        ("conclusion", "skipped"),
        ("conclusion", "cancelled"),
    ],
)
def test_non_success_evidence_fails_closed(field, value):
    pages = green_pages()
    pages[0]["workflow_runs"][0][field] = value
    with pytest.raises(ValueError):
        validate_release_ci(pages, SHA)


def test_missing_workflow_fails_closed():
    pages = green_pages()
    pages[0]["workflow_runs"].pop()
    with pytest.raises(ValueError):
        validate_release_ci(pages, SHA)


def test_newer_failure_beats_old_success_across_pages():
    pages = green_pages()
    newer = deepcopy(pages[0]["workflow_runs"][0])
    newer.update(id=100, conclusion="failure")
    pages.append({"workflow_runs": [newer]})
    with pytest.raises(ValueError):
        validate_release_ci(pages, SHA)


def test_newer_success_supersedes_old_failure():
    pages = green_pages()
    old = deepcopy(pages[0]["workflow_runs"][0])
    old.update(id=0, conclusion="failure")
    pages.append({"workflow_runs": [old]})
    validate_release_ci(pages, SHA)


def test_in_progress_run_waits():
    pages = green_pages()
    pages[0]["workflow_runs"][0]["status"] = "in_progress"
    assert release_ci_status(pages, SHA) == "wait"


def test_plan_publishes_skips_or_bumps():
    head = SHA
    assert plan_release("0.12.10", head, None) == "publish"
    assert plan_release("0.12.10", head, head) == "skip"
    assert plan_release("0.12.9", head, "b" * 40) == "bump"
    assert next_patch("0.12.9") == "0.12.10"


def test_bump_moves_version_and_cache_key(tmp_path):
    package = tmp_path / "custom_components" / "pge_energy"
    frontend = package / "frontend"
    frontend.mkdir(parents=True)
    (package / "const.py").write_text('VERSION = "0.12.9"\n')
    (package / "manifest.json").write_text('{\n  "version": "0.12.9"\n}\n')
    (tmp_path / "README.md").write_text("e.g. `0.12.9`\n")
    (frontend / "panel.js").write_text('import "./data.js?v=0.12.9";\n')
    bump_integration_version(tmp_path, "0.12.9", "0.12.10")
    assert 'VERSION = "0.12.10"' in (package / "const.py").read_text()
    assert '"version": "0.12.10"' in (package / "manifest.json").read_text()
    assert "`0.12.10`" in (tmp_path / "README.md").read_text()
    assert "?v=0.12.10" in (frontend / "panel.js").read_text()
