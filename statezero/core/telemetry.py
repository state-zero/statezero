"""
Telemetry collection for debugging and performance analysis.

When enabled via config.enable_telemetry, this module tracks:
- Cache hits/misses with cache keys
- Database queries executed (count and SQL)
- Hook execution and data transformations
- Permission-validated fields
- Request processing timeline
"""
from typing import Any, Dict, List, Optional
from contextvars import ContextVar
import time

# Context variable to hold the current telemetry context
_telemetry_context: ContextVar[Optional['TelemetryContext']] = ContextVar('telemetry_context', default=None)


class TelemetryContext:
    """
    Collects telemetry data for a single request.
    """

    def __init__(self):
        self.enabled = False
        self.start_time = time.time()
        self.cache_hits: List[Dict[str, Any]] = []
        self.cache_misses: List[Dict[str, Any]] = []
        self.db_queries: List[Dict[str, Any]] = []
        self.hooks_executed: List[Dict[str, Any]] = []
        self.permission_fields: Dict[str, Any] = {}
        self.permission_classes: List[str] = []
        self.permission_field_breakdown: Dict[str, Any] = {}
        self.queryset_evolution: List[Dict[str, Any]] = []
        self.events: List[Dict[str, Any]] = []
        self.query_ast: Optional[Dict[str, Any]] = None

    def record_cache_hit(self, cache_key: str, operation_context: Optional[str] = None, sql: Optional[str] = None):
        """Record a cache hit."""
        if not self.enabled:
            return
        self.cache_hits.append({
            'cache_key': cache_key,
            'operation_context': operation_context,
            'sql_preview': sql[:200] if sql else None,
            'timestamp': time.time() - self.start_time
        })

    def record_cache_miss(self, cache_key: str, operation_context: Optional[str] = None, sql: Optional[str] = None):
        """Record a cache miss."""
        if not self.enabled:
            return
        self.cache_misses.append({
            'cache_key': cache_key,
            'operation_context': operation_context,
            'sql_preview': sql[:200] if sql else None,
            'timestamp': time.time() - self.start_time
        })

    def record_db_query(self, sql: str, params: Optional[tuple] = None, duration: Optional[float] = None):
        """Record a database query."""
        if not self.enabled:
            return
        self.db_queries.append({
            'sql': sql,
            'params': params,
            'duration_ms': duration * 1000 if duration else None,
            'timestamp': time.time() - self.start_time
        })

    def record_hook_execution(self, hook_name: str, hook_type: str, data_before: Any, data_after: Any, hook_path: Optional[str] = None):
        """Record hook execution and data transformation."""
        if not self.enabled:
            return
        self.hooks_executed.append({
            'hook_name': hook_name,
            'hook_type': hook_type,
            'hook_path': hook_path,
            'data_before': self._sanitize_data(data_before),
            'data_after': self._sanitize_data(data_after),
            'timestamp': time.time() - self.start_time
        })

    def record_permission_fields(self, model_name: str, operation_type: str, allowed_fields: List[str]):
        """Record permission-validated fields for a model."""
        if not self.enabled:
            return
        if model_name not in self.permission_fields:
            self.permission_fields[model_name] = {}
        self.permission_fields[model_name][operation_type] = allowed_fields

    def record_event(self, event_type: str, description: str, data: Optional[Dict] = None):
        """Record a generic event."""
        if not self.enabled:
            return
        self.events.append({
            'event_type': event_type,
            'description': description,
            'data': data,
            'timestamp': time.time() - self.start_time
        })

    def set_query_ast(self, ast: Dict[str, Any]):
        """Set the query AST for this request."""
        if not self.enabled:
            return
        self.query_ast = self._sanitize_data(ast)

    def record_permission_class_applied(self, permission_class: str):
        """Record that a permission class was applied."""
        if not self.enabled:
            return
        if permission_class not in self.permission_classes:
            self.permission_classes.append(permission_class)

    def record_permission_class_fields(self, permission_class: str, model_name: str, operation_type: str, fields: List[str]):
        """Record fields allowed by a specific permission class."""
        if not self.enabled:
            return

        if permission_class not in self.permission_field_breakdown:
            self.permission_field_breakdown[permission_class] = {}

        if model_name not in self.permission_field_breakdown[permission_class]:
            self.permission_field_breakdown[permission_class][model_name] = {}

        self.permission_field_breakdown[permission_class][model_name][operation_type] = fields

    def record_queryset_after_permission(self, permission_class: str, sql: Optional[str] = None):
        """Record the SQL state after applying a permission filter."""
        if not self.enabled:
            return

        self.queryset_evolution.append({
            'after_permission': permission_class,
            'sql_preview': sql[:300] if sql else None,
            'timestamp': time.time() - self.start_time
        })

    def _sanitize_data(self, data: Any) -> Any:
        """
        Sanitize data for telemetry output.
        Limits size and removes sensitive information.
        """
        if data is None:
            return None

        # Convert to string and limit length
        data_str = str(data)
        if len(data_str) > 1000:
            return data_str[:1000] + "... (truncated)"
        return data_str

    def get_telemetry_data(self) -> Dict[str, Any]:
        """
        Get all collected telemetry data.
        """
        if not self.enabled:
            return {}

        return {
            'enabled': True,
            'duration_ms': (time.time() - self.start_time) * 1000,
            'query_ast': self.query_ast,
            'cache': {
                'hits': len(self.cache_hits),
                'misses': len(self.cache_misses),
                'hit_details': self.cache_hits,
                'miss_details': self.cache_misses,
            },
            'database': {
                'query_count': len(self.db_queries),
                'queries': self.db_queries,
            },
            'hooks': {
                'count': len(self.hooks_executed),
                'executions': self.hooks_executed,
            },
            'permissions': {
                'classes_applied': self.permission_classes,
                'fields_by_model': self.permission_fields,
                'field_breakdown_by_permission_class': self.permission_field_breakdown,
                'queryset_evolution': self.queryset_evolution,
            },
            'events': self.events,
        }


def get_telemetry_context() -> Optional[TelemetryContext]:
    """Get the current telemetry context."""
    return _telemetry_context.get()


def set_telemetry_context(context: Optional[TelemetryContext]):
    """Set the current telemetry context."""
    _telemetry_context.set(context)


def create_telemetry_context(enabled: bool = False) -> TelemetryContext:
    """Create and activate a new telemetry context."""
    context = TelemetryContext()
    context.enabled = enabled
    set_telemetry_context(context)
    return context


def clear_telemetry_context():
    """Clear the current telemetry context."""
    set_telemetry_context(None)
