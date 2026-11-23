# Semantic-quality features ported from Auto-Ontology 1.3

This fork keeps its own property-level semantic-FK model and its longer
text-to-SQL validation pipeline. From Auto-Ontology 1.3 it adopts the
semantic-compilation improvements that do not require replacing either:

| Feature | Where |
| --- | --- |
| Term families (`OLD_` / `NEW_` copies of one schema) | `all_ontology/semantic/term_families.py`, `all_ontology/dal/term_families.py` |
| Lowest distinct values and distinct ratio per column | `catalog_column.distinct_values`, `catalog_column.distinct_ratio` |
| Value-confirmed semantic FKs and a value-only fallback | `all_ontology/semantic/fk_values.py`, `semantic/semantic_fk.py` |
| Declared self-references (`manager_id -> id`) are kept | `semantic/semantic_fk.py` |
| Unmatched suspected-FK columns attached after resolution | `all_ontology/semantic/unmatched_fks.py` |
| One business description per ColumnAttribute | `all_ontology/semantic/attribute_descriptions.py` |
| PII-tagged columns excluded from sampling, and stored values withheld | `semantic/visit_enter.py`, `semantic/pii_values.py`, `dal/pii.py` |

Compilation order is now:

```
table taxonomy -> term families -> semantic FKs -> unmatched FKs
               -> SqlAttributes -> bridge tables -> attribute descriptions
```

## Deliberate gap: concept-key semantic FKs

Auto-Ontology 1.3 also introduces `concept` / `concept_key` and re-points every
`column__semantic_fk` from a ColumnAttribute to a Concept key. Doing that here
would mean rewriting this fork's join-path traversal
(`dal/attributes.py` still carries `find_table_bridge`,
`find_connected_junction_tables` and related helpers that 1.3 removed). It is
a separate schema migration, not an additive port, so this change keeps the
attribute-level target and does not half-create a second identity model.

## Deliberate gap: ReAct answering agent

1.3 replaces the multi-agent text-to-SQL graph with one ReAct episode
(`retrieve` / `run_sql` / `submit` / `grep` / `predict`). This fork has its own
agents, probe validators and Kumo integration. The ReAct engine can be added
as an opt-in pipeline later; it is not a drop-in module because both sides
own `state.py`, `prompts.py` and `agents/sql_execution.py`.
