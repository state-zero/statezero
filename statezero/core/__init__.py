"""
statezero: A framework for model synchronization and event handling across different ORMs.
"""

from statezero.core.config import AppConfig, ModelConfig, Registry
from statezero.core.interfaces import (AbstractCustomQueryset,
                                       AbstractDataSerializer,
                                       AbstractEventEmitter,
                                       AbstractORMProvider, AbstractPermission,
                                       AbstractSchemaGenerator)
from statezero.core.permission_resolver import PermissionResolver
from statezero.core.permission_bound import PermissionBound, SyntheticRequest
from statezero.core.types import ActionType, ORMField, ORMModel, RequestType

__all__ = [
    # Types
    "ActionType",
    "ORMField",
    "RequestType",
    "ORMModel",
    # Configuration
    "AppConfig",
    "ModelConfig",
    "Registry",
    "app_config",
    "global_registry",
    # Abstract Base Classes
    "AbstractCustomQueryset",
    "AbstractORMProvider",
    "AbstractDataSerializer",
    "AbstractSchemaGenerator",
    "AbstractEventEmitter",
    "AbstractPermission",
    # Permission API (ORM-agnostic base classes)
    "PermissionResolver",
    "PermissionBound",
    "SyntheticRequest",
    # Django convenience: from statezero.adaptors.django.permission_bound import PermissionBound
]

__version__ = "0.1.0"
