# CodeRAG — AI-Powered Codebase Assistant

CodeRAG is a full-stack developer tool that indexes source repositories with code-aware chunks, stores embeddings in PostgreSQL + pgvector, combines semantic and PostgreSQL full-text retrieval using Reciprocal Rank Fusion (RRF), and produces source-grounded answers with file/line citations.

## Architecture

React/Vite → FastAPI → Celery/Redis → repository scanner → parser/chunker → Sentence Transformers → PostgreSQL/pgvector

For questions:

React → `POST /api/ask` → semantic retrieval + lexical retrieval → RRF → retrieved-file dependency context → OpenAI-compatible LLM or deterministic fallback → citations.

## Run locally

1. Install Docker Desktop.
2. Copy `.env.example` to `.env` and optionally set `LLM_API_KEY`.
   For local use, replace the sample database password and keep `POSTGRES_PASSWORD` and the password inside `DATABASE_URL` in sync.
3. Run:

```bash
docker compose up --build
```

4. Open `http://localhost:5173`.
5. Create a project and upload a ZIP repository, or enter a public HTTPS GitHub, GitLab, or Bitbucket URL when creating the project. Repository URLs are shallow-cloned with submodules disabled. Re-indexing a URL-backed project fetches the latest snapshot.
6. Wait for `COMPLETED`, open a citation to inspect its source lines, and ask questions. Existing indexed source can be re-indexed asynchronously with `POST /api/projects/{project_id}/index`.

FastAPI docs: `http://localhost:8000/docs`

The Compose frontend is a production Vite build served by Nginx; Nginx forwards `/api` requests to FastAPI. For frontend-only development outside Compose, run `npm install` and `npm run dev` from `frontend/` with `VITE_API_URL=http://localhost:8000` so the development server calls the separately running API.

## LLM configuration

The app uses an OpenAI-compatible API when `LLM_API_KEY` is configured. `LLM_BASE_URL` and `LLM_MODEL` are configurable. Without an API key, the application uses a deterministic evidence-only fallback and explicitly labels it.

## Supported languages

Java, Python, JavaScript, TypeScript. Tree-sitter extracts symbol node boundaries and imports when parsing succeeds; malformed files use a line/symbol fallback. Java, Python, JavaScript, and TypeScript grammars are installed by the backend requirements.

## Security

Implemented: ZIP traversal protection, upload size limits, supported-source filtering, ignored dependency/build directories, allowlisted public HTTPS Git sources, project-scoped retrieval, optional API bearer-key protection, Redis-backed limits on uploads/indexing/questions/dependency analysis, environment-based secrets, parameterized lexical SQL, and a prompt that treats repository text as untrusted evidence. Set `API_ACCESS_TOKEN` in `.env` to a random secret of at least 32 characters to require authentication; the UI prompts for it and keeps it in the current browser session. Leaving it blank keeps the intended local-development mode unauthenticated.

Production hardening still required before internet exposure: user identity and per-project authorization, HTTPS, malware scanning, a secret manager and key rotation, audit logging, stronger rate limiting, and sandboxing for untrusted repositories. Compose binds all published ports to loopback by default; use an explicit deployment override before exposing services remotely.

## API

- `POST /api/projects`
- `GET /api/projects`
- `POST /api/projects/{project_id}/upload`
- `POST /api/projects/{project_id}/index` (refreshes URL-backed repositories or reprocesses stored source)
- `GET /api/projects/{project_id}/status`
- `POST /api/ask`
- `GET /api/projects/{project_id}/dependencies`
- `GET /api/projects/{project_id}/impact?target=ClassName`
- `GET /api/projects/{project_id}/files`
- `GET /api/projects/{project_id}/files/{document_id}`
- `GET /api/projects/{project_id}/overview`
- `GET /health`
- `GET /ready`

The dependency endpoint accepts an optional `?target=ClassName` filter, returns source paths and symbols with import/class-reference edge types, and supports `limit`/`offset` pagination. Dependency and impact queries are Redis rate-limited. `GET /api/projects/{project_id}/impact?target=ClassName` matches an indexed file or symbol and follows extracted dependency edges in reverse, returning direct and transitive affected files (bounded to 200).

## Sample repository

`sample_repo/` contains a tiny Java/Python repository. Zip that folder and upload it to test questions such as:

- Where is retry logic implemented?
- Which component publishes notifications to Kafka?
- Explain AuthService.
- What files import or depend on NotificationService?

## Testing

Inside the backend container:

```bash
pytest -q
```

The test suite covers parser behavior and chunk bounds, ZIP traversal/source filtering/size limits, URL validation, API contracts, PostgreSQL/pgvector hybrid retrieval, dependency search and transitive impact, RRF ranking, benchmark metric calculations, grounded fallback answers, and rate-limit policy. A PostgreSQL-backed end-to-end test exercises ZIP upload, queued Celery indexing, dependency search, and cited ask using deterministic test embeddings. Run `docker compose exec api pytest -q` with the stack running. GitHub Actions runs frontend build, the full PostgreSQL/Redis-backed test suite, and Python/npm dependency audits.

Run the sample benchmark after the stack is up; it creates a benchmark project, uploads `sample_repo/`, waits for indexing, asks the benchmark questions, and writes a JSON report with Recall@K, MRR, citation accuracy, indexing latency, and query latency:

```bash
docker compose exec api python -m benchmarks.evaluate --output /tmp/coderag-benchmark.json
```

The report includes each answer and its evidence. Groundedness is deliberately left for manual review; rate each answer 0 (unsupported), 1 (partially supported), or 2 (well supported) instead of treating citation presence as proof of grounding.

Database schema changes are managed by Alembic in `backend/migrations/`. On startup, a fresh database is migrated to head. A complete schema created by older CodeRAG versions is stamped as the initial revision before subsequent upgrades; partial unversioned schemas fail closed for manual inspection.

## Project tree

```text
CodeRAG/
├── backend/
│   ├── app/
│   │   ├── api/routes.py
│   │   ├── core/config.py
│   │   ├── db/{session.py,init_db.py}
│   │   ├── models/models.py
│   │   ├── parsers/code_parser.py
│   │   ├── retrieval/hybrid.py
│   │   ├── services/{embedding.py,ingestion.py,llm.py}
│   │   ├── tasks/celery_app.py
│   │   └── main.py
│   ├── tests/
│   ├── migrations/
│   └── benchmarks/
├── frontend/
├── postgres/init/
├── sample_repo/
├── .env.example
├── docker-compose.yml
└── README.md
```
