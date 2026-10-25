# Demo script

1. Start the stack with `docker compose up -d --build` and wait for `http://localhost:8000/ready` to return success.
2. Open `http://localhost:5173`, register an account, and create a project named `CodeMind sample`.
3. Zip the contents of `sample_repo/` and upload the ZIP. Wait until indexing reports `COMPLETED`; show the file, chunk and language counts.
4. Ask “Where is retry logic implemented?” Show `answer_mode=llm` when Gemini is configured, otherwise explain the deterministic fallback. Expand the citation and compare its file and line range to source.
5. Ask an unrelated question such as “What is the office Wi-Fi password?” Show the insufficient-evidence abstention and absence of citations.
6. Reload/select the project and show history preserves the answer, answer mode and citations. Explain that historical excerpts are not retained.
7. Search a dependency string and run impact analysis for a listed file. Describe results as inferred dependency edges rather than a complete call graph.

Never show `.env`, session tokens, or provider key values during the demo. Use a disposable project if demonstrating project deletion.
