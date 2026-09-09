# Agent Audit and Provenance Checklist

FinRobot agents can retrieve market data, query filings, run analysis, write
code, and generate reports. For regulated or production-style workflows, keep a
small audit record around each agent action so a reviewer can reconstruct what
the agent saw, which tools it used, and why the final report changed.

This checklist is vendor-neutral and does not require a logging service. It is
intended as a lightweight pattern for teams extending FinRobot beyond notebooks
or demos.

## What to Capture

For each material agent action, capture:

- Run ID and timestamp.
- Agent name and role.
- User request or task summary.
- Tool name and normalized input parameters.
- Data source, report period, filing type, ticker, or URL when applicable.
- Output artifact path, report section, or generated file name.
- Model name and prompt/template version when available.
- Error, retry, or fallback path if the action did not complete normally.

Avoid storing raw API keys, access tokens, client names, or confidential source
documents in the audit record. Store references, hashes, or approved redacted
summaries instead.

## Provenance for Financial Reports

For report-generation workflows, attach a provenance block to the final
artifact or save it beside the output:

```json
{
  "run_id": "demo-run-2026-03-31-001",
  "ticker": "DEMO",
  "report_date": "2026-03-31",
  "source_documents": [
    {
      "type": "10-K",
      "period": "FY2025",
      "accession_number": "demo-accession",
      "hash": "sha256:..."
    }
  ],
  "tools": [
    {
      "name": "get_sec_report",
      "input_hash": "sha256:...",
      "output_hash": "sha256:..."
    }
  ],
  "review_status": "draft_for_human_review"
}
```

The goal is not to make the report immutable. The goal is to make the report
reviewable: a human should be able to trace each major claim back to a source
document, model step, or tool output.

## Review Gates

Before publishing or sharing an agent-generated report, require checks for:

- Missing source documents or failed data fetches.
- Stale filing periods, mismatched tickers, or inconsistent report dates.
- Generated code or files outside the expected workspace.
- Valuation assumptions that changed without a recorded reason.
- Material report sections that lack source evidence.
- Any tool output that was truncated, retried, or replaced by fallback data.

When a check fails, keep the report in draft state and record the reason.

## Minimal Implementation Pattern

Teams can start with append-only JSONL records:

```text
output/audit/<run_id>.jsonl
```

Each line can represent one action, with hashes for large inputs or outputs.
That simple format is easy to diff, archive, and inspect before adopting a more
formal compliance or observability system.
