# OperationContentSkill

This skill owns the versioned rules used by `OperationsDecisionAgent` to create deterministic
drafts for product titles, five selling-point bullets, descriptions, advertising keywords, and
customer-service replies. The YAML file is the editable policy source; `skill.py` validates it,
builds content only from the supplied `ProductProfile`, and audits length, completeness, and
forbidden-claim rules.

The generated copy remains a draft. Exact prices, ratings, counts, ratios, certifications, and
performance claims must come from user input or validated structured evidence. The skill removes
configured prohibited expressions from generated copy, while `EvidenceAuditAgent` rejects them if
they are introduced later.

The content is encoded into the existing `OperationPlan.next_steps` contract with stable prefixes
and is reconstructed by the report exporter. This preserves the frozen shared schema while still
giving JSON and Markdown reports a structured content playbook.
