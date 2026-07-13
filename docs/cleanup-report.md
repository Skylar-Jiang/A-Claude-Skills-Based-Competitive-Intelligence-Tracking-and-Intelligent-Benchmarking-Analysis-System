# Cleanup report

Cleanup is evidence-based. The old root entry, duplicate backend package, old Agent/RAG/report path,
old skill directory, old business fixtures, old tests, generated reports, and replaced documents are
eligible only after the new tests, compile check, Ruff, smoke test, and reference scan pass.

The user-provided planning source under `new-docs/` is preserved. `frontend/` contains only
`.gitkeep`. Runtime `.env`, keys, SQLite, Chroma data, generated reports, caches, and virtual
environments are ignored and must not be committed.

## Verified cleanup result (2026-07-13)

- Before deletion, the new unit/integration/contract suite passed independently. The combined old/new
  collection still failed because the old tests imported the old package and optional legacy
  dependencies (`openai`, `feedparser`, and `bs4`) were not installed in the new environment. Those
  tests and imports were part of the proven-unreferenced deletion set; no dependency was installed
  merely to preserve a removed chain.
- The post-cleanup reference scan found no old package imports, old routes, or old business terms in
  `app/`, scripts, README, default config, Demo data, or the new tests.
- `python -m pytest -q`: exit 0, 24 passed, one upstream TestClient deprecation warning.
- `python -m compileall -q app tests scripts`: exit 0.
- `python -m ruff check app tests scripts`: exit 0, all checks passed.
- `python scripts/smoke_test.py`: exit 0 from an empty temporary database; 4 Agent outputs, 2 evidence
  references, and 1 Demo/Scaffold report were verified.
- The preserved planning DOCX matched the original copy at SHA-256
  `991031611A14BF6AF61E1BDDC1A62FF18C5ADAD50751E7A51448DF4CAA90BD47`.
- After merging to main, the ignore-rule change exposed additional untracked legacy Chroma state,
  old collection/RAG indexes, old course-task logs/assets, and old memory caches. A second reference
  scan confirmed the new project did not use them; those paths were then removed.
- Main-tree verification also proved tests and Smoke explicitly disable local `.env` loading, so a
  developer's private model configuration cannot change Demo/Real contract test outcomes.
