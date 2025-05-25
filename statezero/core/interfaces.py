from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type, Union, Literal, Protocol

from statezero.core.classes import ModelSchemaMetadata, SchemaFieldMetadata
from statezero.core.types import (ActionType, ORMField, ORMModel, ORMQuerySet, RequestType)

class AbstractORMProvider(ABC):
    """
    A merged ORM engine interface that combines both query building (filtering,
    ordering, aggregation, etc.) and ORM provider responsibilities (queryset assembly,
    event signal registration, model graph construction, etc.).
    """

    # === Query Engine Methods ===

    @abstractmethod
    def get_fields(self) -> Set[str]:
        """
        Get all of the model fields - doesn't apply permissions check.
        """
        pass

    @abstractmethod
    def filter_node(self, node: Dict[str, Any]) -> None:
        """
        Apply filter/and/or/not logic to the current query.
        """
        pass

    @abstractmethod
    def search_node(self, search_query: str, search_fields: Set[str]) -> None:
        """
        Apply search to the current query.
        """
        pass

    @abstractmethod
    def create(self, data: Dict[str, Any]) -> Any:
        """Create a new record."""
        pass

    @abstractmethod
    def update(self, node: Dict[str, Any]) -> int:
        """
        Update records (by filter or primary key).
        Returns the number of rows updated.
        """
        pass

    @abstractmethod
    def delete(self, node: Dict[str, Any]) -> int:
        """
        Delete records (by filter or primary key).
        Returns the number of rows deleted.
        """
        pass

    @abstractmethod
    def get(self, node: Dict[str, Any]) -> Any:
        """
        Retrieve a single record. Raises an error if multiple or none are found.
        """
        pass

    @abstractmethod
    def get_or_create(self, node: Dict[str, Any]) -> Tuple[Any, bool]:
        """
        Retrieve a record if it exists, otherwise create it.
        Returns a tuple of (instance, created_flag).
        """
        pass

    @abstractmethod
    def update_or_create(self, node: Dict[str, Any]) -> Tuple[Any, bool]:
        """
        Update a record if it exists or create it if it doesn't.
        Returns a tuple of (instance, created_flag).
        """
        pass

    @abstractmethod
    def first(self) -> Any:
        """Return the first record from the current query."""
        pass

    @abstractmethod
    def last(self) -> Any:
        """Return the last record from the current query."""
        pass

    @abstractmethod
    def exists(self) -> bool:
        """Return True if the current query has any results; otherwise False."""
        pass

    @abstractmethod
    def aggregate(self, agg_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregate the current query based on the provided functions.
        Example:
          [
            {'function': 'count', 'field': 'id', 'alias': 'id_count'},
            {'function': 'sum',   'field': 'price', 'alias': 'price_sum'}
          ]
        """
        pass

    @abstractmethod
    def count(self, field: str) -> int:
        """Count the number of records for the given field."""
        pass

    @abstractmethod
    def sum(self, field: str) -> Any:
        """Sum the values of the given field."""
        pass

    @abstractmethod
    def avg(self, field: str) -> Any:
        """Calculate the average of the given field."""
        pass

    @abstractmethod
    def min(self, field: str) -> Any:
        """Find the minimum value for the given field."""
        pass

    @abstractmethod
    def max(self, field: str) -> Any:
        """Find the maximum value for the given field."""
        pass

    @abstractmethod
    def order_by(self, order_list: List[Dict[str, str]]) -> None:
        """
        Order the query based on a list of fields.
        Each dict should contain 'field' and optionally 'direction' ('asc' or 'desc').
        """
        pass

    @abstractmethod
    def select_related(self, related_fields: List[str]) -> None:
        """
        Optimize the query by eager loading the given related fields.
        """
        pass

    @abstractmethod
    def prefetch_related(self, related_fields: List[str]) -> None:
        """
        Optimize the query by prefetching the given related fields.
        """
        pass

    @abstractmethod
    def fetch_list(self, offset: int, limit: int) -> List[Any]:
        """
        Return a list of records (as dicts or objects) based on pagination.
        """
        pass

    # === ORM Provider Methods ===

    @abstractmethod
    def get_queryset(
        self,
        request: RequestType,
        model: ORMModel,  # type:ignore
        initial_ast: Dict[str, Any],
        custom_querysets: Dict[str, Type],
        registered_permissions: List[Type],
    ) -> Any:
        """
        Assemble and return the base QuerySet (or equivalent) for the given model.
        This method considers the request context, initial AST (filters, sorting, etc.),
        custom query sets, and any model-specific permission restrictions.
        """
        pass

    @abstractmethod
    def register_event_signals(self, event_emitter: Any) -> None:
        """
        Wire the ORM provider's signals so that on create, update, or delete events,
        the global event emitter is invoked with the proper event type, instance,
        and global event configuration.
        """
        pass

    @abstractmethod
    def get_model_by_name(self, model_name: str) -> Type:
        """
        Retrieve the model class based on a given model name (e.g. "app_label.ModelName").
        """
        pass

    @abstractmethod
    def get_model_name(
        self, model: Union[Type[ORMModel], ORMModel]
    ) -> str:  # type:ignore
        """
        Retrieve the model name (e.g. "app_label.ModelName") for the given model class OR instance.
        """
        pass

    @abstractmethod
    def get_user(self, request: RequestType): # returns User
        """
        Get the request user.
        """
        pass

    @abstractmethod
    def build_model_graph(self, model: ORMModel) -> None:  # type:ignore
        """
        Construct a graph representation of model relationships.
        """
        pass


class AbstractCustomQueryset(ABC):
    @abstractmethod
    def get_queryset(self, request: Optional[RequestType] = None) -> Any:
        """
        Return a custom queryset (e.g. a custom SQLAlchemy Query or Django QuerySet).
        
        Args:
            request: The current request object, which may contain user information
        
        Returns:
            A custom queryset
        """
        pass


class AbstractDataSerializer(ABC):
    @abstractmethod
    def serialize(
        self,
        data: Any,
        model: ORMModel,  # type:ignore
        depth: int,
        fields: Optional[Set[str]] = None,
        allowed_fields: Optional[Dict[str, Set[str]]] = None,
    ) -> dict:
        """
        Serialize the given data (a single instance or a list) for the specified model.
        - `fields`: the set of field names requested by the client.
        - `allowed_fields`: a mapping (by model name) of fields the user is permitted to access.

        The effective fields are computed as the intersection of requested and allowed (if both are provided).
        """
        pass

    @abstractmethod
    def deserialize(
        self,
        model: ORMModel,  # type:ignore
        data: dict,
        allowed_fields: Optional[Dict[str, Set[str]]] = None,
        request: Optional[Any] = None,
    ) -> dict:
        """
        Deserialize the input data into validated Python types for the specified model.
        - `allowed_fields`: a mapping (by model name) of fields the user is allowed to edit.

        Only keys that appear in the allowed set will be processed.
        """
        pass


class AbstractSchemaGenerator(ABC):
    @abstractmethod
    def generate_schema(
        self,
        model: ORMModel,  # type:ignore
        global_schema_overrides: Dict[ORMField, dict],  # type:ignore
        additional_fields: List[ORMField],  # type:ignore
    ) -> ModelSchemaMetadata:
        """
        Generate and return a schema for the given model.
        Both global schema overrides and per-model additional fields are applied.
        """
        pass


class AbstractSchemaOverride(ABC):
    @abstractmethod
    def get_schema(self) -> Tuple[SchemaFieldMetadata, Dict[str, str], str]:
        """
        Return the schema for the field type.
        """
        pass


# --- Event Emitter ---
class AbstractEventEmitter(ABC):
    @abstractmethod
    def emit(
        self, namespace: str, event_type: ActionType, data: Dict[str, Any]
    ) -> None:
        """
        Emit an event to the specified namespace with the given event type and data.
        
        Parameters:
        -----------
        namespace: str
            The namespace/channel to emit the event to
        event_type: ActionType
            The type of event being emitted
        data: Dict[str, Any]
            The structured data payload to emit
        """
        pass

    @abstractmethod
    def has_permission(self, request: RequestType, namespace: str) -> bool:
        """
        Check if the given request has permission to access the channel identified by the namespace.
        """
        pass

    @abstractmethod
    def authenticate(self, request: RequestType) -> None:
        """
        Authenticate the request for the event emitter.
        """
        pass


# --- Permissions ---


class AbstractPermission(ABC):
    @abstractmethod
    def filter_queryset(
        self, request: RequestType, queryset: ORMQuerySet
    ) -> Any:  # type:ignore
        """
        Given the request, queryset, and set of CRUD actions, return a queryset filtered according
        to permission rules.
        """
        pass

    @abstractmethod
    def allowed_actions(
        self, request: RequestType, model: ORMModel
    ) -> Set[ActionType]:  # type:ignore
        """
        Return the set of CRUD actions the user is permitted to perform on the model.
        """
        pass

    @abstractmethod
    def allowed_object_actions(
        self, request: RequestType, obj: Any, model: ORMModel
    ) -> Set[ActionType]:  # type:ignore
        """
        Return the set of CRUD actions the user is permitted to perform on the specific object.
        """
        pass

    def bulk_operation_allowed(
        self,
        request: RequestType,
        items: ORMQuerySet,
        action_type: ActionType,
        model: type,
    ) -> bool:
        """
        Default bulk permission check that simply loops over 'items'
        and calls 'allowed_object_actions' on each one. If any item
        fails, raise PermissionDenied.
        """
        for obj in items:
            object_level_perms = self.allowed_object_actions(request, obj, model)
            if action_type not in object_level_perms:
                return False
        return True

    @abstractmethod
    def visible_fields(
        self, request: RequestType, model: ORMModel
    ) -> Union[Set[str], Literal["__all__"]]:  # type:ignore
        """
        Return the set of fields that are visible to the user for the given model and CRUD actions.
        """
        pass

    @abstractmethod
    def editable_fields(
        self, request: RequestType, model: ORMModel
    ) -> Union[Set[str], Literal["__all__"]]:  # type:ignore
        """
        Return the set of fields that are editable by the user for the given model and CRUD actions.
        """
        pass

    @abstractmethod
    def create_fields(
        self, request: RequestType, model: ORMModel
    ) -> Union[Set[str], Literal["__all__"]]:  # type:ignore
        """
        Return the set of fields that the user is allowed to specify in their create method
        """
        pass

class AbstractSearchProvider(ABC):
    """Base class for search providers in StateZero."""
    
    @abstractmethod
    def search(self, queryset: ORMQuerySet, query: str, search_fields: Union[Set[str], Literal["__all__"]]) -> ORMQuerySet:
        """
        Apply search filtering to a queryset.
        
        Args:
            queryset: Django queryset
            query: The search query string
            search_fields: Set of field names to search in
            
        Returns:
            Filtered queryset with search applied
        """
        pass

class AbstractQueryOptimizer(ABC):
    """
    Abstract Base Class for query optimizers.

    Defines the essential interface for optimizing a query object,
    potentially using configuration provided during initialization.
    """

    def __init__(
        self,
        depth: Optional[int] = None,
        fields_per_model: Optional[Dict[str, Set[str]]] = None,
        get_model_name_func: Optional[Callable[[Type[ORMModel]], str]] = None
    ):
        """
        Initializes the optimizer with common configuration potentially
        used for generating optimization parameters if not provided directly
        to the optimize method.

        Args:
            depth (Optional[int]): Default maximum relationship traversal depth
                if generating field paths automatically.
            fields_per_model (Optional[Dict[str, Set[str]]]): Default mapping of
                model names (keys) to sets of required field/relationship names
                (values), used if generating field paths automatically.
            get_model_name_func (Optional[Callable]): Default function to get a
                consistent string name for a model class, used with
                fields_per_model if generating field paths automatically.
        """
        self.default_depth = depth
        self.default_fields_per_model = fields_per_model
        self.default_get_model_name_func = get_model_name_func
        # Basic validation for depth if provided
        if self.default_depth is not None and self.default_depth < 0:
            raise ValueError("Depth cannot be negative.")

    @abstractmethod
    def optimize(
        self,
        queryset: Any,
        fields: Optional[List[str]] = None,
        **kwargs: Any
    ) -> Any:
        """
        Optimizes the given query object.

        Concrete implementations will use the provided queryset and potentially
        the 'fields' list or the configuration from __init__ to apply
        optimizations.

        Args:
            queryset (Any): The query object to optimize (e.g., a Django QuerySet).
            fields (Optional[List[str]]): An explicit list of field paths to optimize for.
                                         If provided, this typically overrides any
                                         automatic path generation based on init config.
            **kwargs: Additional optimization-specific parameters.

        Returns:
            Any: The optimized query object.

        Raises:
            NotImplementedError: If the concrete class doesn't implement this.
            ValueError: If required parameters (like 'fields' or init config
                        for generation) are missing.
        """
        raise NotImplementedError