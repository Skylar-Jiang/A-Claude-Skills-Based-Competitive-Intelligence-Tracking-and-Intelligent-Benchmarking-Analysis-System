# Testing guide

The suite is split into unit, integration, and contract tests. The Chroma test injects a tiny local
embedding; no network or model download is allowed. `scripts/smoke_test.py` creates an empty database
and report directory under the OS temporary directory, runs the Demo chain, asserts 4 Agent outputs,
2 evidence references, and 1 report, then removes all artifacts.

Required gates:

```powershell
python -m pytest -q
python -m compileall -q app tests scripts
python -m ruff check app tests scripts
python scripts/smoke_test.py
```

Warnings must be recorded honestly. A command is only reported as passing when its actual exit code
is zero in the cleaned repository.
