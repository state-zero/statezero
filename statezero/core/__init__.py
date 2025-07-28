"""
statezero: A framework for model synchronization and event handling across different ORMs.
"""

from statezero.core.config import AppConfig, ModelConfig, Registry
from statezero.core.interfaces import (AbstractCustomQueryset,
                                       AbstractDataSerializer,
                                       AbstractEventEmitter,
                                       AbstractORMProvider, AbstractPermission,
                                       AbstractSchemaGenerator)
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
    "AbstractPermission"
]

__version__ = "0.1.0"
