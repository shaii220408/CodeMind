# CodeRAG — AI-Powered Codebase Assistant

CodeRAG is a full-stack developer tool that indexes source repositories with code-aware chunks, stores embeddings in PostgreSQL + pgvector, combines semantic and PostgreSQL full-text retrieval using Reciprocal Rank Fusion (RRF), and produces source-grounded answers with file/line citations.

## Architecture

React/Vite → FastAPI → Celery/Redis → repository scanner → parser/chunker → Sentence Transformers → PostgreSQL/pgvector

For questions:

React → `POST /api/ask` → semantic retrieval + lexical retrieval → RRF → evidence → dependency context → OpenAI-compatible LLM or deterministic fallback → citations.

## Run locally

1. Install Docker Desktop.
2. Copy `.env.example` to `.env` and optionally set `LLM_API_KEY`.
3. Run:

```bash
docker compose up --build
```

4. Open `http://localhost:5173`.
5. Create a project and upload a ZIP repository.
6. Wait for `COMPLETED` and ask questions.

FastAPI docs: `http://localhost:8000/docs`

## LLM configuration

The app uses an OpenAI-compatible API when `LLM_API_KEY` is configured. `LLM_BASE_URL` and `LLM_MODEL` are configurable. Without an API key, the application uses a deterministic evidence-only fallback and explicitly labels it.

## Supported languages

Java, Python, JavaScript, TypeScript. The parser abstraction is designed so additional Tree-sitter grammars can be added later. AST parsing is attempted where available, with a safe line/symbol fallback when parsing fails.

## Security

Implemented: ZIP traversal protection, upload size limits, supported-source filtering, ignored dependency/build directories, project isolation, environment-based secrets, parameterized lexical SQL, safe grounding prompt, and secret-free logs.

Production hardening still required before internet exposure: authentication/authorization, HTTPS, malware scanning, secret manager, audit logging, stronger rate limiting, and sandboxing for untrusted repositories.

## API

- `POST /api/projects`
- `GET /api/projects`
- `POST /api/projects/{project_id}/upload`
- `POST /api/projects/{project_id}/index`
- `GET /api/projects/{project_id}/status`
- `POST /api/ask`
- `GET /api/projects/{project_id}/dependencies`
- `GET /api/projects/{project_id}/files`
- `GET /api/projects/{project_id}/overview`
- `GET /health`
- `GET /ready`

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

The test suite includes parser behavior and ZIP traversal protection. Retrieval and end-to-end tests should be run against a live PostgreSQL/pgvector service for CI.

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
│   └── tests/
├── frontend/
├── postgres/init/
├── sample_repo/
├── .env.example
├── docker-compose.yml
└── README.md
```
