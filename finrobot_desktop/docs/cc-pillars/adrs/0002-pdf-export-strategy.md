# ADR-0002: PDF export strategy — reuse finrobot's weasyprint, defer FinRobot port

| | |
|---|---|
| **版本** | v1.0 |
| **状态** | Accepted |
| **日期** | 2026-05-21 |
| **作者** | finrobot-backend (Opus 4.7) |
| **触发** | v5 PR5 实施 — spec §12.2 + §13 PR5 |

---

## 0. TL;DR

v5 PR5 ships `POST /api/exports/pdf/{artifact_id}` reusing finrobot's existing
weasyprint pipeline (`engine/reports/pdf_renderer.py` + `html_renderer.py` +
Jinja2 templates). The 1,555-line FinRobot `professional_pdf_report.py` port
that spec §13 PR5 originally proposed is **deferred** to a follow-up because:

1. finrobot already has a working weasyprint pipeline used by
   `/api/report/pdf?ticker=X`.
2. FinRobot's PDF builder carries its own matplotlib charting + formatting
   layer that overlaps with finrobot's templates → a clean port is
   meaningfully larger than 350 LoC.
3. v5 PR5's real shortfall is *artifact addressing*, not visual fidelity —
   the existing route only knows about the in-memory `report_cache`, so
   you can't download yesterday's analysis. Per-artifact addressing
   unblocks the "我的研究" download button immediately.

A future ADR-0003 will revisit visual fidelity once we have UI feedback on
how the current weasyprint output reads.

---

## 1. Context

Spec §12.2 says "我的研究 cards have a PDF download button" and §13 PR5 was
sized at ~350 LoC for migrating FinRobot's `professional_pdf_report.py`.
On inspection:

- `professional_pdf_report.py` is **1,555 lines**, not 350.
- It builds its own matplotlib chart suite + formatted tables + cover page,
  almost all of which overlaps with finrobot's existing
  `engine/reports/templates/*.html`.
- finrobot's existing `/api/report/pdf?ticker=X` route works end-to-end
  with weasyprint — the only thing it's missing is the ability to address
  *any* historic artifact, not just the cached pipeline.

The real user need — "let me download the PDF of an artifact from 3 weeks
ago" — is fully solved by per-artifact addressing without touching the
visual rendering at all.

## 2. Decision

PR5 adds `routes/exports.py` with `POST /api/exports/pdf/{artifact_id}`
that:

1. Loads the full Artifact via `ArtifactStore.get(id)` → 404 on miss.
2. Maps `artifact.type` to one of six existing `render_*_report` calls
   (`equity_research / dcf / comps / lbo / earnings / ic_memo`) → 415
   when the type has no template yet.
3. Pipes HTML through `engine/reports/pdf_renderer.render_pdf()` →
   501 when weasyprint isn't installed on the host.
4. Catches renderer KeyError/AttributeError/TypeError/ValueError →
   422 ("Artifact incomplete for PDF render") so partial artifacts from
   older schema versions don't return 500.

No new dependencies, no template changes, no FinRobot code touched.

## 3. Alternatives Considered

### 3.1 Full port of FinRobot's professional_pdf_report.py

**Rejected** — 1,555 LoC migration in scope creep territory for v5. We'd
either run two parallel formatting stacks (FinRobot's matplotlib + finrobot's
Jinja2/HTML), or rip out the working pipeline to swap in an untested port.
Both are net-worse than shipping per-artifact addressing today and revisiting
visual fidelity once users actually look at the PDF.

### 3.2 Keep only `/api/report/pdf?ticker=X` and tell UI to use `?artifact_id=`

**Rejected** — that route reads `request.app.state.deps.report_cache[ticker]`,
which is in-memory only. Adding an `artifact_id` param means a second code
path that bypasses the cache. Cleaner to give artifact-PDF its own route
that loads from disk.

### 3.3 Generate PDF on artifact save and store it next to the JSON

**Rejected** — multiplies storage cost, and weasyprint is slow enough
(seconds) that doing it inline would slow every pipeline run. Lazy
rendering on download keeps storage small and only pays the cost when
the user actually clicks download.

## 4. Consequences

### 4.1 Positive

- "我的研究" download button unblocked today.
- Zero new dependencies, zero new templates.
- Same 6 supported types as the existing pipeline → no surprise gaps.
- Failure modes are explicit (404 / 415 / 422 / 501) — the UI can
  show user-friendly errors.

### 4.2 Negative

- Visual fidelity matches finrobot's current templates, which are simpler
  than FinRobot's professional layout. If users complain we'll need a
  follow-up to either port FinRobot or invest in the existing templates.
- 422 fires for artifacts written before all template-required fields
  existed — a v2 backfill / migration is possible but out of scope here.

### 4.3 Out of scope

- Watermarking / cover page customisation
- Multi-ticker comparison PDFs
- Hosted PDF storage / shareable links

---

## 5. Implementation Notes

### 5.1 File changes

| File | Change |
|---|---|
| `finrobot/routes/exports.py` | new — route + per-type context builders + error mapping |
| `finrobot/server.py` | +2 lines — import + `app.include_router(exports_router)` |
| `tests/routes/test_export_pdf_route.py` | new — 4 cases: 404 / 415 / 503 / 200-or-known-failure |

### 5.2 Audit

No new red lines — the route only delegates to the existing
`ArtifactStore` + `render_pdf` + `render_*_report` surface. The leaf-layer
test in `tests/audit/test_architecture.py` already covers them.

### 5.3 Roll back

`git rm finrobot/routes/exports.py tests/routes/test_export_pdf_route.py`
+ revert the two `server.py` lines. The existing `/api/report/pdf?ticker=X`
route is unchanged, so nothing currently shipping regresses.

---

## 6. Open Questions

- Do users actually need the FinRobot-style visual format, or are
  finrobot's templates "good enough" for retail readers? Defer until UI
  feedback on PR15 ("我的研究" feed) lands.
- Should there be a server-side cache for rendered PDFs? Probably not
  until we see real read patterns — `art_id → PDF bytes` is easy to add
  later if download latency becomes a complaint.
