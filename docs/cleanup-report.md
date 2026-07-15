# Cleanup report

Cleanup is limited to generated runtime state and stale documentation claims. Backward-compatible Demo tests,
`exact_product` retrieval, migration history, source Git LFS data, and the separate full-index code are retained.

After final validation, local uvicorn was stopped and ignored runtime SQLite, Chroma, reports, uploads, logs,
validation JSON and temporary diagnostics were removed. The tracked deterministic Demo fixtures were retained. The
prepared `product_catalog.sqlite` and `review_lookup.sqlite` caches were deliberately retained locally, as required,
and were not rebuilt. `data/filtered/` and every separate full-index path remained untouched.

The final repository check must confirm `.env`, keys, SQLite, Chroma state, caches, images, reports, logs, and virtual
environments are absent from staged files. Final gate results are recorded in the main handover document and commit
message, not inferred from older cleanup runs.
