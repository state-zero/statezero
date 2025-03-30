from typing import Set
import logging
from django.db.models import QuerySet
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
from django.db import connection

from statezero.core.interfaces import AbstractSearchProvider
from statezero.adaptors.django.config import registry

logger = logging.getLogger(__name__)

class PostgreSQLSearchProvider(AbstractSearchProvider):
    """
    PostgreSQL-specific search provider using full-text search capabilities.
    Uses a precomputed 'pg_search_vector' column if available and if the provided
    search_fields exactly match the expected model configuration (pulled from the registry);
    otherwise, builds the search vector dynamically from the given fields.
    """
    def search(self, queryset: QuerySet, query: str, search_fields: Set[str]) -> QuerySet:
        if not query or not query.strip() or not search_fields:
            return queryset

        # Pull expected_search_fields from the model configuration via the registry.
        model_config = registry.get_config(queryset.model)
        expected_search_fields = set(getattr(model_config, "searchable_fields", []))
        
        search_query = SearchQuery(query, search_type='websearch')
        
        use_precomputed = False
        if self._has_search_column(queryset):
            # Only use the precomputed column if the provided search_fields match the expected ones.
            if expected_search_fields and search_fields == expected_search_fields:
                use_precomputed = True

        if use_precomputed:
            return queryset.annotate(
                rank=SearchRank('pg_search_vector', search_query)
            ).filter(pg_search_vector=search_query).order_by('-rank')
        
        # Fallback: build the search vector dynamically using the provided fields.
        search_vector = SearchVector(*search_fields)
        return queryset.annotate(
            pg_search_vector=search_vector,
            rank=SearchRank(search_vector, search_query)
        ).filter(pg_search_vector=search_query).order_by('-rank')
    
    def _has_search_column(self, queryset: QuerySet) -> bool:
        table_name = queryset.model._meta.db_table
        with connection.cursor() as cursor:
            columns = [col.name for col in connection.introspection.get_table_description(cursor, table_name)]
        return 'pg_search_vector' in columns