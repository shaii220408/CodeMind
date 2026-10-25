# API reference (current implementation)

All application routes are under `/api`; protected routes require `Authorization: Bearer <session-token>`. Use `/docs` for the live OpenAPI schema.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | Create account or session |
| GET | `/api/auth/me` | Return current account |
| POST | `/api/auth/logout` | Revoke current session |
| POST / GET | `/api/projects` | Create or list owned projects |
| POST | `/api/projects/{project_id}/sync?branch=...` | Queue a bounded public GitHub snapshot sync |
| DELETE | `/api/projects/{project_id}` | Delete owned project and its upload directory |
| POST | `/api/projects/{project_id}/upload` | Upload ZIP and queue indexing |
| POST | `/api/projects/{project_id}/index` | Legacy route; directs callers to upload first |
| GET | `/api/projects/{project_id}/status` | Read latest indexing status |
| GET | `/api/projects/{project_id}/files` | List indexed files |
| GET | `/api/projects/{project_id}/source?path=...&start_line=...&end_line=...` | Return an owned project's indexed source line range |
| GET | `/api/projects/{project_id}/overview` | File, chunk and language counts |
| GET | `/api/projects/{project_id}/dependencies` | List extracted dependency edges |
| GET | `/api/projects/{project_id}/dependencies/search?q=...` | Search indexed dependency strings |
| GET | `/api/projects/{project_id}/impact?path=...` | Traverse inferred reverse import edges |
| GET | `/api/projects/{project_id}/graph?search=...&limit=...` | Retrieve project-scoped graph nodes and edges (limit 1,000 nodes) |
| GET | `/api/projects/{project_id}/graph/impact?node_id=...&max_depth=1` | Direct callers/dependents for a graph entity |
| GET | `/api/projects/{project_id}/graph/impact?path=...&max_depth=1` | Direct callers/dependents for an indexed file |
| GET | `/api/projects/{project_id}/analysis` | Cached review and health snapshot for the current successful index revision |
| POST | `/api/projects/{project_id}/analysis/scan` | Queue deterministic static review and health analysis |
| POST | `/api/projects/{project_id}/analysis/explain/{finding_id}` | Explicitly request a Gemini explanation for one redacted finding excerpt |
| GET | `/api/projects/{project_id}/docs/generated` | List documentation generated for the current index revision |
| POST | `/api/projects/{project_id}/docs/generate` | Queue deterministic documentation regeneration |
| GET | `/api/projects/{project_id}/docs/generated/{document_id}` | Preview a project-owned generated Markdown document |
| GET | `/api/projects/{project_id}/docs/generated/{document_id}/export` | Download generated Markdown |
| POST | `/api/ask` | Retrieve evidence, answer, and persist history |
| GET | `/api/projects/{project_id}/history` | Return up to 100 user/project messages |
| GET | `/health`, `/ready`, `/metrics` | Liveness, dependency readiness, Prometheus metrics |

`POST /api/projects` accepts optional `repository_url`, restricted to a public HTTPS `github.com/{owner}/{repo}` URL. `/sync` accepts an optional validated `branch`; status returns sync status, branch and commit SHA. Private repositories and webhooks are not supported. Each sync fetches a complete bounded archive, while database replacement is atomic for the current project generation.

`GET /api/projects/{project_id}/impact?path=...` resolves recognized local Python, Java, and relative JavaScript/TypeScript import forms to indexed files when the target is unique, then reports reverse dependents with depth. Ambiguous and external package imports are omitted; use graph impact for the source-ranged, statically resolved Python call/import relationships.

`/api/ask` returns `answer`, `answer_mode` (`llm`, `fallback`, or `abstention`), `evidence_sufficient`, validated `citations`, and `retrieved_sources` when evidence is sufficient. History persists answer mode, citations and their retrieved excerpts. Follow-up context uses recent messages from the same owner and project.

The graph extracts Python, Java, JavaScript and TypeScript entities and source-ranged relations. Unique local declarations and explicit uniquely bound local imports can resolve calls/inheritance; ambiguous/external references remain unresolved. Graph impact defaults to direct relationships. Set `max_depth` from 2 through 5 to follow reverse resolved call/import edges; results include depth. It is static and incomplete for dynamic dispatch, overloads, reflection and external packages.

Review and health responses are scoped to the owner's current `index_revision`. Scans are queued and cached in PostgreSQL; repeated GET requests do not rerun analysis. Findings include rule ID, severity, category, path, line range, sanitized evidence, remediation, and `origin=static_rule`. A rule match confirms only that the pattern was present. Gemini explanations are sent only on explicit request and only include the selected finding's redacted excerpt; returned hypotheses are labeled unconfirmed. Health metrics report graph entity counts and Python-only approximate cyclomatic complexity; coverage is explicitly unavailable. Documentation generation uses indexed file contents and graph relations, stores Markdown with source references and revision, and never infers setup commands absent from README content. Python API routes are identified only for literal route decorators; other route styles are omitted.
