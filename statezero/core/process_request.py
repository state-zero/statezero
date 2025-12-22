import logging
from typing import Any, Dict, Optional, Set, Type

from fastapi.encoders import jsonable_encoder

from statezero.core import AppConfig, ModelConfig, Registry
from statezero.core.ast_parser import ASTParser
from statezero.core.ast_validator import ASTValidator
from statezero.core.exceptions import PermissionDenied, ValidationError
from statezero.core.interfaces import (AbstractDataSerializer,
                                       AbstractORMProvider,
                                       AbstractSchemaGenerator)
from statezero.core.types import ActionType
from statezero.core.telemetry import create_telemetry_context, clear_telemetry_context

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def _filter_writable_data(
    data: Dict[str, Any],
    req: Any,
    model: Type,
    model_config: ModelConfig,
    orm_provider: AbstractORMProvider,
    create: bool = False,
) -> Dict[str, Any]:
    """
    Filter out keys for which the user does not have write permission.
    When `create` is True, use the permission's `create_fields` method;
    otherwise, use `editable_fields`.

    Only includes fields from permissions that allow the corresponding action
    (CREATE or UPDATE).

    If the allowed fields set contains "__all__", return the original data.
    """
    all_fields = orm_provider.get_fields(model)
    allowed_fields: Set[str] = set()

    # Determine which action we're checking for
    required_action = ActionType.CREATE if create else ActionType.UPDATE

    for permission_cls in model_config.permissions:
        perm = permission_cls()

        # Only include fields if this permission allows the required action
        if required_action not in perm.allowed_actions(req, model):
            continue

        if create:
            permission_fields = perm.create_fields(req, model)
        else:
            permission_fields = perm.editable_fields(req, model)
        # handle the __all__ shorthand
        if permission_fields == "__all__":
            permission_fields = all_fields
        else:
            permission_fields &= all_fields
        allowed_fields |= permission_fields

    return {k: v for k, v in data.items() if k in allowed_fields}


class RequestProcessor:
    def __init__(
        self,
        config: AppConfig,
        registry: Registry,
        orm_provider: AbstractORMProvider = None,
        data_serializer: AbstractDataSerializer = None,
        schema_generator: AbstractSchemaGenerator = None,
        schema_overrides: Dict = None,
    ):
        self.orm_provider = orm_provider or config.orm_provider
        self.data_serializer = data_serializer or config.serializer
        self.schema_generator = schema_generator or config.schema_generator
        self.schema_overrides = schema_overrides or config.schema_overrides
        self.registry = registry
        self.config = config

    def process_schema(self, req: Any) -> Dict[str, Any]:
        try:
            model_name: str = req.parser_context.get("kwargs", {}).get("model_name")
            model = self.orm_provider.get_model_by_name(model_name)
            config: ModelConfig = self.registry.get_config(model)

            # In production, check that the user has permission to at least one of the CRUD actions.
            # Skip this check if the request was authenticated via sync token (for CLI schema generation)
            is_sync_token_access = getattr(req, '_statezero_sync_token_access', False)
            if not self.config.DEBUG and not is_sync_token_access:
                allowed_actions: Set[ActionType] = set()
                for permission_cls in config.permissions:
                    allowed_actions |= permission_cls().allowed_actions(req, model)
                required_actions = {
                    ActionType.CREATE,
                    ActionType.READ,
                    ActionType.UPDATE,
                    ActionType.DELETE,
                }
                if allowed_actions.isdisjoint(required_actions):
                    raise PermissionDenied(
                        "User does not have any permissions required to access the schema."
                    )

            schema_meta = self.schema_generator.generate_schema(
                model=model,
                global_schema_overrides=self.schema_overrides,
                additional_fields=config.additional_fields,
            )
            schema_dict = schema_meta.model_dump()
            return jsonable_encoder(schema_dict)
        except Exception as e:
            logger.exception("Error in process_schema")
            raise ValidationError(str(e))

    def process_request(self, req: Any) -> Dict[str, Any]:
        # Get telemetry context (created by adaptor before calling this)
        from statezero.core.telemetry import get_telemetry_context
        telemetry_ctx = get_telemetry_context()

        body: Dict[str, Any] = req.data or {}
        ast_body: Dict[str, Any] = body.get("ast", {})
        initial_query_ast: Dict[str, Any] = ast_body.get("initial_query", {})
        final_query_ast: Dict[str, Any] = ast_body.get("query", {})

        # Record the query AST in telemetry
        if telemetry_ctx:
            telemetry_ctx.set_query_ast(final_query_ast)

        model_name: str = req.parser_context.get("kwargs", {}).get("model_name")
        model = self.orm_provider.get_model_by_name(model_name)
        model_config: ModelConfig = self.registry.get_config(model)

        base_queryset = self.orm_provider.get_queryset(
            req=req,
            model=model,
            initial_ast=initial_query_ast,
            registered_permissions=model_config.permissions,
        )

        # Step 1: Apply filter_queryset with OR logic (additive permissions)
        # Collect all filtered querysets from each permission
        filtered_querysets = []
        for permission_cls in model_config.permissions:
            perm = permission_cls()

            # Record permission class being applied
            if telemetry_ctx:
                permission_class_name = f"{permission_cls.__module__}.{permission_cls.__name__}"
                telemetry_ctx.record_permission_class_applied(permission_class_name)

            # Apply permission filter to a fresh base queryset
            filtered_qs = perm.filter_queryset(req, base_queryset)
            filtered_querysets.append(filtered_qs)

            # Record SQL after applying this permission
            if telemetry_ctx:
                try:
                    from statezero.core.query_cache import _get_sql_from_queryset
                    sql_data = _get_sql_from_queryset(filtered_qs)
                    if sql_data:
                        sql, _ = sql_data
                        telemetry_ctx.record_queryset_after_permission(permission_class_name, sql)
                except Exception:
                    pass  # Don't fail if we can't get SQL

        # Combine all filtered querysets with OR
        if filtered_querysets:
            combined_queryset = filtered_querysets[0]
            for qs in filtered_querysets[1:]:
                combined_queryset = combined_queryset | qs
            base_queryset = combined_queryset

        # Step 2: Apply exclude_from_queryset with AND logic (restrictive permissions)
        for permission_cls in model_config.permissions:
            perm = permission_cls()
            base_queryset = perm.exclude_from_queryset(req, base_queryset)

        # ---- PERMISSION CHECKS: Global Level (Write operations remain here) ----
        requested_actions: Set[ActionType] = ASTParser.get_requested_action_types(
            final_query_ast
        )

        allowed_global_actions: Set[ActionType] = set()
        for permission_cls in model_config.permissions:
            allowed_global_actions |= permission_cls().allowed_actions(req, model)
        if "__all__" not in allowed_global_actions:
            if not requested_actions.issubset(allowed_global_actions):
                missing = requested_actions - allowed_global_actions
                missing_str = ", ".join(action.value for action in missing)
                raise PermissionDenied(
                    f"Missing global permissions for actions: {missing_str}"
                )

        # For READ operations, delegate field permission checks to ASTValidator.
        serializer_options = ast_body.get("serializerOptions", {})

        # Invoke the ASTValidator to check read field permissions.
        model_graph = self.orm_provider.build_model_graph(model)
        validator = ASTValidator(
            model_graph=model_graph,
            get_model_name=self.orm_provider.get_model_name,
            registry=self.registry,
            request=req,
            get_model_by_name=self.orm_provider.get_model_by_name,
        )
        validator.validate_fields(final_query_ast, model)

        # ---- WRITE OPERATIONS: Filter incoming data to include only writable fields. ----
        op = final_query_ast.get("type")
        if op in ["create", "update"]:
            data = final_query_ast.get("data", {})
            # For create operations, pass create=True so that create_fields are used.
            filtered_data = _filter_writable_data(
                data, req, model, model_config, self.orm_provider, create=(op == "create")
            )
            final_query_ast["data"] = filtered_data
        elif op in ["get_or_create", "update_or_create"]:
            if "lookup" in final_query_ast:
                final_query_ast["lookup"] = _filter_writable_data(
                    final_query_ast["lookup"], req, model, model_config, self.orm_provider, create=True
                )
            if "defaults" in final_query_ast:
                final_query_ast["defaults"] = _filter_writable_data(
                    final_query_ast["defaults"], req, model, model_config, self.orm_provider, create=True
                )

        # Create and use the AST parser directly, instead of delegating to ORM provider
        parser = ASTParser(
            engine=self.orm_provider,
            serializer=self.data_serializer,
            model=model,
            config=self.config,
            registry=self.registry,
            base_queryset=base_queryset,  # Pass the queryset here
            serializer_options=serializer_options or {},
            request=req,
        )
        result: Dict[str, Any] = parser.parse(final_query_ast)

        # Note: Telemetry data is added by the adaptor (views.py)
        # AFTER DB query tracking context exits, so that all queries are captured

        return result
