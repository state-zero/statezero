import unittest

from django.test import TestCase

from statezero.adaptors.django.config import config, registry
from statezero.adaptors.django.orm import DjangoORMAdapter
from statezero.adaptors.django.ast_parser import ASTParser
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
            return {"char_field", "int_field"}
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


def _make_parser(model):
    """Helper to create an ASTParser instance for validation-only tests."""
    adapter = DjangoORMAdapter()
    return ASTParser(
        engine=adapter,
        serializer=config.serializer,
        model=model,
        config=config,
        registry=registry,
        base_queryset=model.objects.none(),
        serializer_options={},
        request={},
    )


# -------------------------------------------------------------------------
# Extended tests for ASTParser validation (formerly ASTValidator).
# -------------------------------------------------------------------------
class TestASTValidator(TestCase):
    def setUp(self):
        self.adapter = DjangoORMAdapter()

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
        self.register_models(DummyPermission)
        parser = _make_parser(DummyModel)
        ast = {"serializerOptions": {"fields": ["name", "related__name"]}}
        try:
            parser.validate_fields(ast, DummyModel)
        except PermissionDenied:
            self.fail(
                "PermissionDenied was raised unexpectedly for valid DummyModel fields."
            )

    def test_dummy_model_invalid_field(self):
        self.register_models(DummyPermission)
        parser = _make_parser(DummyModel)
        ast = {"serializerOptions": {"fields": ["name", "related__nonexistent"]}}
        with self.assertRaises(PermissionDenied):
            parser.validate_fields(ast, DummyModel)

    def test_deep_model_valid(self):
        self.register_models(DummyPermission)
        parser = _make_parser(DeepModelLevel1)
        ast = {
            "serializerOptions": {
                "fields": ["name", "level2__level3__name", "comprehensive_models__char_field"]
            }
        }
        try:
            parser.validate_fields(ast, DeepModelLevel1)
        except PermissionDenied:
            self.fail(
                "PermissionDenied was raised unexpectedly for valid deep model fields."
            )

    def test_deep_model_invalid_intermediate_field(self):
        self.register_models(DummyPermission)
        parser = _make_parser(DeepModelLevel1)
        ast = {"serializerOptions": {"fields": ["name", "level2__nonexistent"]}}
        with self.assertRaises(PermissionDenied):
            parser.validate_fields(ast, DeepModelLevel1)

        ast2 = {
            "serializerOptions": {
                "fields": ["name", "comprehensive_models__nonexistent"]
            }
        }
        with self.assertRaises(PermissionDenied):
            parser.validate_fields(ast2, DeepModelLevel1)

    def test_no_read_permission_root(self):
        self.register_models(DenyReadPermission)
        parser = _make_parser(DummyModel)
        ast = {"serializerOptions": {"fields": ["name"]}}
        with self.assertRaises(PermissionDenied):
            parser.validate_fields(ast, DummyModel)

    def test_intermediate_no_read_permission(self):
        registry._models_config.clear()
        registry.register(
            DummyModel, ModelConfig(DummyModel, permissions=[MixedPermission])
        )
        registry.register(
            DummyRelatedModel,
            ModelConfig(DummyRelatedModel, permissions=[MixedPermission]),
        )
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

        parser = _make_parser(DummyModel)
        ast = {"serializerOptions": {"fields": ["name", "related__name"]}}
        with self.assertRaises(PermissionDenied):
            parser.validate_fields(ast, DummyModel)

    def test_nested_field_not_visible(self):
        self.register_models(PartialPermission)
        parser = _make_parser(DummyModel)
        ast = {"serializerOptions": {"fields": ["name", "value"]}}
        with self.assertRaises(PermissionDenied):
            parser.validate_fields(ast, DummyModel)


if __name__ == "__main__":
    unittest.main()
