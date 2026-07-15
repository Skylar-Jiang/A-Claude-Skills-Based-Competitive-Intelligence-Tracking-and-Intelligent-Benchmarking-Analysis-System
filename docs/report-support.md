# Report support and versioning

`POST /api/v1/reports/{report_id}/support` supports two actions:

- `explain` returns an evidence-grounded explanation for one stable section and the evidence records used;
- `edit` applies a local section replacement only when every evidence ID exists, newly introduced numeric values are
  already supported, and forbidden candidate-feedback wording is absent.

Edits never mutate a stored report. Each accepted edit creates an immutable child version with `parent_report_id`,
`changed_section_ids`, a structured change record, and before/after/unified diff. Only the latest version may be
edited, preventing lost updates. Rejected requests are recorded in the conversation audit trail without creating a
report version.

`GET /reports/{report_id}/versions` lists the full version family. `POST /reports/{report_id}/rollback` copies a chosen
historical version into a new latest version; history remains append-only. `GET /conversations/{session_id}` returns
messages in chronological order with support metadata.

Guardrails intentionally permit only bounded report assistance. They do not allow unsupported market facts, invented
policy/tax/platform claims, new-product review attribution, evidence-ID fabrication, or arbitrary whole-report
rewrites. The original evidence audit remains visible on every derived version.
