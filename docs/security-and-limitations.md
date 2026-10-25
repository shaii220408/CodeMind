# Security, deployment boundary, and known limitations

## Implemented controls

- Gemini credentials are backend-only; Compose explicitly blanks the worker's key and the frontend receives no provider secret.
- Passwords use salted scrypt; opaque bearer tokens are stored hashed and expire. Project routes scope reads and writes to the authenticated owner.
- Redis applies per-IP rate limits. ZIP extraction rejects traversal and symlinks and bounds upload size, extracted size and archive file count.
- Service ports bind to loopback. `/ready` checks PostgreSQL and Redis. API errors for Gemini authentication, quota, timeout, network and provider failures are sanitized.
- Structured JSON logs avoid password, token, and question text. Audit events are emitted for key account/project/index/query actions.
- Public GitHub imports accept only canonical HTTPS `github.com/{owner}/{repo}` URLs. Sync uses bounded API/archive timeouts, validates branch names, limits metadata and archive sizes/file counts, checks archive redirect hosts, and extracts with traversal/symlink protections. The worker uses no shell or Git subprocess.

## Limits before internet-facing production

- Default Compose PostgreSQL credentials are development-only. Add production secret management, TLS/reverse proxy, backup/restore, key rotation, and least-privilege database credentials before external exposure.
- No MFA, email verification or password recovery. Legacy ownerless projects can be claimed by the first account registration; the current sample project remains ownerless until an account claims it.
- Worker has no healthcheck, autoscaling or durable failed-job UI. A Celery retry state is presented as processing; queue submission failures return 503 and remove the unqueued upload.
- Public GitHub sync downloads a complete snapshot archive on each run; only the database replacement is atomic. There is no file-level transfer optimization, webhook, or private repository support. Private repository support needs a backend-only GitHub App installation flow with repository-scoped permissions, encrypted credential storage/rotation, and redacted logs; no token is accepted from the frontend.
- Dependency extraction and impact traversal use heuristic import/reference strings, not a compiler-accurate call graph. No cross-language symbol resolution guarantee.
- Graph facts for Python/Java/JavaScript/TypeScript are static and incomplete for dynamic dispatch, reflection, overloads, and external packages. Calls are linked only when a unique local declaration or explicit local import identifies the target; unresolved names are labeled unresolved. Chunking remains symbol/line based.
- Retrieval uses RRF and overlap scoring with a 0.45 relevance threshold; there is no learned reranker or calibrated confidence. The benchmark artifact is not a current production-quality guarantee.
- Chat history stores citations, answer modes and retrieved evidence excerpts. The frontend has a graph component interaction test but no full browser e2e automation; history is loaded from the server per project.
- No explicit embedding output dimension guard was found. Large repositories and concurrent indexing need load/performance testing.
