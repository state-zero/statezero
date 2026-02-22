"""Test the @action decorator attaches attributes correctly."""
import unittest
from statezero.core.actions import ActionRegistry
from statezero.core.interfaces import AbstractActionPermission


class MockPermission(AbstractActionPermission):
    def has_permission(self, request, action_name: str) -> bool:
        return True

    def has_action_permission(self, request, action_name: str, validated_data: dict) -> bool:
        return True


class MockSerializer:
    pass


class MockResponseSerializer:
    pass


class TestActionDecoratorAttributes(unittest.TestCase):
    def test_decorator_attaches_all_attributes(self):
        """Test that the decorator attaches all statezero attributes to the function."""
        registry = ActionRegistry()
        permission = MockPermission()

        @registry.register(
            serializer=MockSerializer,
            response_serializer=MockResponseSerializer,
            permissions=[permission],
            name="test_action",
        )
        def my_action():
            pass

        # Check all attributes are attached
        self.assertTrue(my_action._statezero_action)
        self.assertEqual(my_action._statezero_action_name, "test_action")
        self.assertIs(my_action._statezero_serializer, MockSerializer)
        self.assertIs(my_action._statezero_response_serializer, MockResponseSerializer)
        self.assertEqual(len(my_action._statezero_permissions), 1)

    def test_decorator_handles_single_permission(self):
        """Test that a single permission is normalized to a list."""
        registry = ActionRegistry()
        permission = MockPermission()

        @registry.register(permissions=permission)
        def my_action():
            pass

        self.assertEqual(len(my_action._statezero_permissions), 1)

    def test_decorator_handles_no_permissions(self):
        """Test that no permissions results in an empty list."""
        registry = ActionRegistry()

        @registry.register()
        def my_action():
            pass

        self.assertEqual(my_action._statezero_permissions, [])

    def test_decorator_uses_function_name_by_default(self):
        """Test that the function name is used when no name is provided."""
        registry = ActionRegistry()

        @registry.register()
        def my_custom_action():
            pass

        self.assertEqual(my_custom_action._statezero_action_name, "my_custom_action")


if __name__ == "__main__":
    unittest.main()
