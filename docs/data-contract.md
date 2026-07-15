# Data contract

The candidate is a user-supplied, not-yet-listed product. It has no sales, rating, or reviews. Listed Amazon records
are stored and described only as peer-market products; their reviews are peer-review samples.

## Prepared caches

`product_catalog.sqlite` stores normalized `parent_asin`, title, description, features, details, categories,
`Target Species`, price, average rating, rating count, source row, and an FTS index. `review_lookup.sqlite` stores
`parent_asin`, byte offset, source row, and counts. Both contain source size/mtime signatures, are atomically built,
idempotently reused, and automatically reported stale when the source changes. Both live under ignored
`data/demo/cache/`.

No full-corpus embedding is created. Online selection uses FTS/rules to retain about 100-300 candidates, embeds only
the candidate subset, reranks about 20-50, and selects up to 10-30 complete peer products that pass the configured
rule and semantic thresholds. It never lowers a threshold or adds unrelated products to meet 10. When fewer than 10
qualify, the actual set is retained and `insufficient_peer_products` is propagated through statistics, Agents, API
metadata, and the report. Configured accessory terms exclude filters, pumps, mats, cleaning brushes, adapters,
replacement parts, accessories, and refills without treating a complete product as an accessory merely because its
description mentions an internal pump.

The catalog does not assign mandatory normalized categories. FTS is built from actual product text, and products with
missing or different categories remain eligible. `categories` is auxiliary; `main_category` is stored for traceability
but is not an acceptance gate. `product_type`, when supplied in candidate text/parameters, is only a retrieval hint.

`peer_group_id` is derived from the normalized candidate business signature, catalog source signature, complete
matching configuration/version, embedding model, and sorted accepted ASINs. The candidate's random upload
`product_id` is deliberately excluded. Same inputs produce the same ID; catalog/config/model/accepted-set changes
produce a new ID.

## Runtime subset

The runtime SQLite contains one candidate product, selected real peers, offers/statistics sources, and exact peer
reviews. It never fabricates candidate reviews, rating, or sales. The two small Chroma collections contain only peer
product and peer-review documents for selected groups.

Every peer evidence item carries `evidence_scope=peer_product`, `peer_group_id`, `peer_product_id`, `parent_asin`,
`match_score`, `source_file`, and `source_row`. Evidence IDs are stable and audit-visible.

The offset cache may point to duplicate source rows because it preserves source truth. Online lookup removes exact
duplicate review identities after seeking the selected ASINs and before SQLite/Chroma persistence; it does not rewrite
or expand review text and does not require a cache rebuild.

Optional product-background evidence is a separate scope with provider, source URI, context type, jurisdiction,
effective date and query date. An empty provider result is a traceable data gap, not permission for an Agent to invent
policy, tax, compliance, platform, or trend facts.

## Numeric boundary

Peer-group SQL statistics may provide `peer_product_count`, `priced_product_count`, min/max/average/median price,
average rating, and total rating count. Exact values in conclusions must come from those structured metrics or explicit
user input. Review text cannot establish market share, sales, exact population ratios, or issue incidence.

Attribute-led inferences are marked `reasoned_hypothesis` and rendered as `待验证假设`; they are neither review
findings nor market statistics.
