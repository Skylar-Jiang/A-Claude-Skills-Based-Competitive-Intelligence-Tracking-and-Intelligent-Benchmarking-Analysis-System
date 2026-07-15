# Development log — 2026-07-15

- Added durable asynchronous runs, ten stages, frontend read views and replayable SSE.
- Added immutable report versions, guarded report support, diffs, conversations and rollback.
- Added an optional evidence-only background provider boundary with no default external facts.
- Added ten concrete real-product matching cases and stronger accessory exclusions.
- Fixed duplicate IDs in Chroma batches and duplicate review identities after offset lookup.
- Fixed failed SQLAlchemy sessions masking the original background error and leaving runs permanently `running`.
- Enabled SQLite WAL/busy timeout for concurrent status reads and writes; deferred default Chroma initialization to the
  background worker.
- Preserved the offline/online boundary: no cache rebuild, source scan, full embedding, or full-index mutation occurs
  in the analysis request path.

All changes were developed with focused RED→GREEN tests before full gates. Generated SQLite, Chroma, reports, logs,
validation JSON and `.env` remain ignored.
