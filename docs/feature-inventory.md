# Feature inventory and readiness

Status meanings: **Implemented** is present in source; **Partial** works with a documented scope or coverage gap; **Missing** is absent; **Not production-ready** exists but needs additional deployment controls or operational validation.

| Area | Status | Evidence / verification |
|---|---|---|
| Account registration, login, logout, bearer sessions | Implemented | `backend/app/api/auth_routes.py`; ownership API tests |
| Per-user project and history isolation | Implemented | owner-scoped routes in `backend/app/api/routes.py`; cross-user API test |
| Project deletion and upload cleanup | Implemented | project DELETE route; delete relies on project cascade for DB rows |
| ZIP traversal, symlink, size and file-count defenses | Implemented | `backend/app/services/ingestion.py`; `test_security.py` |
| Background upload indexing and status | Partial | Celery upload/status present; no worker healthcheck or durable failure dashboard; retry status normalized and queue-failure cleanup regression tested |
| Incremental SHA-256 indexing | Implemented | unchanged content hashes skip embeddings in ingestion service |
| Atomic index replacement / rollback versions | Partial | DB transaction protects each indexing run; no staged index versions or rollback activation |
| Python/Java/JavaScript/TypeScript parsing | Partial | Python AST and Tree-sitter graph extraction for Java/JS/TS; chunk boundaries remain symbol/line based |
| Semantic and lexical retrieval + RRF | Implemented | `backend/app/retrieval/hybrid.py`; relevance floor 0.45 |
| Learned reranking and calibrated confidence | Missing | lexical overlap reranking only |
| Gemini grounded generation / fallback / abstention | Implemented | `backend/app/services/llm.py`; offline provider/grounding tests; prior real Gemini request succeeded, not repeated in this audit |
| Citation validation against current evidence | Implemented | API builds citations from retrieved evidence; grounding tests |
| Persistent answer mode and citation history | Implemented | database-backed chat history route and UI reload |
| Persistent evidence excerpts in history | Implemented | history stores citations and retrieved source excerpts; source route validates project ownership and ranges |
| Dependency search / transitive impact | Partial | heuristic dependency edges and reverse BFS; not compiler-accurate call graph |
| Multi-language static knowledge graph | Partial | Python AST plus Tree-sitter Java/JS/TS entity/import/call/inheritance extraction; uniquely bound relations only; unresolved edges retained; dynamic/overloaded/external resolution is incomplete |
| Graph persistence and project isolation | Implemented | full-snapshot graph rows replaced in the same locked project transaction as the index; duplicate delivery, change/delete, failure rollback and isolation tests |
| Graph API and impact explorer | Partial | owner-checked routes and React SVG explorer with search, relation filters, zoom/pan, node details and source navigation; direct plus bounded five-level static impact |
| Static code review and risk analysis | Partial | revision-scoped Celery scan; deterministic pattern rules, sanitized evidence, severity/category/path filters; rules identify patterns and do not establish exploitability; explicitly requested Gemini explanations are limited to the selected redacted finding |
| Code health dashboard | Partial | cached revision-scoped file/line/language/entity/hotspot/Python-complexity/duplicate/finding metrics; test coverage correctly reports unavailable; metrics are not compiler-complete |
| Documentation drafts and Markdown export | Partial | revision-scoped overview/setup/module/literal-Python-route/graph docs, source references, preview and export; setup commands only copied from README; API route detection and descriptions are incomplete |
| Public GitHub import and sync | Partial | validated public URL/branch, bounded HTTPS archive download and safe extraction, Celery indexing, commit/sync metadata; full archive downloaded each time; no private token or webhook support |
| Health, readiness, DB migrations, basic HTTP metrics and JSON audit logs | Partial | `/health`, `/ready`, Alembic, request metrics; worker health and broader operational metrics absent |
| CI backend tests, frontend build, dependency audits | Implemented | `.github/workflows/ci.yml`; no dedicated frontend unit/e2e tests |
| Internet-facing production deployment | Not production-ready | development DB credentials, no TLS/secrets platform/restore plan/account recovery/malware isolation |

## Release gates

Before real multi-user deployment: replace development credentials, configure TLS and managed secrets, verify backup/restore, run load and worker-recovery tests, add worker health and alerting, decide retention/deletion policy, and complete an authenticated end-to-end flow. Preserve project ownership checks and the 0.45 evidence threshold during that work.

