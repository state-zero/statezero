from __future__ import annotations

from abc import ABC, abstractmethod
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
    Literal,
    Protocol,
)

from statezero.core.classes import ModelSchemaMetadata, SchemaFieldMetadata
from statezero.core.types import (
    ActionType,
    ORMField,
    ORMModel,
    ORMQuerySet,
    RequestType,
)


class AbstractORMProvider(ABC):
    """
    A merged ORM engine interface that combines both query building (filtering,
    ordering, aggregation, etc.) and ORM provider responsibilities (queryset assembly,
    event signal registration, model graph construction, etc.).
    """

    # === Query Engine Methods ===

    @abstractmethod
    def validate(
        self,
        model: Type,
        data: Dict[str, Any],
        validate_type: str,
        partial: bool,
        request: Any,
        permissions: List[Type],
        serializer: Any,
    ) -> bool:
        """
        Validate model data without saving to database.

        Args:
            model: The model class to validate against
            data: Data to validate
            validate_type: 'create' or 'update'
            partial: Whether to allow partial validation (only validate provided fields)
            request: Request object for permission context
            permissions: List of permission classes
            serializer: Serializer instance for validation

        Returns:
            bool: True if validation passes

        Raises:
            ValidationError: For serializer validation failures
            PermissionDenied: For permission failures
        """
        pass

    @abstractmethod
    def get_fields(self, model: ORMModel) -> Set[str]:
        """
        Get all of the model fields - doesn't apply permissions check.
        Includes both database fields and additional_fields (computed fields).
        """
        pass

    @abstractmethod
    def get_db_fields(self, model: ORMModel) -> Set[str]:
        """
        Get only the actual database fields for a model.
        Excludes read-only additional_fields (computed fields).
        Used for deserialization - hooks can write to any DB field.
        """
        pass

    @abstractmethod
    def filter_node(self, queryset: ORMQuerySet, node: Dict[str, Any]) -> ORMQuerySet:
        """
        Apply filter/and/or/not logic to the queryset and return new queryset.
        """
        pass

    @abstractmethod
    def search_node(
        self, queryset: ORMQuerySet, search_query: str, search_fields: Set[str]
    ) -> ORMQuerySet:
        """
        Apply search to the queryset and return new queryset.
        """
        pass

    @abstractmethod
    def exclude_node(self, queryset: ORMQuerySet, node: Dict[str, Any]) -> ORMQuerySet:
        """
        Apply exclude logic to the queryset and return new queryset.
        """
        pass

    @abstractmethod
    def order_by(self, queryset: ORMQuerySet, order_list: List[str]) -> ORMQuerySet:
        """
        Order the queryset based on a list of fields and return new queryset.
        """
        pass

    @abstractmethod
    def select_related(
        self, queryset: ORMQuerySet, related_fields: List[str]
    ) -> ORMQuerySet:
        """
        Optimize the queryset by eager loading the given related fields and return new queryset.
        """
        pass

    @abstractmethod
    def prefetch_related(
        self, queryset: ORMQuerySet, related_fields: List[str]
    ) -> ORMQuerySet:
        """
        Optimize the queryset by prefetching the given related fields and return new queryset.
        """
        pass

    @abstractmethod
    def select_fields(self, queryset: ORMQuerySet, fields: List[str]) -> ORMQuerySet:
        """
        Select only specific fields from the queryset and return new queryset.
        """
        pass

    @abstractmethod
    def fetch_list(
        self,
        queryset: ORMQuerySet,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        req: Optional[RequestType] = None,
        permissions: Optional[List[Type]] = None,
    ) -> ORMQuerySet:
        """
        Return a sliced queryset based on pagination with permission checks.
        """
        pass

    # === Aggregate Methods ===

    @abstractmethod
    def aggregate(
        self, queryset: ORMQuerySet, agg_list: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Aggregate the queryset based on the provided functions.
        Example:
          [
            {'function': 'count', 'field': 'id', 'alias': 'id_count'},
            {'function': 'sum',   'field': 'price', 'alias': 'price_sum'}
          ]
        """
        pass

    @abstractmethod
    def count(self, queryset: ORMQuerySet, field: str) -> int:
        """Count the number of records for the given field."""
        pass

    @abstractmethod
    def sum(self, queryset: ORMQuerySet, field: str) -> Any:
        """Sum the values of the given field."""
        pass

    @abstractmethod
    def avg(self, queryset: ORMQuerySet, field: str) -> Any:
        """Calculate the average of the given field."""
        pass

    @abstractmethod
    def min(self, queryset: ORMQuerySet, field: str) -> Any:
        """Find the minimum value for the given field."""
        pass

    @abstractmethod
    def max(self, queryset: ORMQuerySet, field: str) -> Any:
        """Find the maximum value for the given field."""
        pass

    @abstractmethod
    def first(self, queryset: ORMQuerySet) -> Any:
        """Return the first record from the queryset."""
        pass

    @abstractmethod
    def last(self, queryset: ORMQuerySet) -> Any:
        """Return the last record from the queryset."""
        pass

    @abstractmethod
    def exists(self, queryset: ORMQuerySet) -> bool:
        """Return True if the queryset has any results; otherwise False."""
        pass

    # === CRUD Methods ===

    @abstractmethod
    def create(
        self, model: Type[ORMModel], data: Dict[str, Any], *args, **kwargs
    ) -> Any:
        """Create a new record using the model class."""
        pass

    @abstractmethod
    def bulk_create(
        self,
        model: Type[ORMModel],
        data_list: List[Dict[str, Any]],
        *args,
        **kwargs
    ) -> List[Any]:
        """
        Create multiple records using the model class.
        Returns a list of created instances.
        """
        pass

    @abstractmethod
    def update(
        self,
        queryset: ORMQuerySet,
        node: Dict[str, Any],
        req: RequestType,
        permissions: List[Type],
        readable_fields: Optional[Set[str]] = None,
    ) -> Tuple[int, List[Any]]:
        """
        Update records in the queryset.
        Returns tuple of (number of rows updated, updated instances).
        """
        pass

    @abstractmethod
    def delete(
        self,
        queryset: ORMQuerySet,
        node: Dict[str, Any],
        req: RequestType,
        permissions: List[Type],
    ) -> Tuple[int, Any]:
        """
        Delete records in the queryset.
        Returns tuple of (number of rows deleted, deleted instance data).
        """
        pass

    @abstractmethod
    def get(
        self,
        queryset: ORMQuerySet,
        node: Dict[str, Any],
        req: RequestType,
        permissions: List[Type],
    ) -> Any:
        """
        Retrieve a single record from the queryset.
        Raises an error if multiple or none are found.
        """
        pass

    @abstractmethod
    def get_or_create(
        self,
        queryset: ORMQuerySet,
        node: Dict[str, Any],
        serializer: Any,
        req: RequestType,
        permissions: List[Type],
        create_fields_map: Dict[str, Set[str]],
    ) -> Tuple[Any, bool]:
        """
        Retrieve a record if it exists, otherwise create it.
        Returns a tuple of (instance, created_flag).
        """
        pass

    @abstractmethod
    def update_or_create(
        self,
        queryset: ORMQuerySet,
        node: Dict[str, Any],
        req: RequestType,
        serializer: Any,
        permissions: List[Type],
        update_fields_map: Dict[str, Set[str]],
        create_fields_map: Dict[str, Set[str]],
    ) -> Tuple[Any, bool]:
        """
        Update a record if it exists or create it if it doesn't.
        Returns a tuple of (instance, created_flag).
        """
        pass

    @abstractmethod
    def update_instance(
        self,
        model: Type[ORMModel],
        ast: Dict[str, Any],
        req: RequestType,
        permissions: List[Type],
        serializer: Any,
        fields_map: Dict[str, Set[str]],
    ) -> Any:
        """Update a single model instance by filter."""
        pass

    @abstractmethod
    def delete_instance(
        self,
        model: Type[ORMModel],
        ast: Dict[str, Any],
        req: RequestType,
        permissions: List[Type],
    ) -> int:
        """Delete a single model instance by filter."""
        pass

    # === ORM Provider Methods (Unchanged - these are utility methods) ===

    @abstractmethod
    def get_queryset(
        self,
        request: RequestType,
        model: ORMModel,  # type:ignore
        initial_ast: Dict[str, Any],
        registered_permissions: List[Type],
    ) -> Any:
        """
        Assemble and return the base QuerySet (or equivalent) for the given model.
        This method considers the request context, initial AST (filters, sorting, etc.),
        and any model-specific permission restrictions.
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
    def get_user(self, request: RequestType):  # returns User
        """
        Get the request user.
        """
        pass

    @abstractmethod
    def build_model_graph(self, model: ORMModel) -> Any:  # type:ignore
        """
        Construct a graph representation of model relationships.
        """
        pass


# === Other Abstract Classes (Unchanged) ===


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
        data: Union[dict, List[dict]],
        allowed_fields: Optional[Dict[str, Set[str]]] = None,
        request: Optional[Any] = None,
        many: bool = False,
    ) -> Union[dict, List[dict]]:
        """
        Deserialize the input data into validated Python types for the specified model.
        - `allowed_fields`: a mapping (by model name) of fields the user is allowed to edit.
        - `many`: if True, expects data to be a list of dicts and returns a list of validated dicts.

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


class AbstractActionPermission(ABC):
    """
    Permission class for StateZero actions.
    Similar to DRF BasePermission but with access to validated data and
    gives the action instead of the view.
    """

    @abstractmethod
    def has_permission(self, request, action_name: str) -> bool:
        """
        View-level permission check (before validation).
        Similar to DRF BasePermission.has_permission
        """
        pass

    @abstractmethod
    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        """
        Action-level permission check (after validation).
        This is where you check permissions that depend on the actual data.
        """
        pass

class AbstractPermission(ABC):
    @abstractmethod
    def filter_queryset(
        self, request: RequestType, queryset: ORMQuerySet
    ) -> Any:  # type:ignore
        """
        Given the request, queryset, and set of CRUD actions, return a queryset filtered according
        to permission rules.

        When multiple permissions are registered, their filter_queryset results are combined
        with OR logic (additive) - a row is visible if it passes ANY permission's filter.
        """
        pass

    def exclude_from_queryset(
        self, request: RequestType, queryset: ORMQuerySet
    ) -> Any:  # type:ignore
        """
        Given the request and queryset, return a queryset with rows excluded according
        to permission rules.

        When multiple permissions are registered, their exclude_from_queryset results are combined
        with AND logic (restrictive) - a row is excluded if it fails ANY permission's exclusion check.

        By default, no rows are excluded. Override this method to implement exclusion logic.
        """
        return queryset

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
    def search(
        self,
        queryset: ORMQuerySet,
        query: str,
        search_fields: Union[Set[str], Literal["__all__"]],
    ) -> ORMQuerySet:
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
        get_model_name_func: Optional[Callable[[Type[ORMModel]], str]] = None,
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
        self, queryset: Any, fields: Optional[List[str]] = None, **kwargs: Any
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
