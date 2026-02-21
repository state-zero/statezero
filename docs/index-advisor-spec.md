# StateZero Index Advisor — Design Spec

## Goal

A built-in management command (`manage.py suggest_indexes`) that observes query patterns flowing through StateZero and outputs an `.md` report recommending missing database indexes, ranked by impact.

## Why build it vs use existing tools

- **No Django package exists** that does this. The ecosystem has profiling tools (django-silk, debug-toolbar) that surface slow queries but none that recommend indexes.
- **Dexter** (PostgreSQL) is the closest external tool but requires the HypoPG extension (unavailable on many hosted providers), operates outside Django, and has no awareness of StateZero's permission filters or query AST.
- **StateZero already captures everything needed**: the telemetry system records every SQL query per request, the query AST knows which fields are filtered/ordered before they hit SQL, and `ModelConfig` declares which fields are filterable.

## Architecture

### Two phases: Collect and Analyze

```
Phase 1: Collect (middleware, runs in dev/staging)
  Request → TelemetryContext captures queries
        → IndexCollector records field usage from AST
        → Writes to collection file (JSON lines)

Phase 2: Analyze (management command, runs on-demand)
  Reads collection file
  + Reads model Meta (existing indexes)
  + Optionally runs EXPLAIN on top queries
  → Outputs .md report
```

### Phase 1 — Collection

Hook into the existing telemetry path in `ModelView.post()`. A new `IndexCollector` records:

| Field | Source |
|---|---|
| model name | from request AST |
| filtered fields | from `filter` node in query AST |
| ordered fields | from `orderBy` node in query AST |
| combined filter patterns | field combinations that appear together (for composite indexes) |
| query count | incremented per pattern |
| avg duration (ms) | from `track_db_queries` |

Storage: append-only JSONL file at a configurable path (default: `.statezero/index_observations.jsonl`). One line per request, keeps it simple and avoids needing a DB table or cache backend.

Enable via setting:
```python
STATEZERO_INDEX_ADVISOR = True  # default False
STATEZERO_INDEX_ADVISOR_PATH = ".statezero/index_observations.jsonl"
```

### Phase 2 — Analysis (`suggest_indexes` command)

The management command:

1. **Aggregate observations** — group by model + field pattern, sum counts, compute avg duration
2. **Introspect existing indexes** — for each model, read `Meta.indexes`, `Meta.unique_together`, and field-level `db_index=True` / `unique=True`
3. **Identify gaps** — high-frequency filter/order fields (or combos) that have no covering index
4. **Rank by impact** — `score = frequency × avg_duration`. Optionally factor in table row count via `pg_stat_user_tables` or `COUNT(*)`
5. **Optional EXPLAIN pass** — for the top-N recommendations, run `EXPLAIN ANALYZE` on a representative query and check for `Seq Scan` on large tables. This confirms the recommendation isn't a false positive.
6. **Output report** — write `.md` file

### Report format

```markdown
# StateZero Index Advisor Report
Generated: 2026-02-19 | Observation period: 7 days | Total requests observed: 12,483

## High Impact (recommended)

### 1. `myapp_order.customer_id` — filtered 3,241 times, avg 45ms
- **Current state:** No index. Sequential scan confirmed via EXPLAIN.
- **Suggestion:** `models.Index(fields=["customer_id"])`
- **Estimated improvement:** High (large table, frequent filter)

### 2. `myapp_order.status, myapp_order.created_at` — filtered together 1,892 times, avg 62ms
- **Current state:** Individual index on `status` exists, but no composite.
- **Suggestion:** `models.Index(fields=["status", "created_at"])`
- **Note:** Order matters — `status` has lower cardinality, so it leads.

## Medium Impact

### 3. `myapp_product.category_id` — ordered by 987 times, avg 23ms
...

## Already indexed (no action)

- `myapp_order.id` — primary key
- `myapp_customer.email` — unique constraint
...

## Unused indexes detected

- `myapp_order.legacy_ref` — index exists, 0 filter/order observations
  - Consider dropping if confirmed unused in other code paths
```

## Implementation plan

### New files

| File | Purpose |
|---|---|
| `statezero/adaptors/django/index_advisor/collector.py` | `IndexCollector` — extracts field usage from AST, appends to JSONL |
| `statezero/adaptors/django/index_advisor/analyzer.py` | Reads JSONL, introspects models, scores gaps, optionally runs EXPLAIN |
| `statezero/adaptors/django/index_advisor/report.py` | Renders the `.md` report |
| `statezero/adaptors/django/management/commands/suggest_indexes.py` | Management command entry point |

### Modified files

| File | Change |
|---|---|
| `statezero/adaptors/django/views.py` | After telemetry block, call `IndexCollector.record()` if enabled |
| `statezero/core/config.py` | Add `index_advisor_enabled` and `index_advisor_path` settings |

### Management command interface

```bash
# Basic — reads observations, outputs report
python manage.py suggest_indexes

# With EXPLAIN pass (requires DB access, slower)
python manage.py suggest_indexes --explain

# Custom observation file
python manage.py suggest_indexes --observations .statezero/index_observations.jsonl

# Output path (default: index_report.md)
python manage.py suggest_indexes -o docs/index_report.md

# Minimum frequency threshold (ignore rare patterns)
python manage.py suggest_indexes --min-frequency 50

# Reset observations
python manage.py suggest_indexes --reset
```

## Scope boundaries

**In scope:**
- Filter and order-by field tracking from StateZero query AST
- Composite index detection (fields that co-occur in filters)
- Existing index introspection from Django model Meta
- EXPLAIN-based confirmation (opt-in)
- Unused index detection (index exists but field never observed in filters)
- PostgreSQL and SQLite support for basic mode; EXPLAIN pass PostgreSQL-only

**Out of scope (future):**
- Automatic index creation (too dangerous — report only)
- Partial index suggestions (e.g. `WHERE status = 'active'`)
- GIN/GiST index suggestions for full-text or JSON fields
- Production log ingestion (use Dexter for that)
- Historical trend tracking across multiple observation periods

## Dependencies

None. Uses only Django internals (`connection.cursor()` for EXPLAIN, model `_meta` for index introspection) and StateZero's existing AST/telemetry.
