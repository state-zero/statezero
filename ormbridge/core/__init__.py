"""
ormbridge: A framework for model synchronization and event handling across different ORMs.
"""

from ormbridge.core.config import AppConfig, ModelConfig, Registry
from ormbridge.core.interfaces import (AbstractCustomQueryset,
                                       AbstractDataSerializer,
                                       AbstractEventConfig,
                                       AbstractEventEmitter,
                                       AbstractORMProvider, AbstractPermission,
                                       AbstractSchemaGenerator)
from ormbridge.core.types import ActionType, ORMField, ORMModel, RequestType

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
    "AbstractEventConfig",
]

__version__ = "0.1.0"
