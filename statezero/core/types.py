from __future__ import annotations

from enum import Enum


class ActionType(Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    BULK_CREATE = "bulk_create"
    BULK_UPDATE = "bulk_update"
    BULK_DELETE = "bulk_delete"
    # new pre-operation types
    PRE_UPDATE = "pre_update"
    PRE_DELETE = "pre_delete"


# ORM aliases re-exported from Django adaptor for backward compatibility
from statezero.adaptors.django.types import ORMField, ORMModel, ORMQuerySet, RequestType
