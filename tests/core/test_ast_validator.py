import unittest

import networkx as nx
from django.test import TestCase

from statezero.adaptors.django.config import registry
from statezero.adaptors.django.orm import DjangoORMAdapter
from statezero.core.ast_validator import ASTValidator
from statezero.core.config import ModelConfig
from statezero.core.exceptions import PermissionDenied
from statezero.core.interfaces import AbstractPermission
from statezero.core.types import ActionType
# Import your test models.
from tests.django_app.models import (ComprehensiveModel, DeepModelLevel1,
                                     DeepModelLevel2, DeepModelLevel3,
                                     DummyModel, DummyRelatedModel)


# -------------------------------------------------------------------------
# DummyPermission: Always allows READ and returns all expected visible fields.
# -------------------------------------------------------------------------
class DummyPermission(AbstractPermission):
    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        # Always allow READ.
        return {ActionType.READ}

    def allowed_object_actions(self, request, obj, model):
        return {ActionType.READ}

    def visible_fields(self, request, model):
        if model == DummyModel:
            return {"name", "value", "related", "computed"}
        elif model == DummyRelatedModel:
            return {"name"}
        elif model == DeepModelLevel1:
            return {"name", "level2", "comprehensive_models"}
        elif model == DeepModelLevel2:
            return {"name", "level3"}
        elif model == DeepModelLevel3:
            return {"name"}
        elif model == ComprehensiveModel:
            return {"name", "value"}
        return set()

    def editable_fields(self, request, model):
        return self.visible_fields(request, model)
    
    def create_fields(self, request, model):
        return self.editable_fields(request, model)


# -------------------------------------------------------------------------
# DenyReadPermission: Denies READ permission even if visible_fields are set.
# -------------------------------------------------------------------------
class DenyReadPermission(AbstractPermission):
    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        # Deny all actions including READ.
        return set()

    def allowed_object_actions(self, request, obj, model):
        return set()

    def visible_fields(self, request, model):
        # Even if some fields are declared visible, without READ permission they won't matter.
        if model == DummyModel:
            return {"name", "value", "related", "computed"}
        return set()

    def editable_fields(self, request, model):
        return self.visible_fields(request, model)
    
    def create_fields(self, request, model):
        return self.editable_fields(request, model)


# -------------------------------------------------------------------------
# MixedPermission: Allows READ for one model but denies READ for its related model.
# For example, allow READ for DummyModel but not for DummyRelatedModel.
# -------------------------------------------------------------------------
class MixedPermission(AbstractPermission):
    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        if model == DummyModel:
            return {ActionType.READ}
        elif model == DummyRelatedModel:
            return set()  # Deny READ on the related model.
        return {ActionType.READ}

    def allowed_object_actions(self, request, obj, model):
        return {ActionType.READ}

    def visible_fields(self, request, model):
        if model == DummyModel:
            return {"name", "value", "related", "computed"}
        elif model == DummyRelatedModel:
            return {"name"}  # Field is visible but READ is not allowed.
        return set()

    def editable_fields(self, request, model):
        return self.visible_fields(request, model)
    
    def create_fields(self, request, model):
        return self.editable_fields(request, model)


# -------------------------------------------------------------------------
# PartialPermission: Allows READ but only a subset of fields.
# -------------------------------------------------------------------------
class PartialPermission(AbstractPermission):
    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        return {ActionType.READ}

    def allowed_object_actions(self, request, obj, model):
        return {ActionType.READ}

    def visible_fields(self, request, model):
        if model == DummyModel:
            # Exclude 'value' from visible fields.
            return {"name", "related", "computed"}
        elif model == DummyRelatedModel:
            return {"name"}
        return set()

    def editable_fields(self, request, model):
        return self.visible_fields(request, model)
    
    def create_fields(self, request, model):
        return self.editable_fields(request, model)


# -------------------------------------------------------------------------
# Extended tests for ASTValidator.
# -------------------------------------------------------------------------
class TestASTValidator(TestCase):
    def setUp(self):
        # Create an instance of the DjangoORMAdapter.
        self.adapter = DjangoORMAdapter()
        # Save registry state so we can restore it after each test.
        self._saved_registry = dict(registry._models_config)

    def tearDown(self):
        # Restore the original registry to avoid polluting other test suites.
        registry._models_config.clear()
        registry._models_config.update(self._saved_registry)

    def register_models(self, permission_class):
        """Helper to clear and register models with a given permission class."""
        registry._models_config.clear()
        registry.register(
            DummyModel, ModelConfig(DummyModel, permissions=[permission_class])
        )
        registry.register(
            DummyRelatedModel,
            ModelConfig(DummyRelatedModel, permissions=[permission_class]),
        )
        registry.register(
            DeepModelLevel1,
            ModelConfig(DeepModelLevel1, permissions=[permission_class]),
        )
        registry.register(
            DeepModelLevel2,
            ModelConfig(DeepModelLevel2, permissions=[permission_class]),
        )
        registry.register(
            DeepModelLevel3,
            ModelConfig(DeepModelLevel3, permissions=[permission_class]),
        )
        registry.register(
            ComprehensiveModel,
            ModelConfig(ComprehensiveModel, permissions=[permission_class]),
        )

    def test_dummy_model_valid(self):
        # Use DummyPermission.
        self.register_models(DummyPermission)
        dummy_graph = self.adapter.build_model_graph(DummyModel)
        validator = ASTValidator(
            model_graph=dummy_graph,
            get_model_name=self.adapter.get_model_name,
            registry=registry,
            request={},  # dummy request object
            get_model_by_name=self.adapter.get_model_by_name,
        )
        # Valid AST for DummyModel:
        # Requesting "name" (DummyModel.name) and nested "related__name" (DummyRelatedModel.name).
        ast = {"serializerOptions": {"fields": ["name", "related__name"]}}
        try:
            validator.validate_fields(ast, DummyModel)
        except PermissionDenied:
            self.fail(
                "PermissionDenied was raised unexpectedly for valid DummyModel fields."
            )

    def test_dummy_model_invalid_field(self):
        # Use DummyPermission.
        self.register_models(DummyPermission)
        dummy_graph = self.adapter.build_model_graph(DummyModel)
        validator = ASTValidator(
            model_graph=dummy_graph,
            get_model_name=self.adapter.get_model_name,
            registry=registry,
            request={},
            get_model_by_name=self.adapter.get_model_by_name,
        )
        # Invalid AST: "related__nonexistent" is not allowed.
        ast = {"serializerOptions": {"fields": ["name", "related__nonexistent"]}}
        with self.assertRaises(PermissionDenied):
            validator.validate_fields(ast, DummyModel)

    def test_deep_model_valid(self):
        # Use DummyPermission.
        self.register_models(DummyPermission)
        deep_graph = self.adapter.build_model_graph(DeepModelLevel1)
        validator = ASTValidator(
            model_graph=deep_graph,
            get_model_name=self.adapter.get_model_name,
            registry=registry,
            request={},
            get_model_by_name=self.adapter.get_model_by_name,
        )
        # Valid AST for DeepModelLevel1:
        # "level2__level3__name" should be allowed (DeepModelLevel1 -> DeepModelLevel2 -> DeepModelLevel3)
        # and "comprehensive_models__name" should be allowed (comprehensive_models points to DummyModel).
        ast = {
            "serializerOptions": {
                "fields": ["name", "level2__level3__name", "comprehensive_models__name"]
            }
        }
        try:
            validator.validate_fields(ast, DeepModelLevel1)
        except PermissionDenied:
            self.fail(
                "PermissionDenied was raised unexpectedly for valid deep model fields."
            )

    def test_deep_model_invalid_intermediate_field(self):
        # Use DummyPermission.
        self.register_models(DummyPermission)
        deep_graph = self.adapter.build_model_graph(DeepModelLevel1)
        validator = ASTValidator(
            model_graph=deep_graph,
            get_model_name=self.adapter.get_model_name,
            registry=registry,
            request={},
            get_model_by_name=self.adapter.get_model_by_name,
        )
        # Invalid AST: "level2__nonexistent" should fail.
        ast = {"serializerOptions": {"fields": ["name", "level2__nonexistent"]}}
        with self.assertRaises(PermissionDenied):
            validator.validate_fields(ast, DeepModelLevel1)

        # Also, requesting a non-permitted field from comprehensive_models.
        ast2 = {
            "serializerOptions": {
                "fields": ["name", "comprehensive_models__nonexistent"]
            }
        }
        with self.assertRaises(PermissionDenied):
            validator.validate_fields(ast2, DeepModelLevel1)

    def test_no_read_permission_root(self):
        # Use DenyReadPermission so that READ is not allowed on the root model.
        self.register_models(DenyReadPermission)
        dummy_graph = self.adapter.build_model_graph(DummyModel)
        validator = ASTValidator(
            model_graph=dummy_graph,
            get_model_name=self.adapter.get_model_name,
            registry=registry,
            request={},
            get_model_by_name=self.adapter.get_model_by_name,
        )
        # Even though visible_fields returns some fields, without READ the AST should be rejected.
        ast = {"serializerOptions": {"fields": ["name"]}}
        with self.assertRaises(PermissionDenied):
            validator.validate_fields(ast, DummyModel)

    def test_intermediate_no_read_permission(self):
        # Use MixedPermission:
        # DummyModel will have READ, but DummyRelatedModel will not.
        registry._models_config.clear()
        registry.register(
            DummyModel, ModelConfig(DummyModel, permissions=[MixedPermission])
        )
        registry.register(
            DummyRelatedModel,
            ModelConfig(DummyRelatedModel, permissions=[MixedPermission]),
        )
        # For the other models, we can register with DummyPermission.
        registry.register(
            DeepModelLevel1, ModelConfig(DeepModelLevel1, permissions=[DummyPermission])
        )
        registry.register(
            DeepModelLevel2, ModelConfig(DeepModelLevel2, permissions=[DummyPermission])
        )
        registry.register(
            DeepModelLevel3, ModelConfig(DeepModelLevel3, permissions=[DummyPermission])
        )
        registry.register(
            ComprehensiveModel,
            ModelConfig(ComprehensiveModel, permissions=[DummyPermission]),
        )

        dummy_graph = self.adapter.build_model_graph(DummyModel)
        validator = ASTValidator(
            model_graph=dummy_graph,
            get_model_name=self.adapter.get_model_name,
            registry=registry,
            request={},
            get_model_by_name=self.adapter.get_model_by_name,
        )
        # Even though DummyModel has READ permission, its related model (DummyRelatedModel)
        # does not. So "related__name" should raise a PermissionDenied.
        ast = {"serializerOptions": {"fields": ["name", "related__name"]}}
        with self.assertRaises(PermissionDenied):
            validator.validate_fields(ast, DummyModel)

    def test_nested_field_not_visible(self):
        # Use PartialPermission so that even with READ permission, some fields are not visible.
        self.register_models(PartialPermission)
        dummy_graph = self.adapter.build_model_graph(DummyModel)
        validator = ASTValidator(
            model_graph=dummy_graph,
            get_model_name=self.adapter.get_model_name,
            registry=registry,
            request={},
            get_model_by_name=self.adapter.get_model_by_name,
        )
        # "value" is not included in PartialPermission.visible_fields for DummyModel.
        ast = {"serializerOptions": {"fields": ["name", "value"]}}
        with self.assertRaises(PermissionDenied):
            validator.validate_fields(ast, DummyModel)


if __name__ == "__main__":
    unittest.main()
