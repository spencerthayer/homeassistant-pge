from copy import deepcopy
import pytest
from scripts.check_release_ci import REQUIRED, validate_release_ci

SHA = "a" * 40


def green_pages():
    return [{"workflow_runs": [
        {"id": index, "path": path, "head_sha": SHA, "event": "push",
         "head_branch": "main", "status": "completed", "conclusion": "success"}
        for index, path in enumerate(REQUIRED, 1)
    ]}]


def test_all_required_runs_pass():
    validate_release_ci(green_pages(), SHA)


@pytest.mark.parametrize("field,value", [
    ("head_sha", "b" * 40), ("event", "pull_request"),
    ("head_branch", "pr-59"), ("status", "in_progress"),
    ("conclusion", "failure"), ("conclusion", "skipped"),
    ("conclusion", "cancelled"),
])
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
