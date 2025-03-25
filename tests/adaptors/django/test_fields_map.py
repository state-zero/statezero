import unittest
from unittest.mock import MagicMock
from typing import Type, Any, Set

from django.test import TestCase

from ormbridge.core.constants import ALL_FIELDS
from ormbridge.core.ast_parser import ASTParser
from ormbridge.adaptors.django.orm import DjangoORMAdapter
from ormbridge.adaptors.django.permissions import AllowAllPermission
from tests.django_app.permissions import RestrictedFieldsPermission
from ormbridge.adaptors.django.serializers import DRFDynamicSerializer
from ormbridge.adaptors.django.config import config, registry
from ormbridge.core.constants import ALL_FIELDS
from ormbridge.core.interfaces import AbstractPermission
from ormbridge.core.types import ActionType, ORMModel, RequestType

# Import the test models
from tests.django_app.models import (
    ParentTestModel, 
    ChildTestModel, 
    GrandChildTestModel
)

class BasePermission:
    """Base permission class for testing"""
    
    def filter_queryset(self, request: RequestType, queryset: Any) -> Any:
        return queryset

    def allowed_actions(self, request: RequestType, model: Type[ORMModel]) -> Set[ActionType]:
        return {
            ActionType.CREATE,
            ActionType.DELETE,
            ActionType.READ,
            ActionType.UPDATE,
        }

    def allowed_object_actions(self, request: RequestType, obj: Any, model: Type[ORMModel]) -> Set[ActionType]:
        return {
            ActionType.CREATE,
            ActionType.DELETE,
            ActionType.READ,
            ActionType.UPDATE,
        }

    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return {ALL_FIELDS}

    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return {ALL_FIELDS}

    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return {ALL_FIELDS}

class RestrictedPermission(BasePermission):
    """Permission class with restricted fields"""
    
    def __init__(self, allowed_fields=None):
        self.allowed_fields = allowed_fields or set()
    
    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return self.allowed_fields
    
    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return self.allowed_fields
    
    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return self.allowed_fields

class DenyPermission(BasePermission):
    """Permission class that denies access"""
    
    def allowed_actions(self, request: RequestType, model: Type[ORMModel]) -> Set[ActionType]:
        return set()  # No actions allowed

    def allowed_object_actions(self, request: RequestType, obj: Any, model: Type[ORMModel]) -> Set[ActionType]:
        return set()  # No actions allowed
    
    def visible_fields(self, request: RequestType, model: Type) -> Set[str]:
        return set()  # No fields visible
    
    def editable_fields(self, request: RequestType, model: Type) -> Set[str]:
        return set()  # No fields editable
    
    def create_fields(self, request: RequestType, model: Type) -> Set[str]:
        return set()  # No fields creatable

class TestASTParserPermissions(TestCase):
    """
    Tests for the ASTParser's permission handling.
    This version uses the actual registry and config, updated to reflect that reverse 
    relationships are not traversed.
    """
    
    def setUp(self):
        # Models should already be registered in the registry.
        # Create mock objects for engine, serializer, and request.
        self.engine = MagicMock(spec=DjangoORMAdapter)
        self.serializer = MagicMock(spec=DRFDynamicSerializer)
        self.request = MagicMock()
        
        # Create ASTParser with ParentTestModel as the base model.
        self.parser = ASTParser(
            engine=self.engine,
            serializer=self.serializer,
            model=ParentTestModel,
            config=config,
            registry=registry,
            request=self.request,
            serializer_options={}
        )

    def test_has_read_permission_with_all_allow(self):
        """Test that _has_read_permission returns True with AllowAllPermission"""
        # The AllowAllPermission should already be configured for the model.
        result = self.parser._has_read_permission(ParentTestModel)
        self.assertTrue(result)

    def test_has_read_permission_with_deny(self):
        """Test that _has_read_permission returns False when all permissions deny access"""
        # Save original permissions.
        original_permissions = registry.get_config(ParentTestModel)._permissions
        
        # Override permissions temporarily.
        registry.get_config(ParentTestModel)._permissions = [DenyPermission]
        
        result = self.parser._has_read_permission(ParentTestModel)
        self.assertFalse(result)
        
        # Restore original permissions.
        registry.get_config(ParentTestModel)._permissions = original_permissions

    def test_has_read_permission_with_mixed_permissions(self):
        """Test that _has_read_permission returns True when at least one permission grants access"""
        # Save original permissions.
        original_permissions = registry.get_config(ParentTestModel)._permissions
        
        # Override permissions temporarily.
        registry.get_config(ParentTestModel)._permissions = [DenyPermission, AllowAllPermission]
        
        result = self.parser._has_read_permission(ParentTestModel)
        self.assertTrue(result)
        
        # Restore original permissions.
        registry.get_config(ParentTestModel)._permissions = original_permissions

    def test_allowed_fields_for_model(self):
        """Test that _allowed_fields_for_model returns the registered fields for a model"""
        # AllowAllPermission returns ALL_FIELDS, which means all fields are allowed.
        result = self.parser._allowed_fields_for_model(ParentTestModel)
        self.assertEqual(result, {ALL_FIELDS})
        
        # Save original permissions.
        original_permissions = registry.get_config(ParentTestModel)._permissions
        
        # Create a custom RestrictedFieldsPermission class instance.
        class CustomRestrictedPermission(RestrictedFieldsPermission):
            def visible_fields(self, request, model):
                return {"name"}
        
        # Override permissions temporarily.
        registry.get_config(ParentTestModel)._permissions = [CustomRestrictedPermission]
        
        result = self.parser._allowed_fields_for_model(ParentTestModel)
        self.assertEqual(result, {"name"})
        
        # Restore original permissions.
        registry.get_config(ParentTestModel)._permissions = original_permissions

    def test_get_depth_based_fields(self):
        """Test that _get_depth_based_fields includes only forward relationships"""
        # Get depth-based fields with depth 2.
        result = self.parser._get_depth_based_fields(depth=2)
        
        # Get model name using the ORM provider for ParentTestModel.
        parent_model_name = config.orm_provider.get_model_name(ParentTestModel)
        
        # Since we don't traverse reverse relations, only the parent model should be in the result.
        self.assertIn(parent_model_name, result)
        
        # Check field sets for the parent model.
        # We expect fields from the model, but no reverse relation fields.
        self.assertIn("name", result[parent_model_name])
        self.assertIn("description", result[parent_model_name])
        
        # The reverse relations should not be followed.
        self.assertEqual(len(result), 1, "Only the parent model should be included in the result")

    def test_get_depth_based_fields_with_depth(self):
        """Test that _get_depth_based_fields respects depth parameter"""
        # Get depth-based fields with depth 0 (only the root model).
        result = self.parser._get_depth_based_fields(depth=0)
        
        parent_model_name = config.orm_provider.get_model_name(ParentTestModel)
        
        # Only ParentTestModel should be in the result.
        self.assertIn(parent_model_name, result)
        self.assertEqual(len(result), 1, "Only the parent model should be included at depth 0")
        
        # Now test with depth 1 - since we don't follow reverse relations, depth shouldn't affect the result.
        result = self.parser._get_depth_based_fields(depth=1)
        self.assertIn(parent_model_name, result)
        self.assertEqual(len(result), 1, "Still only parent model should be included at depth 1")

    def test_get_depth_based_fields_with_permission_denied(self):
        """Test that _get_depth_based_fields skips models where permission is denied"""
        # Save original permissions for ChildTestModel.
        original_permissions = registry.get_config(ChildTestModel)._permissions
        
        # Override permissions for ChildTestModel to deny access.
        registry.get_config(ChildTestModel)._permissions = [DenyPermission]
        
        # Get depth-based fields with depth 2.
        result = self.parser._get_depth_based_fields(depth=2)
        
        parent_model_name = config.orm_provider.get_model_name(ParentTestModel)
        child_model_name = config.orm_provider.get_model_name(ChildTestModel)
        
        # Only the parent should be included since reverse relations are not traversed.
        self.assertIn(parent_model_name, result)
        self.assertNotIn(child_model_name, result)
        self.assertEqual(len(result), 1, "Only the parent model should be included in the result")
        
        # Restore original permissions.
        registry.get_config(ChildTestModel)._permissions = original_permissions

    def test_get_permissioned_fields_with_requested_fields(self):
        """Test get_permissioned_fields with requested fields that override depth-based fields"""
        # Create a parser with requested fields.
        parser = ASTParser(
            engine=self.engine,
            serializer=self.serializer,
            model=ParentTestModel,
            config=config,
            registry=registry,
            request=self.request,
            serializer_options={"fields": ["name", "description", "children__name"]}
        )
        
        # Get merged fields.
        result = parser.get_permissioned_fields(depth=1)
        
        parent_model_name = config.orm_provider.get_model_name(ParentTestModel)
        child_model_name = config.orm_provider.get_model_name(ChildTestModel)
        
        # ParentTestModel should have both name and description, and include the relationship key "children".
        self.assertIn("name", result[parent_model_name])
        self.assertIn("description", result[parent_model_name])
        self.assertIn("children", result[parent_model_name])
        
        # Since reverse relations are not traversed, no separate child model mapping should be present.
        self.assertEqual(len(result), 1, "Only parent model should be in the result")

    def test_get_permissioned_fields_with_empty_requested_fields(self):
        """Test get_permissioned_fields with no requested fields, relying on depth-based fields only"""
        # Get merged fields with no requested fields.
        result = self.parser.get_permissioned_fields(depth=1)
        
        parent_model_name = config.orm_provider.get_model_name(ParentTestModel)
        child_model_name = config.orm_provider.get_model_name(ChildTestModel)
        
        # ParentTestModel should have fields from depth-based traversal.
        self.assertIn("name", result[parent_model_name])
        self.assertNotIn("children", result[parent_model_name])
        
        # Since reverse relations are not traversed, no child model should be included.
        self.assertEqual(len(result), 1, "Only parent model should be in the result")

    def test_get_permissioned_fields_with_overlapping_fields(self):
        """Test get_permissioned_fields when requested fields overlap with depth-based fields"""
        # Create a parser with requested fields that include nested paths.
        parser = ASTParser(
            engine=self.engine,
            serializer=self.serializer,
            model=ParentTestModel,
            config=config,
            registry=registry,
            request=self.request,
            serializer_options={"fields": ["name", "children__name", "children__extra"]}
        )
        
        # Get merged fields.
        result = parser.get_permissioned_fields(depth=1)
        
        parent_model_name = config.orm_provider.get_model_name(ParentTestModel)
        child_model_name = config.orm_provider.get_model_name(ChildTestModel)
        
        # Since reverse relations are not traversed, only the parent model's mapping is returned.
        self.assertIn("name", result[parent_model_name])
        self.assertIn("children", result[parent_model_name])
        self.assertEqual(len(result), 1, "Only parent model should be in the result")

    def test_process_requested_fields(self):
        """Test _process_requested_fields with nested field paths"""
        # Process requested fields with nested paths.
        result = self.parser._process_requested_fields([
            "name", 
            "description",
            "children__name",
            "children__grandchildren__name"
        ])
        
        parent_model_name = config.orm_provider.get_model_name(ParentTestModel)
        child_model_name = config.orm_provider.get_model_name(ChildTestModel)
        grandchild_model_name = config.orm_provider.get_model_name(GrandChildTestModel)
        
        # With reverse relationships not traversed, only the parent model's fields are processed.
        self.assertEqual(result[parent_model_name], {"name", "description", "children", "grandchildren"})
        self.assertNotIn(child_model_name, result)
        self.assertNotIn(grandchild_model_name, result)
        self.assertEqual(len(result), 1, "Only parent model should be in the result")