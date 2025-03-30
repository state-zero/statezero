from typing import Set
from django.db.models import QuerySet, Q
from statezero.core.interfaces import AbstractSearchProvider

class BasicSearchProvider(AbstractSearchProvider):
    """Simple search provider using basic Django field lookups."""
    
    def search(self, queryset: QuerySet, query: str, search_fields: Set[str]) -> QuerySet:
        """Apply search using basic field lookups."""
        if not search_fields or not query or not query.strip():
            return queryset
            
        # Split the query into individual terms.
        terms = [term.strip() for term in query.split() if term.strip()]
        if not terms:
            return queryset
            
        # Build Q objects to OR across fields and terms.
        q_objects = Q()
        for field in search_fields:
            for term in terms:
                q_objects |= Q(**{f"{field}__icontains": term})
                
        return queryset.filter(q_objects)