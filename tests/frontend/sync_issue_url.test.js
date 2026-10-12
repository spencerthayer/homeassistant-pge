import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { redactSyncText, syncHasReportableError, syncIssueUrl } from "../../custom_components/pge_energy/frontend/data.js";

describe("sync issue url", () => {
  it("redacts emails and long numbers", () => {
    assert.equal(
      redactSyncText("failed for user@example.com account 1234567890"),
      "failed for [redacted-email] account [redacted]",
    );
  });

  it("builds a prefilled bug-report link and omits the account", () => {
    const url = new URL(
      syncIssueUrl({
        version: "0.13.2",
        haVersion: "2026.10.0",
        sync: {
          status: "error",
          phase: "usage",
          error: "portal timeout for user@example.com",
          entry_id: "pge_account_1234567890",
          last_successful_update: "2026-10-18T08:00:00Z",
        },
      }),
    );
    assert.equal(url.origin + url.pathname, "https://github.com/spencerthayer/homeassistant-pge/issues/new");
    assert.equal(url.searchParams.get("template"), "bug_report.md");
    assert.match(url.searchParams.get("title"), /^\[Bug\] Sync error/);
    const body = url.searchParams.get("body");
    assert.match(body, /2026\.10\.0/);
    assert.match(body, /0\.13\.2/);
    assert.match(body, /portal timeout for \[redacted-email\]/);
    assert.match(body, /Last successful update: 2026-10-18T08:00:00Z/);
    assert.doesNotMatch(body, /1234567890/);
    assert.doesNotMatch(body, /user@example.com/);
  });

  it("treats an API error as reportable and a clean sync as not", () => {
    assert.equal(syncHasReportableError({ status: "complete" }), false);
    assert.equal(syncHasReportableError({ status: "complete", last_api_error: "401" }), true);
    assert.equal(syncHasReportableError({ failed_days: 2 }), true);
  });
});
