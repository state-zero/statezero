"""
Database query telemetry tracker for Django.

This module provides a context manager that tracks database queries
and records them to telemetry when enabled.
"""
from contextlib import contextmanager
from django.db import connection
from django.test.utils import CaptureQueriesContext

from statezero.core.telemetry import get_telemetry_context


@contextmanager
def track_db_queries():
    """
    Context manager that tracks database queries and records them to telemetry.

    Usage:
        with track_db_queries():
            # Execute database operations
            queryset.all()
    """
    telemetry_ctx = get_telemetry_context()

    # Only track if telemetry is enabled
    if not telemetry_ctx or not telemetry_ctx.enabled:
        yield
        return

    # Use Django's CaptureQueriesContext to track queries
    with CaptureQueriesContext(connection) as queries_context:
        yield

    # Record all captured queries to telemetry
    for query_dict in queries_context.captured_queries:
        sql = query_dict.get('sql', '')
        duration = float(query_dict.get('time', 0))

        telemetry_ctx.record_db_query(
            sql=sql,
            params=None,  # Django already interpolates params into sql
            duration=duration
        )
