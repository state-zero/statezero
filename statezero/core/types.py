from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import (Any, Callable, Dict, List, Optional, Set, Type, TypeVar,
                    Union)

# Django imports
from django.db.models import Field as DjangoField
from django.db.models import Model as DjangoModel
from django.db.models.query import QuerySet as DjangoQuerySet
from rest_framework.request import Request as DRFRequest

# Type definitions, when we add FastAPI support, we wil turn these into unions
ORMField = DjangoField
ORMModel = DjangoModel
ORMQuerySet = DjangoQuerySet
RequestType = DRFRequest

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
