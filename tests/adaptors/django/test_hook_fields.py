"""
Test that pre-hooks can add fields that aren't in the permission-allowed fields.
This tests the new deserialize behavior where:
1. User input is filtered to only allowed fields
2. Pre-hooks can add any DB field (not in allowed fields)
3. Serializer validates with all DB fields
"""
from django.test import TestCase
from tests.django_app.models import Product, ProductCategory
from statezero.adaptors.django.config import registry
from statezero.adaptors.django.serializers import DRFDynamicSerializer


class TestPreHooksCanAddHiddenFields(TestCase):
    """Test that pre-hooks can add DB fields not in the allowed fields_map"""

    def setUp(self):
        self.serializer = DRFDynamicSerializer()
        self.category = ProductCategory.objects.create(name="Test Category")

    def test_hook_can_add_field_not_in_allowed_fields(self):
        """Test that a pre-hook can add 'created_by' even when it's not in allowed fields"""

        # Define a hook that adds 'created_by' field
        def add_created_by_hook(data, request=None):
            data = data.copy()
            data['created_by'] = 'hook_user'
            return data

        # Get model config and temporarily add the hook
        model_config = registry.get_config(Product)
        original_hooks = model_config.pre_hooks
        model_config.pre_hooks = [add_created_by_hook]

        try:
            # Simulate a fields_map that only allows 'name', 'description', 'price', 'category'
            # but NOT 'created_by'
            allowed_fields = {'name', 'description', 'price', 'category'}
            fields_map = {'django_app.product': allowed_fields}  # Note: lowercase model name!

            # User input that includes allowed fields
            # Note: category needs to be the ID
            user_data = {
                'name': 'Test Product',
                'description': 'A test product',
                'price': '99.99',
                'category': self.category.id,
            }

            # Call deserialize
            validated_data = self.serializer.deserialize(
                model=Product,
                data=user_data,
                fields_map=fields_map,
                partial=False,
                request=None
            )

            # Verify the hook was able to add 'created_by'
            self.assertIn('created_by', validated_data)
            self.assertEqual(validated_data['created_by'], 'hook_user')

            # Verify the other fields are still present
            self.assertEqual(validated_data['name'], 'Test Product')
            self.assertEqual(validated_data['description'], 'A test product')

        finally:
            # Restore original hooks
            model_config.pre_hooks = original_hooks

    def test_user_cannot_inject_restricted_field(self):
        """Test that user input is filtered and cannot inject fields not in allowed_fields"""

        # Define a hook that adds 'created_by' field
        def add_created_by_hook(data, request=None):
            data = data.copy()
            data['created_by'] = 'hook_user'
            return data

        # Get model config and temporarily add the hook
        model_config = registry.get_config(Product)
        original_hooks = model_config.pre_hooks
        model_config.pre_hooks = [add_created_by_hook]

        try:
            # Simulate a fields_map that only allows 'name', 'description', 'price', 'category'
            # but NOT 'created_by'
            allowed_fields = {'name', 'description', 'price', 'category'}
            fields_map = {'django_app.product': allowed_fields}  # Note: lowercase model name!

            # User input that tries to maliciously set 'created_by'
            user_data = {
                'name': 'Test Product',
                'description': 'A test product',
                'price': '99.99',
                'category': self.category.id,
                'created_by': 'hacker',  # This should be filtered out!
            }

            # Call deserialize
            validated_data = self.serializer.deserialize(
                model=Product,
                data=user_data,
                fields_map=fields_map,
                partial=False,
                request=None
            )

            # Verify the user's malicious 'created_by' was filtered out
            # and the hook's value was used instead
            self.assertIn('created_by', validated_data)
            self.assertEqual(validated_data['created_by'], 'hook_user')
            self.assertNotEqual(validated_data['created_by'], 'hacker')

        finally:
            # Restore original hooks
            model_config.pre_hooks = original_hooks
