# TICKET-003: ForeignKey/OneToOneField as Primary Key causes serialization failure

## Summary

When a model uses a ForeignKey or OneToOneField as its primary key (`primary_key=True`), the serializer fails with `TypeError: Object of type User is not JSON serializable`.

## Reproduction

```python
class ConversationActivity(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,  # <-- This causes the issue
        related_name='conversation_activity',
    )
    last_message_at = models.DateTimeField()
```

When fetching this model via statezero, the response fails during JSON serialization because the `user` field (which is also the PK) returns the full User object instead of just the ID.

## Expected Behavior

The serializer should recognize that the PK field is a relation and serialize it as the related object's primary key (e.g., UUID), not the full object.

## Actual Behavior

```
TypeError: Object of type User is not JSON serializable
```

## Root Cause

In `DRFDynamicSerializer.serialize()`, the top-level primary keys are extracted with:

```python
result["data"] = [getattr(instance, pk_field) for instance in top_level_instances]
```

When `pk_field` is a OneToOneField, `getattr(instance, pk_field)` returns the related User instance, not the ID.

## Suggested Fix

Check if the PK field is a relation and extract the ID appropriately:

```python
pk_field = model._meta.pk
if pk_field.is_relation:
    result["data"] = [getattr(instance, pk_field.attname) for instance in top_level_instances]
else:
    result["data"] = [getattr(instance, pk_field.name) for instance in top_level_instances]
```

Using `pk_field.attname` (e.g., `user_id`) instead of `pk_field.name` (e.g., `user`) would return the raw ID value.

## Workaround

Don't use ForeignKey/OneToOneField as primary key. Use a regular auto-generated PK instead:

```python
class ConversationActivity(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='conversation_activity',
    )  # No primary_key=True
```

## Priority

Medium - Has a simple workaround but should be fixed for proper Django model support.
