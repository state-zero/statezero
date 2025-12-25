# TICKET-001: Support Reverse Relations in Model Graph

## Summary
Reverse relations (e.g., `ForeignKey.related_name`) are currently skipped when building the model graph, even when explicitly listed in a model's `fields` config. This causes a `NetworkXError` when traversing relations at depth > 0.

---

## Problem

When a model config includes a reverse relation in `fields`:

```python
registry.register(
    HousekeepingService,
    ModelConfig(
        fields={
            "id",
            "home",
            "assigned_tasks",  # ← Reverse relation from AssignedTask.housekeeping_service
        },
    ),
)
```

The graph building in `build_model_graph()` skips all `ForeignObjectRel` fields:

```python
# orm.py:853-856
if isinstance(field, ForeignObjectRel):
    continue  # ← Skipped entirely, even if in configured fields
```

This results in:
1. The reverse relation field node is never added to the graph
2. The related model (`AssignedTask`) is never added to the graph
3. When `_get_depth_based_fields()` tries to traverse the relation, it fails:

```
networkx.exception.NetworkXError: The node housekeeping.assignedtask is not in the digraph.
```

---

## Solution

Modify `build_model_graph()` to include reverse relations **if they are explicitly listed in the model's configured `fields`**.

### Changes to `statezero/adaptors/django/orm.py`

In `build_model_graph()`, replace the blanket skip:

```python
# Before (line 853-856)
if isinstance(field, ForeignObjectRel):
    continue
```

With a conditional skip that checks the model config:

```python
# After
if isinstance(field, ForeignObjectRel):
    # Only include reverse relations if explicitly configured
    try:
        config = registry.get_config(model)
        if field.name not in config.fields:
            continue
    except ValueError:
        continue  # Model not registered, skip reverse relation
```

Then handle the reverse relation like a forward relation - add the field node and recursively build the related model:

```python
# For reverse relations, the related model is the model that defines the FK
if isinstance(field, ForeignObjectRel):
    related_model = field.related_model
    related_model_name = self.get_model_name(related_model)

    field_node = f"{model_name}::{field_name}"
    field_node_data = FieldNode(
        model_name=model_name,
        field_name=field_name,
        is_relation=True,
        related_model=related_model_name,
    )
    model_graph.add_node(field_node, data=field_node_data)
    model_graph.add_edge(model_name, field_node)

    if not model_graph.has_node(related_model_name):
        self.build_model_graph(related_model, model_graph)
    model_graph.add_edge(field_node, related_model_name)
    continue
```

---

## Behavior

Reverse relations will be treated as **read-only** relations, similar to how `additional_fields` with M2M/FK work:

| Aspect | Behavior |
|--------|----------|
| Read (list/detail) | Included in response if in `fields` and depth allows |
| Create | Not writable (ignored in input) |
| Update | Not writable (ignored in input) |
| Graph traversal | Works correctly, related model added to graph |

---

## Acceptance Criteria

- [ ] Reverse relations listed in `fields` are added to the model graph
- [ ] Related models are recursively added to the graph (no `NetworkXError`)
- [ ] Circular dependencies handled correctly (via `has_node()` guard)
- [ ] Reverse relations not in `fields` are still skipped
- [ ] Unregistered models still skip reverse relations
- [ ] Read operations return reverse relation data at appropriate depth
- [ ] Write operations ignore reverse relation fields (read-only)

---

## Test Cases

1. **Basic reverse relation**: Model A has FK to Model B with `related_name`. Model B lists the reverse relation in fields. Query Model B at depth=1 should include related Model A instances.

2. **Circular dependency**: Model A → Model B → Model A. No infinite loop when building graph.

3. **Unregistered related model**: Reverse relation points to unregistered model. Should skip gracefully.

4. **Write operations**: Attempting to set reverse relation field in create/update should be ignored.

---

## Notes

- This makes `additional_fields` unnecessary for exposing reverse relations
- Existing `additional_fields` usage will continue to work (separate code path)
- The `has_node()` guard prevents infinite recursion in circular dependencies
