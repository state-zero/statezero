# TICKET-002: Chained Filters Use Wrong M2M Semantics

## Summary
Chained `.filter()` calls on M2M fields currently use SAME-object semantics instead of Django's ANY/ANY semantics. The backend combines all AND children into a single Q object and calls `.filter()` once, when it should call `.filter()` multiple times to get separate JOINs.

---

## Problem

In Django ORM, chained filters on M2M fields have different semantics than a single filter with multiple conditions:

```python
# ANY/ANY - different objects can match each condition (separate JOINs)
qs.filter(m2m__field=10).filter(m2m__field=20)

# SAME object - one object must match both conditions (single JOIN)
qs.filter(m2m__field=10, m2m__field=20)
```

Currently, the backend's `filter_node()` method visits the entire AST and creates a single combined Q object:

```python
# orm.py:212-217
def filter_node(self, queryset: QuerySet, node: Dict[str, Any]) -> QuerySet:
    model = queryset.model
    visitor = QueryASTVisitor(model)
    q_object = visitor.visit(node)  # Combines everything into one Q
    return queryset.filter(q_object)  # Single filter call!
```

And `visit_and()` combines children with `&`:

```python
# orm.py:136-138
def visit_and(self, node: Dict[str, Any]) -> Q:
    return self._combine(node.get("children", []), lambda a, b: a & b)
```

This means chained filters from the client:
```javascript
Model.objects.filter({ m2m__field: 10 }).filter({ m2m__field: 20 })
```

Get converted to:
```python
queryset.filter(Q(m2m__field=10) & Q(m2m__field=20))  # SAME object semantics!
```

Instead of:
```python
queryset.filter(Q(m2m__field=10)).filter(Q(m2m__field=20))  # ANY/ANY semantics
```

---

## Solution

Modify `filter_node()` to handle top-level AND nodes by calling `.filter()` multiple times instead of combining Q objects.

### Option A: Simple loop in filter_node

```python
def filter_node(self, queryset: QuerySet, node: Dict[str, Any]) -> QuerySet:
    """Apply a filter node to the queryset and return new queryset."""
    model = queryset.model
    visitor = QueryASTVisitor(model)

    # For top-level AND nodes, apply each child as a separate filter
    # to get Django's chained filter semantics (ANY/ANY for M2M)
    if node.get("type") == "and" and "children" in node:
        for child in node["children"]:
            q_object = visitor.visit(child)
            queryset = queryset.filter(q_object)
        return queryset

    # For other nodes, apply as single filter
    q_object = visitor.visit(node)
    return queryset.filter(q_object)
```

### Exclude also affected?

The same issue likely applies to `exclude_node()`. In Django:

```python
# Different semantics:
qs.exclude(m2m__field=10).exclude(m2m__field=20)  # Separate excludes
qs.exclude(m2m__field=10, m2m__field=20)  # Single exclude
```

Apply the same pattern:

```python
def exclude_node(self, queryset: QuerySet, node: Dict[str, Any]) -> QuerySet:
    model = queryset.model
    visitor = QueryASTVisitor(model)

    # Handle exclude nodes with a child
    if "child" in node:
        child = node["child"]
        # For top-level AND nodes in exclude, apply each as separate exclude
        if child.get("type") == "and" and "children" in child:
            for grandchild in child["children"]:
                q_object = visitor.visit(grandchild)
                queryset = queryset.exclude(q_object)
            return queryset
        q_object = visitor.visit(child)
    else:
        q_object = visitor.visit(node)

    return queryset.exclude(q_object)
```

---

## Impact

This is a semantic correctness issue. Queries that should return results may return empty, or vice versa.

**Example:**
- Parent has M2M to Children: `[{role: "admin"}, {role: "user"}]`
- Query: `.filter({children__role: "admin"}).filter({children__role: "user"})`
- Expected (ANY/ANY): Parent matches (has child with admin AND has child with user)
- Current (SAME): No match (no single child has both admin AND user roles)

---

## Acceptance Criteria

- [ ] Chained `.filter()` calls on M2M fields use separate JOINs (ANY/ANY semantics)
- [ ] Single `.filter()` with multiple M2M conditions uses single JOIN (SAME object semantics)
- [ ] Chained `.exclude()` calls behave correctly
- [ ] Non-M2M filters continue to work correctly
- [ ] Nested AND/OR within a single filter still work correctly

---

## Test Cases

1. **Chained M2M filter - should match**
   ```python
   # Parent has children with roles ["admin", "user"]
   Parent.objects.filter(children__role="admin").filter(children__role="user")
   # Should return the parent (ANY child has admin, ANY child has user)
   ```

2. **Single M2M filter with multiple conditions - should NOT match**
   ```python
   Parent.objects.filter(children__role="admin", children__role="user")
   # Should return empty (no SINGLE child has both roles)
   ```

3. **Chained M2M filter - should NOT match**
   ```python
   # Parent has children with roles ["admin", "viewer"]
   Parent.objects.filter(children__role="admin").filter(children__role="user")
   # Should return empty (no child has "user" role)
   ```

---

## Notes

- The client-side AST correctly represents chained filters as separate nodes in an AND
- The fix is entirely backend-side in the Django ORM adapter
- This is a simple for-loop change, low risk
