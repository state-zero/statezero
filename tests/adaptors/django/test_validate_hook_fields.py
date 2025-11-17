"""
Test that validate() doesn't filter out hook-added fields.

The bug: validate() filters data to only allowed create_fields BEFORE passing
to serializer, but the serializer's deserialize() method needs to receive the
unfiltered data so hooks can add ANY field.
"""
from django.test import TestCase, RequestFactory
from tests.django_app.models import Product, ProductCategory
from statezero.adaptors.django.config import registry
from statezero.adaptors.django.orm import DjangoORMAdapter
from statezero.adaptors.django.serializers import DRFDynamicSerializer
from statezero.core.interfaces import AbstractPermission
from statezero.core.types import ActionType
from typing import Set


class RestrictedCreatePermission(AbstractPermission):
    """Permission that only allows setting 'name' on create"""

    def filter_queryset(self, request, queryset):
        return queryset

    def allowed_actions(self, request, model) -> Set[ActionType]:
        return {ActionType.CREATE, ActionType.READ, ActionType.UPDATE, ActionType.DELETE}

    def allowed_object_actions(self, request, model, instance):
        return {ActionType.READ, ActionType.UPDATE, ActionType.DELETE}

    def create_fields(self, request, model):
        if model.__name__ == "Product":
            return {"name"}  # Very restricted - only name allowed!
        return "__all__"

    def editable_fields(self, request, model):
        return "__all__"

    def visible_fields(self, request, model):
        return "__all__"


def add_required_fields_hook(data, request=None):
    """
    Hook that adds required fields that are NOT in create_fields.
    User can only set 'name', but Product requires: name, description, price, category.
    This hook adds the missing required fields.
    """
    data = data.copy()
    # Get or create a default category
    category = ProductCategory.objects.first()
    if not category:
        category = ProductCategory.objects.create(name="Default Category")
    data['description'] = 'Auto-generated description from hook'
    data['price'] = '99.99'
    data['category'] = category.id
    return data


class TestValidateWithRestrictedPermissions(TestCase):
    """Test that validate() allows hooks to add fields not in create_fields"""

    def setUp(self):
        self.factory = RequestFactory()
        self.category = ProductCategory.objects.create(name="Test Category")
        self.orm_adaptor = DjangoORMAdapter()
        self.serializer = DRFDynamicSerializer()

        # Get model config and save originals
        self.model_config = registry.get_config(Product)
        self.original_hooks = self.model_config.pre_hooks
        self.original_permissions = self.model_config._permissions

    def tearDown(self):
        # Restore originals
        self.model_config.pre_hooks = self.original_hooks
        self.model_config._permissions = self.original_permissions

    def test_hook_adds_fields_not_in_create_fields(self):
        """
        Test that hooks can add fields not in create_fields.

        This is the bug: validate() was filtering data to only 'name'
        before passing to serializer, preventing hooks from adding 'price'
        and 'category'.
        """
        # Setup: Only 'name' is allowed in create_fields
        self.model_config._permissions = [RestrictedCreatePermission]
        # Hook will add 'description', 'price', and 'category' which are required but not in create_fields
        self.model_config.pre_hooks = [add_required_fields_hook]

        # Simulate a request
        request = self.factory.post('/test/')

        # User provides only 'name' (which is all they're allowed to provide)
        user_data = {
            "name": "Test Product"
            # Notice: no description, price, or category - hook will add these
        }

        # Call deserialize() directly to test the full flow
        # In the buggy version, validate() was filtering data to only {'name'} before
        # passing to serializer.deserialize(), which prevented hooks from adding fields
        try:
            # Get allowed fields for create
            model_name = 'django_app.product'
            allowed_fields = {'name'}  # Restricted - only name allowed
            fields_map = {model_name: allowed_fields}

            # Call deserialize - this should work now that validate() doesn't pre-filter
            validated_data = self.serializer.deserialize(
                model=Product,
                data=user_data,
                fields_map=fields_map,
                partial=False,
                request=request
            )

            # If we get here without errors, the fix is working!
            self.assertIsNotNone(validated_data)
            self.assertIn('name', validated_data)
            self.assertEqual(validated_data['name'], 'Test Product')

            # These are the critical assertions - hook should have added these
            self.assertIn('description', validated_data, "Hook should have added 'description' field")
            self.assertEqual(validated_data['description'], 'Auto-generated description from hook')
            self.assertIn('price', validated_data, "Hook should have added 'price' field")
            self.assertEqual(str(validated_data['price']), '99.99')
            self.assertIn('category', validated_data, "Hook should have added 'category' field")

        except Exception as e:
            # If we get an error, the bug exists
            self.fail(f"Hook-added fields were filtered out! Error: {e}")
