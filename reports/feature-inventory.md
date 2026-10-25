# CodeMind feature inventory — 2026-10-25

Status reflects evidence from this audit, not the presence of a screen or route.

| Area | Status | Evidence / limits |
|---|---|---|
| Authentication | PASS (basic flow) | Browser registration, login, authenticated workspace and logout were exercised with a synthetic account. Project ownership checks and backend auth tests are present. Logout now resets the auth mode and clears email/password. |
| Projects and upload/indexing | PASS (sample flow) | A disposable project accepted a safe two-file Java source archive; indexing completed with 2 documents and 4 chunks. Temporary repository/project removed after evaluation. |
| API, database, worker | PASS (audit snapshot) | API readiness 200, Celery ping pong, compose services running, Alembic current=head `0007_review_health_docs`. |
| Repository Explorer/source | PARTIAL | Source files and line ranges used by retrieval were checked. Full file-search and all citation-click paths were not browser-tested in this pass. |
| AI Q&A / Gemini | PARTIAL / BLOCKED | Retrieval succeeded, but real Gemini requests returned HTTP 504. No `llm` response/citation correctness score can be claimed. Unsupported question produced true abstention with zero citations and persisted history. |
| Retrieval evaluation | PASS (retrieval-only) | 50 labelled questions: Recall@5 0.9706 and MRR 0.9265 on 34 answerable items. Full metrics and caveats in `evaluation-results.json`. |
| Knowledge Graph / impact | PARTIAL | Backend tests passed; end-to-end node search, filters, zoom, direct/transitive impact and navigation were not all browser-tested here. |
| Code Review / Health / Docs | PARTIAL | Backend and frontend automated coverage exists; actual scan/generation/export workflows and metric provenance were not browser-exercised in this pass. |
| GitHub sync / history | PARTIAL | Persistent abstention history was verified. Live GitHub sync, failure/retry and commit tracking were not exercised. |
| UI console | PASS (checked state) | No browser console error entries were returned after the login/logout flow. |
| Responsive layouts | NOT VERIFIED | Requested 1366x768, 1920x1080 and narrow viewport visual checks were unavailable in the current browser-control workflow. |
| CI/audit/lint | PARTIAL | Backend tests and frontend test/build ran. No frontend lint/typecheck scripts are configured; CI audit jobs were not executed in this pass. |

## Highest-priority gaps

1. Gemini provider availability: real requests returned 504, so generation, citations, and answer quality remain unverified.
2. Complete browser E2E for graph, review, health, documentation, GitHub sync, and responsive sizes.
3. Reliability and semantic evaluation should be rerun when Gemini responds successfully; retain abstention and citation checks.
4. Review upload symlink handling and add/confirm an explicit regression test if absent.
5. Improve retrieval for absent questions that still receive above-threshold evidence (4 of 16 in this evaluation proxy).

## Follow-up verification — 2026-10-25

| Area | Updated status | New evidence / limits |
|---|---|---|
| Gemini live generation | BLOCKED | Minimal real Gemini request returned 503; real grounded request returned provider HTTP 504 before the configured 30-second local SDK timeout. No `llm` answer or generated citation. `.env` untouched and key only checked for presence. |
| Knowledge Graph | PASS (tested Java sample UI/API) | 9 nodes/9 edges; search and source path/lines verified; graph controls/empty state checked at 1366×768, 1920×1080 and 390×844. Java function-call resolution remains incomplete. |
| Impact analysis | PARTIAL | API works and reports `completeness: partial`; unresolved Java calls are explicitly not guessed. Direct relationships are sparse; transitive Java impact not verified. |
| Code Review | PASS (empty scan) | Real scan completed with zero configured-rule findings; UI does not equate zero findings with safe code. |
| Codebase Health | PASS (Java sample) | Actual file/line/class/module/language/review/hotspot/duplicate metrics checked. Python complexity and test coverage are unavailable for this corpus. |
| Documentation | PASS (generation/preview/export) | Six generated docs; preview and Markdown export succeeded. API docs correctly reflect no reliably identified routes in Java sources. |
| GitHub sync | PASS (public API/worker) | `octocat/Hello-World` synced on `master`; status and commit SHA recorded. UI button path and private repos not tested. |
| History | PASS (abstention) | Unsupported question reloads with abstention mode and no citations; LLM-mode history is blocked by provider failure. |
| Browser ZIP upload | NOT VERIFIED / observed failure | UI showed “Failed to fetch”; only OPTIONS reached API. Direct API upload/index succeeded; frontend/browser root cause remains open. |
| Responsive visual QA | PASS (targeted) | Overview and empty graph at 1366×768, 1920×1080, 390×844; populated graph/source at 1920×1080. Targeted fixes covered graph empty state/controls and existing-index copy. Not every route was checked at every size. |
| Worker recovery/concurrency | NOT VERIFIED live | No repeated duplicate/concurrent/failure injection in this pass. Backend suite passed. |
| Synthetic visual-QA data cleanup | BLOCKED | Automatic safety review rejected deleting the exact test account/project; it was preserved. Explicit authorization is needed before cleanup. |

Backend tests after code changes: 63 passed, 156 warnings. Frontend tests: 4 files / 11 tests passed. Production build passed. Full evidence and metrics are in `final-report.md` and `live-workflow-results.json`.

## Stabilization update — 2026-10-25

| Area | Current status | Evidence / limitations |
|---|---|---|
| Gemini grounded generation | BLOCKED / intermittent | Minimal real request was HTTP 200 in 7.06s; grounded CodeMind request HTTP 504 in 33.98s; live UI request saw upstream 503s. Model/key worked for minimal prompt. Errors are upstream HTTP responses, not local SDK timeouts. Generation metrics remain null. |
| Gemini transient handling | PASS | At most one 0.5s-backoff retry for 500/502/503 within the UI deadline budget; no retry for 429/504, auth/client errors, connection failures or local timeout. Unit and live 503 sequence verified. |
| ZIP upload/CORS | PASS after fix | PNA preflight previously returned Starlette 400 `Disallowed CORS private-network`; explicit localhost origin allowlist now allows PNA. Active 5174 UI upload: OPTIONS 200, POST 200, worker completed 2 files/4 chunks. Full DevTools request headers unavailable; direct PNA probe recorded. |
| Java call graph/impact | PASS for tested static imported type chain; otherwise PARTIAL | Receiver now preserved (`Base.leaf`); explicit unique imported-type method resolution works. Synthetic three-file API test returns direct `Middle.run` and depth-2 `Top.execute`. Dynamic/instance inference and overloads remain unresolved. |
| GitHub UI sync | PASS (sync metadata) | UI + real worker synced public `octocat/Hello-World`; branch master and commit SHA recorded; 0 supported source files in that repo. |
| Q&A cancellation/duplicate | PASS same tab | Stop waiting exits spinner; Ctrl+Enter did not duplicate the in-flight request. Server generation may continue after browser abort. Cross-tab concurrency and manual Retry click not verified live. |
| Graph/review/health/docs | Prior evidence retained | Not repeated because recent reports already contain the browser/API evidence and those components were unchanged. Successful-answer citation navigation remains blocked by Gemini generation failure. |
| Regression | PASS | 67 backend tests passed; 11 frontend tests passed; production build passed. 169 backend deprecation warnings remain. |

No retrieval numbers were relabeled as generation accuracy. Synthetic QA data remains preserved.
