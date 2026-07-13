# File structure

```text
app/
  adapters/        DomainAdapter contract and Demo adapter
  agents/          Four independent LCEL scaffold Agents and contracts
  api/v1/          The single formal API router
  core/            Settings, enums, exceptions
  db/              SQLAlchemy models, session, repository protocols
  rag/             Two-domain ports, memory store, minimal Chroma adapter
  schemas/         Pydantic v2 request, state, evidence, output, report models
  services/        Product, analysis, knowledge, conversation, report services
  skills/          Disabled OperationContentSkill placeholder
  workflows/       TradePilotState and the StateGraph
config/             Domain profiles
data/demo/          Explicitly marked deterministic fixtures
docs/               Architecture, contracts, development, handover, cleanup
frontend/.gitkeep   No frontend in this phase
scripts/            Init, seed, rebuild and isolated smoke commands
tests/              Unit, integration and API contract tests
new-docs/           User-provided planning source, preserved unchanged
```
