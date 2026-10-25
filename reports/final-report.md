# CodeMind audit and evaluation report — 2026-10-25

## Summary

The existing CodeMind app was inspected and exercised without replacing its stack. The main observed “Thinking…” issue was traced to the real Gemini request, not browser CORS or the API base URL: retrieval completed, while Gemini returned HTTP 504. The old provider timeout was 120 seconds and the assistant had no stop/retry controls. Gemini timeout is now configurable, defaults to 30 seconds, and frontend requests are bounded with cancellation, duplicate-submit protection, explicit retry feedback, and loading cleanup. No successful hosted generation was observed.

A fresh 50-question dataset was grounded in two actual sample repository Java files. Retrieval-only scores were measured; semantic and citation scores remain blocked rather than being treated as failures or successes.

## Evidence and statuses

| Workflow / check | Status | Evidence |
|---|---|---|
| Registration | PASS | Browser created a synthetic QA account and navigated into its workspace. |
| Valid login | PASS | The synthetic account logged in and reached the authenticated project workspace. |
| Logout | PASS | Sign out returned to the default sign-in screen with blank email/password fields. |
| Authorization | PASS (automated) | Backend authorization tests passed in the full backend suite; no second-user project-crossing browser scenario was run. |
| Upload and indexing | PASS | Safe sample upload indexed 2 Java files into 4 chunks; job completed. |
| Readiness / worker / migration | PASS (audit snapshot) | API `/ready` 200; Celery ping `pong`; migration current and head `0007_review_health_docs`; compose services were running during audit. |
| Grounded answer from live Gemini | BLOCKED | Real request and a separate minimal provider probe both returned HTTP 504. No `answer_mode=llm`, generated citation, or successful-provider assertion is claimed. |
| Unsupported question | PASS | An absent question returned `abstention`, the insufficient-evidence message, and zero citations. |
| Chat history | PASS (abstention case) | History page reloaded the saved question, abstention mode and zero citations. LLM history could not be tested because Gemini generated no answer. |
| Retrieval benchmark | PASS (retrieval only) | 50 questions; 34 answerable and 16 unanswerable. Recall@5 0.9706 and MRR 0.9265 are over answerable questions only. Unanswerable above-threshold abstention proxy: 0.75 (12/16). Retrieval latency: mean 128.8 ms, p50 15.7 ms, p95 21.2 ms; mean includes the 5.5s cold retrieval/model load. |
| Frontend tests | PASS | 4 files, 10 tests passed, including logout reset regression. |
| Frontend production build | PASS | Vite 8.3.5 production build succeeded. |
| Backend tests | PASS | `docker compose -f <project-root>\docker-compose.yml exec -T api python -m pytest -q`: 63 passed, 156 warnings (deprecation warnings). This ran before the frontend-only logout change. |
| Browser console | PASS (checked flow) | No console errors returned for the login/logout session. |
| Other feature browser flows | NOT TESTED | Graph interactions, review scan findings, health metric values, documentation export/regeneration, GitHub sync and retry/failure states were not all exercised in browser in this pass. |
| Responsive visual QA | NOT VERIFIED | 1366x768, 1920x1080 and narrow viewport checks were not performed. |

## Evaluation limitations

- `evaluation-questions.json` contains 50 questions with repository-based expected evidence and scoring criteria; `evaluation-manifest.json` records source hashes and line counts.
- `evaluation-results.json` records retrieval result/rank/latency per question. The temporary evaluation project identifier was removed from the report after cleanup.
- Correctness, groundedness, citation precision/coverage and unsupported-question API accuracy are `null` because Gemini returned HTTP 504 before an answer was produced. These are blocked, not zero and not a model score.
- The corpus used two safe Java files; a credential-like demo file was excluded. Results do not establish multilingual or large-repository performance.
- Four of 16 absent questions retrieved evidence above the existing 0.45 floor. This is a retrieval-risk signal, not a measured API abstention defect.

## Changes made in this audit

- Backend Gemini timeout now uses `GEMINI_TIMEOUT_SECONDS`, defaults to 30 seconds, and validates 5–120 seconds.
- `.env.example`, README, and grounding tests document/check the timeout setting. The real `.env` was not read into output or changed.
- Frontend Q&A now has a bounded request, cancellation, single-flight guard, retry feedback, and guaranteed cleanup. A stop-waiting control is exposed during generation.
- Logout resets to sign-in mode and clears credential form fields; a focused frontend regression test covers this behavior.
- Added the 50-question evaluation set, manifest, retrieval results, audit baseline and feature inventory under `reports/`.

## Remaining actions

1. Retry the hosted Gemini integration when the provider stops returning HTTP 504, then score real answers, citations, history and error classes.
2. Complete browser workflows for graph/impact, review, health, documentation, GitHub sync and responsive viewports.
3. Add a reliable CI frontend audit/lint check if desired; this frontend currently exposes test/build scripts, not lint/typecheck scripts.
4. Complete explicit upload-symlink regression verification and address retrieval false positives noted above.

No API key, password, or other environment secret is included in these reports.

## Follow-up audit — 2026-10-25

### Priority 1: Gemini 504 diagnosis

- **Provider/configuration:** Gemini via the official `google.genai` SDK; current configured model `gemini-3.8-flash`, 30-second SDK timeout, and API key presence was checked as a boolean only. The project-root `.env` was neither changed nor printed.
- **Provider reachability:** a minimal real request without deprecated sampling parameters received Google API HTTP 503 in 3.41 seconds. A real CodeMind grounded request reached `generativelanguage.googleapis.com` and returned HTTP 504; the API surfaced a sanitized 504 service error. Earlier instrumented timing on a warmed request was retrieval 5.906 seconds and generation 29.027 seconds; total 34.95 seconds. A later cold request took 66.973 seconds end-to-end because local embedding initialization was included, then the Gemini call returned 504 at approximately 29 seconds.
- **Conclusion:** the observed 504 is an upstream Gemini HTTP response before the configured 30-second local SDK timeout, not the local timeout handler. Retrieval is not the dominant latency on the warmed request. Provider availability/capacity or account quota/access remains unresolved; the response does not establish an invalid key. No real answer was generated and no live citations were verified.
- Removed the deprecated `temperature=0` request parameter and updated its regression assertion. This is compatible with current Gemini 3.6+ request guidance; it did not resolve the upstream 503/504.

### Priority 2: remaining feature workflows

| Feature / scenario | Status | Evidence and limits |
|---|---|---|
| Safe repository index | PASS (API/worker) | Two safe Java files indexed through the actual API and Celery worker; 2 documents, 4 chunks, completed job. |
| Knowledge Graph | PASS (graph/source/search UI) | 9 nodes and 9 edges persisted. Search found `retryNotification` in `src/NotificationService.java`, lines 7–11; node details and source viewer showed those lines. Empty graph, search, zoom and fit controls were visually checked. |
| Dependency / direct impact | PARTIAL | API returned HTTP 200 with `completeness: partial`. Java calls to `println` and `publish` remained unresolved and were omitted from resolved direct dependents/callers. No inferred edges were presented as certain. Transitive Java impact is not established. |
| Code Review | PASS (empty real scan) | Scan completed against indexed files with 0 findings. UI correctly states no configured rule matched and does not claim the code is risk-free. |
| Codebase Health | PASS (available metrics) | 2 files, 16 source lines, 2 classes, 2 modules, Java distribution 2; 0 review findings, no dependency hotspots, 0 duplicates. Python complexity and coverage were correctly unavailable (Java-only corpus/no reliable coverage artifact). |
| Documentation | PASS (API workflow and export) | Generation completed with six actual docs (API, architecture, two module docs, overview, setup); preview returned 200 and Markdown export returned 200 (`text/markdown`, 221 bytes). API route discovery correctly reported none for this Java-only corpus. Browser downloaded `api-project.md`. |
| GitHub sync | PASS (public repo API/worker) | Public `octocat/Hello-World`, branch `master`, synced through the real Celery worker; status `SYNCED` and commit SHA present. Private repository credentials were not used. Browser sync-button interaction was not tested. |
| Chat history | PASS (abstention case) | Unsupported question persisted and reloaded with `answer_mode=abstention` and zero citations. LLM-mode history remains unverified because Gemini returned no answer. |
| Empty/failure states | PARTIAL | Empty graph, review, health, docs, impact and history states were observed. Local snapshot sync failure returned HTTP 400 when unconfigured. Browser ZIP upload showed “Failed to fetch”; browser network evidence contained only OPTIONS 200 and no POST, while direct API upload/index succeeded. The browser upload failure cause remains unresolved. |
| Retry/concurrency/failed indexing | NOT VERIFIED in this follow-up | No new destructive or duplicate job experiment was run. Existing backend regression coverage passed, but it is not evidence of every live worker scenario. |

The two earlier audit projects were deleted through the project API after evaluation. A later synthetic empty project/account created for visual testing could not be removed: the automatic safety reviewer rejected the cleanup because account/project deletion is irreversible and there was no explicit authorization for that exact deletion. It was preserved; no alternative deletion path was attempted.

### Priority 3: generation evaluation

The 50-question set was **not rerun for generation** because the real provider returned 503/504. Existing retrieval-only measurements remain separate: Recall@5 0.9706 and MRR 0.9265 on 34 answerable questions. Correctness, groundedness, citation precision/coverage, unsupported-question handling accuracy, generation latency distribution, and generation failure rate remain unscored/null. No overall AI accuracy is reported.

### Priority 4: browser visual checks

Actual browser viewport checks were performed at 1366×768, 1920×1080, and 390×844. Overview and empty graph layouts were inspected at all three sizes; the populated graph and source detail were inspected at 1920×1080. No horizontal overflow or text clipping was observed in those screens. Two confirmed UI defects were fixed: empty graph displayed “Loading” after loading, and graph controls/count labels were poorly styled/spaced. Existing-index upload copy was also corrected so it no longer claimed the first index was missing. Regression tests cover these changes. This was targeted visual QA, not a full pixel-level inspection of every route at every viewport.

### Regression checks after fixes

- Backend: `docker compose -f <project-root>\docker-compose.yml exec -T api python -m pytest -q` — **63 passed, 156 warnings**, 3.70s.
- Frontend: Vitest — **4 files, 11 tests passed**; Vite production build — **passed**.
- Runtime: API `/ready` — 200; database and Redis healthy; Celery ping — `pong`; Alembic at `0007_review_health_docs (head)`.
- No `.env` changes, secret values, commits, or pushes were made.

### Remaining blockers / next actions

1. Check Gemini AI Studio usage/quota, model access and provider status; retry a minimal request and the grounded request only after service availability changes. Then run the 50-question generation/citation evaluation.
2. Diagnose the browser ZIP upload’s missing POST separately; the API/worker ingestion path itself passed.
3. Add/verify Java symbol resolution and transitive impact before calling impact analysis complete.
4. Exercise GitHub sync in the UI and live worker retry/concurrent-index failure paths.
5. Request explicit approval before removing the preserved synthetic visual-QA account/project; the automatic reviewer rejected deletion.
6. Symlink-upload regression remains unverified.

## Stabilization follow-up — 2026-10-25

### Priority 1 — Gemini provider and retry behavior

- Safe configuration check: provider Gemini, model `gemini-3.8-flash`, SDK timeout 30 seconds, key configured (boolean only). No key or `.env` value was read into output; `.env` was not changed.
- Real minimal provider request: **HTTP 200**, 7.06 seconds, response present. This establishes that the configured credentials/model can answer a small prompt at that time.
- Real grounded CodeMind request through `/api/ask`: **HTTP 504** after 33.98 seconds end-to-end. Sanitized API detail indicated Gemini had not finished before the request deadline. Earlier instrumented request measured retrieval 5.906s and generation 29.027s (34.95s total); a later cold request also included local embedding initialization. Google’s request log records HTTP 504 before the configured 30-second SDK timeout handling would raise a local timeout exception. This is an upstream response, not a locally raised SDK timeout.
- A live browser Q&A attempt on the indexed sample was stopped by the user-facing Stop waiting control. Gemini logged two upstream HTTP 503 responses 6.51 seconds apart for that request sequence; the UI exited loading and showed the cooldown message. No answer/citations were returned.
- Provider logs expose status and endpoint only; the service intentionally drops provider response bodies. No 429/quota-specific signal was observed. A minimal 200 and grounded 503/504 indicate intermittent/provider workload behavior, not proof of invalid credentials or missing model access. Quota/availability dashboards were not accessible from this API integration, so remaining provider cause is unresolved.
- Added one bounded retry for transient 500/502/503 only, with 0.5s backoff, at most one retry, and only when the remaining budget fits the 39s UI response window. HTTP 429, 504, auth/client failures, connection errors and local timeouts are not retried. Tests verify one retry for 503 and no retry for 429/504. The live UI sequence confirmed the 503 retry; no successful grounded generation was observed. The separate post-error Retry question button was not clicked to avoid further provider calls while failures persisted.

### Priority 2 — browser ZIP upload root cause

- Browser testing was performed against the active Vite frontend at `http://localhost:5174` (the earlier Compose frontend at 5173 is a separate build).
- A browser-equivalent preflight carrying `Access-Control-Request-Private-Network: true` reproduced Starlette’s exact `400 Disallowed CORS private-network` response before the fix, despite the ordinary allowlisted origin/method/header checks succeeding. Added `allow_private_network=True` while retaining the explicit localhost origin allowlist. The corrected preflight returned 200 with `Access-Control-Allow-Private-Network: true`.
- Actual active-frontend upload then produced `OPTIONS 200` followed by `POST /api/projects/.../upload 200`; the Celery index task completed. The UI showed COMPLETED with 2 Java files and 4 chunks. Browser console error/warning log was empty.
- The browser automation exposes console logs and the API’s access log, but not the complete DevTools Network request-header pane. Thus the PNA defect is directly reproducible and fixed, while the original failing browser request’s exact `Access-Control-Request-Private-Network` header was not independently captured. The original ZIP was retried from an accessible workspace path; the active Vite upload was verified with that safe sample ZIP.

### Priority 3 — Java impact analysis

- A parser probe confirmed the Tree-sitter extractor discarded the receiver from Java `Base.leaf()` calls, recording only `leaf`; cross-file callers could not resolve.
- Java method invocations now retain their receiver. Index-time linking resolves a call only when its receiver is an explicitly imported type and the matching local method is unique. A synthetic three-file Java chain was indexed and queried through the graph impact API: direct caller `impact.Middle.run` at depth 1 and transitive caller `impact.Top.execute` at depth 2 both resolved as `inferred`.
- Instance-variable type inference, overload ambiguity, reflection, dynamic dispatch, external library targets, and runtime call proof remain unsupported; those relationships stay unresolved rather than guessed. Impact response wording now describes static/incomplete links without incorrectly claiming Python-only behavior.

### Priority 4 — live UI workflows

| Scenario | Status | Evidence |
|---|---|---|
| ZIP upload/index on active Vite frontend | PASS | UI upload, OPTIONS/POST access logs, Celery completion, 2 files/4 chunks. |
| GitHub sync through active UI | PASS (sync) | Public `octocat/Hello-World` queued through the UI; worker completed in 1.62s; UI reported `SYNCED`, branch `master`, commit `7fd1a60b01f91b314f59955a4e4d4e80d8edf11d`. It contained 0 supported source files, so this validates sync metadata/workflow, not a nonempty code index. |
| Q&A cancellation | PASS | Stop waiting exited the spinner, surfaced the stopped message, and disabled retry during the cooldown; backend work may continue after client cancellation. |
| Same-tab duplicate prevention | PASS | Ctrl+Enter during the in-flight request did not start another `/api/ask` sequence. The backend made the bounded transient retry for the single request. |
| Cross-tab concurrent asks | NOT VERIFIED | No second concurrent hosted call was issued while Gemini was returning 503/504. |
| Manual Retry question click | NOT VERIFIED live | Retry control and cooldown behavior were visible; automatic transient retry was live/tested. No extra hosted calls were made solely to click the manual retry control. |
| Graph, review, health and documentation UI | NOT REPEATED | Prior report already contains browser evidence for these routes; no change to those components in this follow-up. Citation opening from a successful Gemini answer remains blocked because no grounded answer was returned. |

### Regression checks

- Full backend suite: `docker compose -f <project-root>\docker-compose.yml exec -T api python -m pytest -q` — **67 passed, 169 warnings**, 4.75s. Warnings are existing Pydantic/SQLAlchemy deprecations.
- Frontend `npm test` — **4 files, 11 tests passed**.
- Frontend `npm run build` — **passed** (Vite 8.3.5).
- No frontend source was changed in this follow-up. No migration was needed. No `.env` change, secret output, commit, or push.

### Remaining blockers

1. Gemini still does not reliably complete grounded prompts; the live 50-question generation evaluation remains blocked. Keep correctness, groundedness, citation precision/coverage, unsupported-answer accuracy and overall AI accuracy null. Existing retrieval Recall@5 and MRR remain retrieval-only.
2. Verify Google AI Studio quota/service status outside the application if provider 503/504 continues; no quota detail is available from the sanitized SDK logs.
3. Capture the exact PNA header from a full DevTools Network inspector if the original OPTIONS-only failure must be proven at the browser-header level; the API-side preflight reproduction and active UI success are recorded above.
4. Cross-tab concurrent Q&A and a manual Retry question click remain unverified. Preserve all synthetic QA accounts/projects; none were deleted.
