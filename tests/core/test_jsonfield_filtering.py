"""
Tests for JSONField nested path filtering support.

These tests validate TICKET-003: Support JSONField Filtering in Backend Validation.

The issue: The backend AST validator currently rejects valid Django ORM filter
queries on JSONField nested paths (e.g., `metadata__user__name`), even though
Django's ORM natively supports this.

Test cases cover:
1. Valid JSONField filtering should be allowed
2. JSONField with lookup operators should work
3. Deep nested JSON paths should work
4. Permission checks should still be enforced on the base JSONField
5. Non-existent base fields should still be rejected
6. Mixed relationship and JSON paths should work
"""

from django.test import TestCase

from statezero.adaptors.django.config import config, registry
from statezero.adaptors.django.orm import DjangoORMAdapter
from statezero.adaptors.django.ast_parser import ASTParser
from statezero.core.config import ModelConfig
from statezero.core.exceptions import PermissionDenied, ValidationError
from statezero.core.interfaces import AbstractPermission
from statezero.core.types import ActionType
from tests.django_app.models import ComprehensiveModel, DeepModelLevel1


class JSONFieldPermission(AbstractPermission):
    """Permission class that allows access to json_field on ComprehensiveModel."""

    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        return {ActionType.READ}

    def allowed_object_actions(self, request, obj, model):
        return {ActionType.READ}

    def visible_fields(self, request, model):
        if model == ComprehensiveModel:
            return {"id", "char_field", "json_field", "related"}
        elif model == DeepModelLevel1:
            return {"id", "name", "level2"}
        return set()

    def editable_fields(self, request, model):
        return self.visible_fields(request, model)

    def create_fields(self, request, model):
        return self.editable_fields(request, model)


class JSONFieldDeniedPermission(AbstractPermission):
    """Permission class that denies access to json_field."""

    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model):
        return {ActionType.READ}

    def allowed_object_actions(self, request, obj, model):
        return {ActionType.READ}

    def visible_fields(self, request, model):
        if model == ComprehensiveModel:
            # Explicitly exclude json_field
            return {"id", "char_field", "related"}
        return set()

    def editable_fields(self, request, model):
        return self.visible_fields(request, model)

    def create_fields(self, request, model):
        return self.editable_fields(request, model)


def _make_parser(model, permission_class):
    """Helper to set up an ASTParser with given permissions for validation tests."""
    adapter = DjangoORMAdapter()
    model_graph = adapter.build_model_graph(model)
    return ASTParser(
        engine=adapter,
        serializer=config.serializer,
        model=model,
        config=config,
        registry=registry,
        base_queryset=model.objects.none(),
        serializer_options={},
        request={},
        model_graph=model_graph,
    )


class TestJSONFieldFiltering(TestCase):
    """Tests for JSONField nested path filtering in AST parser validation."""

    def setUp(self):
        self.adapter = DjangoORMAdapter()

    def _setup_parser(self, permission_class):
        """Helper to set up the parser with given permissions."""
        registry._models_config.clear()
        registry.register(
            ComprehensiveModel,
            ModelConfig(ComprehensiveModel, permissions=[permission_class])
        )
        registry.register(
            DeepModelLevel1,
            ModelConfig(DeepModelLevel1, permissions=[permission_class])
        )
        return _make_parser(ComprehensiveModel, permission_class)

    # =========================================================================
    # Test 1: Valid JSONField filtering should be allowed
    # =========================================================================
    def test_jsonfield_nested_path_filtering(self):
        """
        Test that filtering on JSONField nested paths works.

        Django supports: MyModel.objects.filter(json_field__user__name='John')
        StateZero should allow this in validation.
        """
        parser = self._setup_parser(JSONFieldPermission)
        parser.validate_filterable_field(ComprehensiveModel, "json_field__user__name")

    # =========================================================================
    # Test 2: JSONField with lookup operators should work
    # =========================================================================
    def test_jsonfield_with_lookup_operators(self):
        """
        Test that JSONField filtering with lookup operators works.

        Django supports: MyModel.objects.filter(json_field__count__gte=5)
        """
        parser = self._setup_parser(JSONFieldPermission)
        parser.validate_filterable_field(ComprehensiveModel, "json_field__count__gte")

    def test_jsonfield_with_contains_operator(self):
        """
        Test that JSONField filtering with contains operator works.

        Django supports: MyModel.objects.filter(json_field__name__icontains='test')
        """
        parser = self._setup_parser(JSONFieldPermission)
        parser.validate_filterable_field(ComprehensiveModel, "json_field__name__icontains")

    # =========================================================================
    # Test 3: Deep nested JSON paths should work
    # =========================================================================
    def test_jsonfield_deep_nested_path(self):
        """
        Test that deeply nested JSON paths work.

        Django supports: MyModel.objects.filter(json_field__level1__level2__level3='value')
        """
        parser = self._setup_parser(JSONFieldPermission)
        parser.validate_filterable_field(
            ComprehensiveModel,
            "json_field__level1__level2__level3"
        )

    # =========================================================================
    # Test 4: Permission checks should still be enforced
    # =========================================================================
    def test_jsonfield_permission_denied_when_field_not_visible(self):
        """
        Test that permission checks are still enforced on the base JSONField.

        If a user doesn't have access to the json_field itself, they shouldn't
        be able to filter on any nested paths within it.
        """
        parser = self._setup_parser(JSONFieldDeniedPermission)
        with self.assertRaises(PermissionDenied):
            parser.validate_filterable_field(ComprehensiveModel, "json_field__user__name")

    # =========================================================================
    # Test 5: Non-existent base fields should still be rejected
    # =========================================================================
    def test_nonexistent_base_field_rejected(self):
        """
        Test that non-existent base fields are still rejected.
        """
        parser = self._setup_parser(JSONFieldPermission)
        with self.assertRaises(ValidationError):
            parser.validate_filterable_field(ComprehensiveModel, "nonexistent_field__key")

    # =========================================================================
    # Test 6: Regular (non-JSON) field validation still works
    # =========================================================================
    def test_regular_field_validation_unchanged(self):
        """
        Test that regular field validation still works correctly.
        """
        parser = self._setup_parser(JSONFieldPermission)
        parser.validate_filterable_field(ComprehensiveModel, "char_field")
        parser.validate_filterable_field(ComprehensiveModel, "char_field__icontains")

    def test_regular_nested_field_still_validated(self):
        """
        Test that nested paths through relations are still validated.
        """
        parser = self._setup_parser(JSONFieldPermission)
        with self.assertRaises((ValidationError, PermissionDenied)):
            parser.validate_filterable_field(ComprehensiveModel, "related__nonexistent")


class TestJSONFieldInFilterConditions(TestCase):
    """Tests for JSONField filtering in full AST filter condition validation."""

    def setUp(self):
        self.adapter = DjangoORMAdapter()

    def _setup_parser(self, permission_class):
        """Helper to set up the parser with given permissions."""
        registry._models_config.clear()
        registry.register(
            ComprehensiveModel,
            ModelConfig(ComprehensiveModel, permissions=[permission_class])
        )
        registry.register(
            DeepModelLevel1,
            ModelConfig(DeepModelLevel1, permissions=[permission_class])
        )
        return _make_parser(ComprehensiveModel, permission_class)

    def test_ast_filter_with_jsonfield_path(self):
        """
        Test that AST filter validation works with JSONField paths.
        """
        parser = self._setup_parser(JSONFieldPermission)
        ast_node = {
            "type": "filter",
            "conditions": {
                "json_field__user__name": "John"
            }
        }
        parser.validate_filter_conditions(ast_node, ComprehensiveModel)

    def test_ast_filter_with_multiple_jsonfield_paths(self):
        """
        Test that AST filter validation works with multiple JSONField paths.
        """
        parser = self._setup_parser(JSONFieldPermission)
        ast_node = {
            "type": "filter",
            "conditions": {
                "json_field__user__name": "John",
                "json_field__user__age__gte": 18,
                "char_field__icontains": "test"
            }
        }
        parser.validate_filter_conditions(ast_node, ComprehensiveModel)

    def test_full_ast_validation_with_jsonfield(self):
        """
        Test complete AST validation with JSONField in both fields and filters.
        """
        parser = self._setup_parser(JSONFieldPermission)
        ast = {
            "serializerOptions": {
                "fields": ["id", "char_field", "json_field"]
            },
            "filter": {
                "type": "filter",
                "conditions": {
                    "json_field__settings__enabled": True
                }
            }
        }
        parser.validate_ast(ast, ComprehensiveModel)
