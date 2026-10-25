# Viva preparation

## Short project explanation

CodeMind indexes supported source files into PostgreSQL with pgvector, retrieves candidate code with both semantic vector search and PostgreSQL lexical search, fuses rankings with Reciprocal Rank Fusion, filters evidence by a fixed relevance threshold, and asks Gemini to answer only from that evidence. The API returns explicit `llm`, `fallback`, or `abstention` modes and citations tied to retrieved file/line ranges.

## Questions to be ready for

**Why hybrid retrieval?** Vector search finds semantically similar code while lexical search preserves exact names and terms; RRF combines their ranks before an overlap adjustment.

**How is grounding enforced?** The server retrieves project-scoped chunks, drops evidence below 0.45, passes the remaining excerpts to a constrained prompt, and returns citations derived from retrieved evidence. If evidence is inadequate, it abstains. Provider failures are errors rather than successful fallbacks.

**How are repeated uploads handled?** SHA-256 hashes identify unchanged files and avoid regenerating their embeddings. Current documents/chunks are updated transactionally, but there is not yet index version rollback.

**How is uploaded code protected?** Upload size and archive file count/expanded size are bounded, traversal paths and symlinks are rejected, and ignored/generated paths are skipped. This is not a substitute for malware scanning or process isolation in a public service.

**What are the main limitations?** No full AST extraction, learned reranker, versioned index, Git commit sync, call-graph-grade dependency analysis, or frontend E2E suite. Deployment secrets/TLS and account recovery also require production work.
