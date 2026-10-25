# CodeMind audit baseline - 2026-10-25

## Repository and runtime

- Active project: C:/Users/sharm_nmsbze9/OneDrive/Desktop. The Desktop root has no Git metadata, so branch/status comparison is unavailable.
- Frontend: Vite at http://localhost:5174. Compose frontend is loopback-bound on 5173. The frontend API client uses http://localhost:8000, matching the Compose API port.
- API readiness passed. PostgreSQL, Redis, API, frontend, and worker containers were running; Celery ping returned pong. Alembic current revision equaled head 0007_review_health_docs. Gemini key presence was checked as a boolean only; no key value was read into output. Model identifier: gemini-3.8-flash.
- Existing inventory and architecture/testing docs are docs/feature-inventory.md, docs/architecture.md, docs/api.md, and docs/testing.md. The existing benchmark had four labelled questions; it was not treated as a fresh score.

## Verified Q&A baseline

- Request path: browser POST /api/ask; project ownership/history checks; retrieve() (pgvector plus PostgreSQL lexical ranking, RRF and lexical rerank; 0.45 evidence floor); answer(); Gemini generateContent; citation construction; chat persistence. The route is synchronous.
- Frontend ask() used fetch without a timeout or AbortSignal. It did have finally cleanup, but no cancellation or explicit retry action. Gemini SDK timeout was 120 seconds.
- In an isolated account/project, actual upload indexing completed for two Java files and four chunks. A browser question showed Thinking, then a sanitized Gemini deadline error. Retrieval for the same question returned the expected Java source ranges in 6.1 seconds in a cold API-side process.
- A separate minimal real Gemini request returned provider HTTP 504 (status only). A key is configured; this is a provider deadline/server availability failure, not missing configuration or frontend fetch/CORS failure. No successful hosted generation was observed.

The confirmed issue is provider-side HTTP 504 after retrieval, amplified by a long 120-second provider timeout and no frontend stop/retry controls. The evaluation data is stored separately; retrieval-only and LLM/citation scores are reported separately so provider unavailability is not misreported as an accuracy failure.
