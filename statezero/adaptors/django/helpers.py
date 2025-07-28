from typing import Dict, Set, List, Optional, Callable, Type, Union, Any
from django.db import models
from django.db.models.query import QuerySet
from django.apps import apps
from django.core.exceptions import FieldDoesNotExist

def collect_models_by_type(
    obj, 
    fields_map: Dict[str, Set[str]], 
    collected: Optional[Dict[str, List[models.Model]]] = None,
    get_model_name: Optional[Callable[[Union[models.Model, Type[models.Model]]], str]] = None,
    visited: Optional[Set[str]] = None
) -> Dict[str, List[models.Model]]:
    """
    Collects model instances by their type based on a fields_map.
    Uses prefetched/preselected data that's already loaded.
    
    Args:
        obj: Django model instance or queryset
        fields_map: Dict mapping model names to sets of field names
                    e.g. {
                        "django_app.deepmodellevel1": {"level2"},
                        "django_app.deepmodellevel2": {"level3"},
                        "django_app.deepmodellevel3": {"name"}
                    }
        collected: Dict to store collected models by type
        get_model_name: Optional function to get model name in the format used in fields_map
        visited: Set of already visited instance IDs to prevent cycles
        
    Returns:
        Dict mapping model types to lists of model instances
    """
    # Initialize collection dictionary
    if collected is None:
        collected = {}
    
    # Initialize visited set to prevent cycles
    if visited is None:
        visited = set()
    
    # Handle querysets
    if isinstance(obj, (QuerySet, list, tuple)):
        for item in obj:
            collect_models_by_type(item, fields_map, collected, get_model_name, visited)
        return collected
    
    # Skip None objects
    if obj is None:
        return collected
    
    # Get model info using the provided function or default
    model = obj.__class__
    model_type = get_model_name(obj)
    
    # Create a unique ID for this instance to detect cycles
    instance_id = f"{model_type}:{obj.pk}"
    if instance_id in visited:
        # Already processed this instance
        return collected
    
    # Mark as visited
    visited.add(instance_id)
    
    # Add this model instance to the collection
    if model_type.lower() in [k.lower() for k in fields_map.keys()]:
        # Find the correct case in the fields_map
        for key in fields_map.keys():
            if key.lower() == model_type.lower():
                model_type = key
                break
        
        if model_type not in collected:
            collected[model_type] = []
        
        # Check if this instance is already in the collection
        if obj not in collected[model_type]:
            collected[model_type].append(obj)
    
    # Process related fields based on fields_map
    # Find the case-insensitive match
    model_key = None
    for key in fields_map.keys():
        if key.lower() == model_type.lower():
            model_key = key
            break
    
    allowed_fields = fields_map.get(model_key, set()) if model_key else set()
    
    # If no fields specified for this model, don't traverse further
    if not allowed_fields:
        return collected
    
    # Process each allowed field
    for field_name in allowed_fields:
        try:
            # Try to get model field definition
            field_def = model._meta.get_field(field_name)
            
            # Only process relation fields
            if field_def.is_relation:
                # Get the related value - this will use prefetched/selected data when available
                related_obj = getattr(obj, field_name)
                
                if related_obj is None:
                    continue
                
                # For many-to-many or reverse FK relations
                if field_def.many_to_many or field_def.one_to_many:
                    # This will use prefetch_related data if available
                    related_qs = related_obj.all()
                    collect_models_by_type(related_qs, fields_map, collected, get_model_name, visited)
                else:
                    # This will use select_related data if available
                    collect_models_by_type(related_obj, fields_map, collected, get_model_name, visited)
                    
        except FieldDoesNotExist:
            # Skip computed properties and non-existent fields
            continue
    
    return collected

def collect_from_queryset(
    data: Any, 
    fields_map: Dict[str, Set[str]],
    get_model_name: Optional[Callable[[Union[models.Model, Type[models.Model]]], str]] = None,
    get_model: Optional[Callable[[str], Type[models.Model]]] = None
) -> Dict[str, List[models.Model]]:
    """
    Collects model instances by type from a queryset or model instance.
    
    Args:
        data: Django model instance or queryset
        fields_map: Dict mapping model names to sets of field names
        get_model_name: Optional function to get model name in the format used in fields_map
        get_model: Optional function to get model class from a model name
        
    Returns:
        Dict with each model type pointing to a list of model instances
    """
    if data is None:
        return {}
    
    # Process data with the provided get_model_name function
    collected_models = collect_models_by_type(data, fields_map, get_model_name=get_model_name)
    
    # If get_model is provided and we want to ensure all keys in fields_map have entries
    if get_model:
        for model_name in fields_map.keys():
            if model_name not in collected_models:
                # Create an empty list for model types that weren't collected
                collected_models[model_name] = []
    
    return collected_models