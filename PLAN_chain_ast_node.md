# Introduce `chain` AST node to distinguish chained filters from compound Q

## Context

Both `.filter(a).filter(b)` (chained calls) and `.filter(Q(a) & Q(b))` (compound Q) produce identical AST: `{"type": "and", "children": [...]}`. The server always splits top-level `"and"` into separate `.filter()` calls, forcing chained-filter (ANY/ANY) M2M semantics everywhere. This means compound `Q(a) & Q(b)` never gets Django's single-filter (SAME-object) M2M semantics.

**After this change:**
- `.filter(a).filter(b)` → `{"type": "chain", ...}` → separate `.filter()` calls (ANY/ANY)
- `.filter(Q(a) & Q(b))` → `{"type": "and", ...}` → single `.filter()` with combined Q (SAME-object)

## Changes

### 1. JS Client `build()` — 1 line
**File:** `statezero-client/src/flavours/django/querySet.js` line ~882

Change the wrapper from `"and"` to `"chain"` when `build()` wraps multiple nodes:
```javascript
// BEFORE
{ type: "and", children: nonSearchNodes }
// AFTER
{ type: "chain", children: nonSearchNodes }
```

`filter()` (line 221) and `exclude()` (line 256) Q wrappers keep `"and"` — they represent logical AND within a single call.

### 2. Python Client `_build()` — 1 line
**File:** `statezero/client/runtime_template.py` line 691

Same change:
```python
# BEFORE
filter_node = {"type": "and", "children": non_search}
# AFTER
filter_node = {"type": "chain", "children": non_search}
```

`_CompoundQ._to_ast()` (line 493) keeps producing `"and"` — correct.

### 3. Server `filter_node()` — rewrite ~12 lines
**File:** `statezero/adaptors/django/orm.py` lines 196-210

- `"chain"` → split into separate `.filter()`/`.exclude()` calls (current AND behavior)
- `"and"` → let visitor combine into single Q (new correct behavior)
- Chain children can include exclude nodes — dispatch to `exclude_node()`

### 4. Server `exclude_node()` — simplify ~8 lines
**File:** `statezero/adaptors/django/orm.py` lines 221-240

Remove AND-splitting. The `"and"` inside an exclude child should always combine into a single Q. Chained `.exclude(a).exclude(b)` is now handled as separate chain children.

### 5. JS Tests — update 3 outer `"and"` → `"chain"`

**File:** `statezero-client/tests/query-builder.test.ts`
- Line 135: `.filter().exclude()` outer wrapper → `"chain"`

**File:** `statezero-client/tests/query-builder-ast.test.ts`
- Line 231: `.filter().exclude()` outer wrapper → `"chain"`
- Line 284: `.filter().exclude()` outer wrapper → `"chain"`

Inner `"and"` nodes (Q wrappers within single calls) are unchanged.

### 6. JS Client local filtering — 2 spots
**File:** `statezero-client/src/filtering/localFiltering.js`

- Line 824: `convertFilterNodeToSiftCriteria` — add `"chain"` alongside `"and"` (both map to `$and` in sift)
- Line 1089: `walkFilter` switch — add `"chain"` case alongside `"and"`/`"or"` to recurse children

### 7. Python Parity Tests — update + add ~30 lines
**File:** `tests/adaptors/django/test_exotic_query_parity.py`

- Update `test_m2m_compound_q_different_fields_is_chained_semantics` → compound Q now matches Django single-filter (SAME-object) semantics
- `test_m2m_chained_filters_any_any` should still pass unchanged
- Add `test_m2m_chain_vs_compound_q_differ` contrasting the two behaviors

## Files NOT changed
- `ast_validator.py` — already recurses `"children"` generically (line 257)
- `process_request.py` `_extract_filter_fields()` — already recurses `"children"` generically (line 74)
- `QueryASTVisitor` — never sees `"chain"` (handled before reaching visitor)

## Verification
```
python manage.py test tests.adaptors.django.test_exotic_query_parity --verbosity 2
python manage.py test tests.adaptors.django.test_client_parity --verbosity 2
cd ../statezero-client && npm test
```
