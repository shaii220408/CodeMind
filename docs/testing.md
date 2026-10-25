# Testing and evaluation

## Backend regression suite

```powershell
docker compose exec api python -m pytest -q
```

The suite covers ownership checks and cross-user API isolation, Gemini request/error behavior and grounding, parser behavior, ZIP traversal/symlink/size/file-count defenses, queue/status regressions, source-range serving, public GitHub URL/branch validation and size preflight, Python/Java/JavaScript/TypeScript graph extraction/persistence, deterministic review rules and redaction, documentation source references, and analysis/document authorization and queue behavior. Graph tests use temporary files and isolated database projects, including repeated/stale indexing, changed/deleted files, rollback, project isolation, authorization, direct impact, bounded transitive impact, cycle handling, and depth validation. They do not use the user's sample repository, make external GitHub calls, or make real Gemini calls.

## Frontend production build

```powershell
Push-Location frontend
npm ci
npm run build
Pop-Location
```

Run frontend interaction tests with `npm test` from `frontend/`. They exercise graph search, selecting a node, direct-impact request wiring, source-location navigation, and project review/health/documentation views. Full browser end-to-end automation is not configured.

## Retrieval benchmark

`benchmarks/questions.json` labels relevant repository paths. Run against an indexed owned project:

```powershell
$env:CODERAG_PROJECT_ID = '<project-id>'
$env:CODERAG_TOKEN = '<bearer-session-token>'
python benchmarks/evaluate.py
Remove-Item Env:CODERAG_PROJECT_ID, Env:CODERAG_TOKEN
```

Metrics include Recall@K, MRR, file-level citation precision, citation coverage and request latency. A checked-in results JSON is a prior artifact, not a fresh result; benchmark numbers must be regenerated against the current index before being used as a release baseline.
