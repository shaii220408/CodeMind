# CodeMind — AI-Powered Codebase Intelligence Platform

CodeMind is an AI-powered Codebase Intelligence Platform. It indexes source repositories into PostgreSQL + pgvector, combines semantic and PostgreSQL full-text retrieval with Reciprocal Rank Fusion (RRF), and provides evidence-grounded answers with file and line citations.

## Architecture

React/Vite → FastAPI → Celery/Redis → repository scanner → parser/chunker → Sentence Transformers → PostgreSQL/pgvector

Successful indexing also builds a project-scoped knowledge graph in PostgreSQL. Python uses its standard AST; Java, JavaScript and TypeScript use Tree-sitter for supported static entities and relationships. The explorer includes source locations and direct or bounded transitive impact (up to five levels); unresolved relationships are labeled and ambiguous links are not guessed.

For questions:

React → `POST /api/ask` → semantic + lexical retrieval → RRF → term-overlap reranking → evidence threshold → grounded answer and citations.

## Run locally

1. Install Docker Desktop.
2. Create `.env` from `.env.example` if it does not exist. Set the LLM key only in this backend environment file; do not add it to frontend variables or commit `.env`.
3. Run:

```bash
docker compose up --build
```

4. Open `http://localhost:5173`.
5. Register an account, create a project, and upload a ZIP repository.
6. Wait for `COMPLETED` and ask questions.

FastAPI docs: `http://localhost:8000/docs`

## Gemini configuration

The backend uses Google's official `google-genai` Python SDK to call Gemini `generateContent`. Set `GEMINI_API_KEY` in the project-root `.env`; it is passed only to the API container, never to the React/Vite frontend or indexing worker. `GEMINI_MODEL` defaults to `gemini-3.8-flash`. With an empty key, CodeMind uses the deterministic evidence-only fallback. Each Gemini request is bounded by GEMINI_TIMEOUT_SECONDS (default 30 seconds; valid range 5–120 seconds). After changing the key or model, run `docker compose up -d --build api worker`. Gemini authentication, model, quota/rate-limit, timeout, connection, and server errors remain explicit API errors.

## Supported languages

Java, Python, JavaScript, TypeScript. Tree-sitter syntax checks are available for Python, JavaScript, and TypeScript; Java uses the regex fallback. Chunk extraction is symbol/line based rather than full AST semantic extraction. See [architecture](docs/architecture.md) and [known limitations](docs/security-and-limitations.md).

## Security and operations

- Account registration and login issue opaque bearer sessions. Passwords use salted scrypt hashes; session tokens are stored hashed and expire after `AUTH_TOKEN_TTL_DAYS`.
- Projects and chat history are scoped to their owner. Projects created before accounts were introduced are claimed by the first account registered.
- Redis enforces per-IP request limits: 10 auth, 5 upload, 30 ask, and 120 other API requests per minute. Redis is required for readiness.
- ZIP extraction rejects traversal paths and symlinks and enforces `MAX_UPLOAD_MB` and `MAX_ARCHIVE_FILES`.
- Docker publishes API, frontend, PostgreSQL, and Redis ports on loopback only.
- Alembic upgrades run before the API starts. PostgreSQL and Redis have healthchecks; API readiness checks both dependencies.
- `/metrics` exposes Prometheus request counts and latency. Account, project, indexing, and query events are written as structured JSON logs without passwords, tokens, or query text.
- GitHub Actions runs backend tests, migrations, `pip-audit`, the frontend production build, and `npm audit`.

Before exposing this development stack to the internet, configure HTTPS, a managed secret store, email verification and password recovery, malware scanning, and stronger isolation for untrusted repositories.

## API

- `POST /api/auth/register` and `POST /api/auth/login`
- `GET /api/auth/me` and `POST /api/auth/logout`
- `POST /api/projects`
- `GET /api/projects`
- `POST /api/projects/{project_id}/upload`
- `POST /api/projects/{project_id}/index`
- `GET /api/projects/{project_id}/status`
- `POST /api/ask`
- `GET /api/projects/{project_id}/dependencies`
- `GET /api/projects/{project_id}/dependencies/search?q=...`
- `GET /api/projects/{project_id}/impact?path=...`
- `GET /api/projects/{project_id}/history`
- `GET /api/projects/{project_id}/source?path=...&start_line=...&end_line=...`
- `POST /api/projects/{project_id}/sync?branch=...` (public GitHub repositories only)
- `DELETE /api/projects/{project_id}`
- `GET /api/projects/{project_id}/files`
- `GET /api/projects/{project_id}/overview`
- `GET /health`
- `GET /ready`
- `GET /metrics`

## Sample repository

`sample_repo/` contains a tiny Java/Python repository. Zip that folder and upload it to test questions such as:

- Where is retry logic implemented?
- Which component publishes notifications to Kafka?
- Explain AuthService.
- What files import or depend on NotificationService?

## Knowledge graph and GitHub sync

The project graph extracts Python AST facts and Tree-sitter entities/relationships for Java, JavaScript and TypeScript. It includes source locations, relationship resolution state, search/filtering, zoom/pan, node details, source viewing and bounded direct/transitive impact. Static results are incomplete when names are ambiguous, dynamically dispatched, overloaded, reflected, or external; unresolved references are kept unresolved.

Create a project with an optional public HTTPS GitHub repository URL, then select **Sync repository** to fetch the chosen/default branch. Each sync downloads a size- and file-bounded ZIP snapshot (not a Git clone or webhook). Successful indexing records branch and commit SHA. Index tables are replaced atomically for the active project generation, so a failed snapshot index leaves the last successful index in place. Private GitHub repositories are not supported; never put a token in the repository URL. See [security and limitations](docs/security-and-limitations.md).

## Project review, health, and documentation

The project page includes **Review**, **Health**, and **Documentation** panels. A successful index increments `index_revision`; static analysis and generated documents are stored against that revision. Start scans and documentation generation explicitly from the UI, then revisit the panels to read cached results. Static findings identify rule-matched patterns and are not proof that a vulnerability is exploitable. AI explanations are opt-in per finding and send only its redacted excerpt. Documentation is generated from indexed source and graph facts; setup commands are copied only when found in README text, and missing information is labeled as unknown. Coverage remains unavailable unless reliable coverage data is later integrated.

Analysis API: `GET /api/projects/{project_id}/analysis`, `POST /api/projects/{project_id}/analysis/scan`, `POST /api/projects/{project_id}/analysis/explain/{finding_id}`. Documentation API: `GET /api/projects/{project_id}/docs/generated`, `POST /api/projects/{project_id}/docs/generate`, `GET /api/projects/{project_id}/docs/generated/{document_id}`, and `/export` for Markdown download. All routes require project ownership.

## Testing

Backend tests (inside the API container):

```bash
docker compose exec -T api python -m pytest -q
```

Frontend checks (run from `frontend/`):

```bash
npm ci
npm test
npm run build
```

CI also runs database migrations, `pip-audit`, and `npm audit`. The latest live Gemini checks produced intermittent upstream HTTP 503/504 responses for grounded prompts. Generation correctness and citation metrics therefore remain unscored; retrieval-only metrics are recorded separately in `reports/evaluation-results.json`.

## Retrieval evaluation

Run the labelled sample-repository benchmark with an account bearer token:

```bash
python benchmarks/evaluate.py --project-id <project-id> --token <access-token>
```

The report includes Recall@K, MRR, distinct-file citation accuracy, answer citation coverage, warmed latency percentiles, and first-request warmup latency.

## Project documentation

- [Feature inventory and readiness](docs/feature-inventory.md)
- [Architecture and data flow](docs/architecture.md)
- [API reference](docs/api.md)
- [Testing and evaluation](docs/testing.md)
- [Security and limitations](docs/security-and-limitations.md)
- [Viva preparation](docs/viva.md)
- [Demo script](docs/demo.md)

## Project tree

```text
CodeMind/
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
│   └── tests/
├── frontend/
├── postgres/init/
├── sample_repo/
├── .env.example
├── docker-compose.yml
└── README.md
```
