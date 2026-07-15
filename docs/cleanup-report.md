# Cleanup report

Cleanup is limited to generated runtime state and stale documentation claims. Backward-compatible Demo tests,
`exact_product` retrieval, migration history, source Git LFS data, and the separate full-index code are retained.

After final validation and before commit, stop local uvicorn and remove only ignored paths under `data/demo/`: runtime
SQLite, Chroma, reports, uploads, logs, PID, prepared caches, and temporary subset artifacts. Cache deletion is final
repository hygiene, not a rebuild; `data/filtered/` and any separate full-index build remain untouched.

The final repository check must confirm `.env`, keys, SQLite, Chroma state, caches, images, reports, logs, and virtual
environments are absent from staged files. Final gate results are recorded in the main handover document and commit
message, not inferred from older cleanup runs.
