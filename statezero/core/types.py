from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import (Any, Callable, Dict, List, Optional, Set, Type, TypeVar,
                    Union)

# Django imports
try:
    from django.db.models import Field as DjangoField
    from django.db.models import Model as DjangoModel
    from django.db.models.query import QuerySet as DjangoQuerySet
    from rest_framework.request import Request as DRFRequest
except ImportError:
    DjangoField = None
    DjangoQuerySet = None
    DjangoModel = None
    DRFRequest = object

# SQLAlchemy imports
try:
    from sqlalchemy.ext.declarative import \
        DeclarativeMeta as SQLAlchemyDeclarativeMeta
    from sqlalchemy.orm.query import Query as SQLAlchemyQuery
    from sqlalchemy.sql.schema import Column as SQLAlchemyColumn  # type:ignore
except ImportError:
    SQLAlchemyColumn = None
    SQLAlchemyQuery = None
    SQLAlchemyDeclarativeMeta = None

# FastAPI & Flask imports
try:
    from fastapi import Request as FastAPIRequest
except ImportError:
    FastAPIRequest = object

try:
    from flask import Request as FlaskRequest
except ImportError:
    FlaskRequest = object

# Type definitions
# Explicitly list all possible types. Including 'object' as a fallback ensures the type remains valid
ORMField = Union[object, DjangoField, SQLAlchemyColumn]
ORMModel = Union[object, DjangoModel, SQLAlchemyDeclarativeMeta]
ORMQuerySet = Union[Any, DjangoQuerySet, SQLAlchemyQuery]
RequestType = Union[DRFRequest, FastAPIRequest, FlaskRequest]

class HotPathActionType(Enum):
    CREATED = "created"
    COMPLETED = "completed"
    REJECTED = "rejected"

class ActionType(Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    BULK_UPDATE = "bulk_update"
    BULK_DELETE = "bulk_delete"
    # new pre-operation types
    PRE_UPDATE = "pre_update"
    PRE_DELETE = "pre_delete"