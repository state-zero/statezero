import json
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase

from ormbridge.adaptors.django.config import registry, config
from ormbridge.adaptors.django.permissions import AllowAllPermission
from ormbridge.core.constants import ALL_FIELDS
from ormbridge.core.types import ActionType
from tests.django_app.models import (
    ParentTestModel,
    ChildTestModel,
    GrandChildTestModel,
)
from tests.django_app.permissions import CustomIntersectionPermission


class NestedFieldPermissionsTest(APITestCase):
    """
    Test suite for nested field permissions in depth-based serialization.
    
    These tests verify that:
    1. Model-level fields restrictions from ModelConfig are enforced in nested serialization
    2. Permission-based field restrictions are enforced in nested serialization
    3. The combination of both restrictions works as expected
    4. Depth parameters correctly limit the depth of serialization
    """
    
    def setUp(self):
        # Create and log in a test user
        self.user = User.objects.create_user(username="testuser", password="password")
        self.client.login(username="testuser", password="password")

        # Create a hierarchy of test models
        self.parent = ParentTestModel.objects.create(
            name="Parent1", 
            description="Parent description"
        )
        
        self.child1 = ChildTestModel.objects.create(
            parent=self.parent,
            name="Child1",
            extra="Extra information"
        )
        
        self.child2 = ChildTestModel.objects.create(
            parent=self.parent,
            name="Child2",
            extra="More extra info"
        )
        
        self.grandchild1 = GrandChildTestModel.objects.create(
            child=self.child1,
            name="Grandchild1",
            detail="Grandchild detail 1"
        )
        
        self.grandchild2 = GrandChildTestModel.objects.create(
            child=self.child1,
            name="Grandchild2",
            detail="Grandchild detail 2"
        )
        
        self.grandchild3 = GrandChildTestModel.objects.create(
            child=self.child2,
            name="Grandchild3",
            detail="Grandchild detail 3"
        )

    def test_depth_0_serialization(self):
        """Test that depth=0 returns minimal representation for relationships."""
        url = reverse("ormbridge:model_view", args=["django_app.ParentTestModel"])
        
        query_payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.parent.id}
                    }
                },
                "serializerOptions": {
                    "depth": 0  # Minimal representation
                }
            }
        }
        
        response = self.client.post(url, data=query_payload, format="json")
        self.assertEqual(response.status_code, 200)
        
        # Extract the result data
        result_data = response.json().get("data", {})
        
        # Verify that the result contains only the allowed fields for ParentTestModel
        self.assertIn("name", result_data)
        self.assertIn("description", result_data)
        
        # Verify that children is not expanded (should be a list of minimal representations)
        children = result_data.get("children", [])
        self.assertTrue(isinstance(children, list))
        
        if children:
            child = children[0]
            # Child should have repr and pk but not actual fields
            self.assertIn("repr", child)
            self.assertIn("pk", child)
            self.assertNotIn("name", child)
            self.assertNotIn("extra", child)
            self.assertNotIn("grandchildren", child)

    def test_depth_1_serialization(self):
        """Test that depth=1 expands only the first level of relationships with proper field filtering."""
        url = reverse("ormbridge:model_view", args=["django_app.ParentTestModel"])
        
        query_payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.parent.id}
                    }
                },
                "serializerOptions": {
                    "depth": 1  # Expand first level only
                }
            }
        }
        
        response = self.client.post(url, data=query_payload, format="json")
        self.assertEqual(response.status_code, 200)
        
        # Extract the result data
        result_data = response.json().get("data", {})
        
        # Verify that the parent has only the allowed fields
        self.assertIn("name", result_data)
        self.assertIn("description", result_data)
        
        # Verify that children is expanded and has only the allowed fields
        children = result_data.get("children", [])
        self.assertTrue(isinstance(children, list))
        
        if children:
            child = children[0]
            # Child should have name (allowed) but not other fields (restricted)
            self.assertIn("name", child)
            self.assertIn("grandchildren", child)  # This should be present but not expanded
            
            # The extra field should not be present (not in ModelConfig.fields)
            self.assertNotIn("extra", child)
            
            # Grandchildren should not be expanded at depth 1
            grandchildren = child.get("grandchildren", [])
            if grandchildren:
                grandchild = grandchildren[0]
                self.assertIn("repr", grandchild)
                self.assertIn("pk", grandchild)
                self.assertNotIn("name", grandchild)
                self.assertNotIn("detail", grandchild)

    def test_depth_2_serialization(self):
        """Test that depth=2 expands two levels of relationships with proper field filtering."""
        url = reverse("ormbridge:model_view", args=["django_app.ParentTestModel"])
        
        query_payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.parent.id}
                    }
                },
                "serializerOptions": {
                    "depth": 2  # Expand two levels
                }
            }
        }
        
        response = self.client.post(url, data=query_payload, format="json")
        self.assertEqual(response.status_code, 200)
        
        # Extract the result data
        result_data = response.json().get("data", {})
        
        # Verify parent fields
        self.assertIn("name", result_data)
        self.assertIn("description", result_data)
        
        # Verify that children is expanded
        children = result_data.get("children", [])
        self.assertTrue(isinstance(children, list))
        
        if children:
            child = children[0]
            # Child should have only allowed fields
            self.assertIn("name", child)
            self.assertIn("grandchildren", child)
            self.assertNotIn("extra", child)
            
            # Grandchildren should be expanded at depth 2
            grandchildren = child.get("grandchildren", [])
            self.assertTrue(isinstance(grandchildren, list))
            
            if grandchildren:
                grandchild = grandchildren[0]
                # Grandchild should have only allowed fields
                self.assertIn("name", grandchild)
                self.assertNotIn("detail", grandchild)

    def test_explicit_field_selection(self):
        """Test that explicitly selected fields override depth-based expansion but still respect permissions."""
        url = reverse("ormbridge:model_view", args=["django_app.ParentTestModel"])
        
        query_payload = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.parent.id}
                    }
                },
                "serializerOptions": {
                    "depth": 2,  # Deep expansion
                    "fields": [
                        "name",  # Only request name for parent
                        "children__name",  # Only name for children
                        "children__grandchildren__name"  # Only name for grandchildren
                    ]
                }
            }
        }
        
        response = self.client.post(url, data=query_payload, format="json")
        self.assertEqual(response.status_code, 200)
        
        # Extract the result data
        result_data = response.json().get("data", {})
        
        # Verify only requested fields are present
        self.assertIn("name", result_data)
        self.assertNotIn("description", result_data)
        
        # Verify children are expanded but only with requested fields
        children = result_data.get("children", [])
        if children:
            child = children[0]
            self.assertIn("name", child)
            self.assertNotIn("extra", child)
            self.assertIn("grandchildren", child)
            
            # Verify grandchildren are expanded but only with requested fields
            grandchildren = child.get("grandchildren", [])
            if grandchildren:
                grandchild = grandchildren[0]
                self.assertIn("name", grandchild)
                self.assertNotIn("detail", grandchild)

    def test_override_fields_in_modelconfig(self):
        """
        Test that when ModelConfig fields is overridden, the changes are reflected in serialization.
        This test temporarily modifies the ModelConfig.fields for ChildTestModel to include 'extra'.
        """
        
        # Get original config
        original_config = registry.get_config(ChildTestModel)
        original_fields = original_config.fields
        
        # Temporarily modify fields to include 'extra'
        original_config.fields = {"name", "extra", "grandchildren"}
        
        try:
            url = reverse("ormbridge:model_view", args=["django_app.ParentTestModel"])
            
            query_payload = {
                "ast": {
                    "query": {
                        "type": "get",
                        "filter": {
                            "type": "filter",
                            "conditions": {"id": self.parent.id}
                        }
                    },
                    "serializerOptions": {
                        "depth": 1  # Expand first level
                    }
                }
            }
            
            response = self.client.post(url, data=query_payload, format="json")
            self.assertEqual(response.status_code, 200)
            
            # Extract the result data
            result_data = response.json().get("data", {})
            children = result_data.get("children", [])
            
            if children:
                child = children[0]
                # Child should now have 'extra' field
                self.assertIn("name", child)
                self.assertIn("extra", child)  # This should be present now
                self.assertIn("grandchildren", child)
        
        finally:
            # Restore original fields
            original_config.fields = original_fields

    def test_permission_field_restrictions(self):
        """
        Test that permission-based field restrictions are applied in nested serialization.
        This test temporarily adds CustomIntersectionPermission which has different field
        restrictions than the ModelConfig.
        """
        
        # Get original configs
        parent_config = registry.get_config(ParentTestModel)
        child_config = registry.get_config(ChildTestModel)
        grandchild_config = registry.get_config(GrandChildTestModel)
        
        # Save original permissions
        original_parent_permissions = parent_config._permissions
        original_child_permissions = child_config._permissions
        original_grandchild_permissions = grandchild_config._permissions
        
        # Temporarily add CustomIntersectionPermission
        parent_config._permissions = [CustomIntersectionPermission]
        child_config._permissions = [CustomIntersectionPermission]
        grandchild_config._permissions = [CustomIntersectionPermission]
        
        try:
            url = reverse("ormbridge:model_view", args=["django_app.ParentTestModel"])
            
            query_payload = {
                "ast": {
                    "query": {
                        "type": "get",
                        "filter": {
                            "type": "filter",
                            "conditions": {"id": self.parent.id}
                        }
                    },
                    "serializerOptions": {
                        "depth": 2  # Expand two levels
                    }
                }
            }
            
            response = self.client.post(url, data=query_payload, format="json")
            self.assertEqual(response.status_code, 200)
            
            # Extract the result data
            result_data = response.json().get("data", {})
            
            # Verify parent fields - should have name, description, children
            # (allowed by both ModelConfig and CustomIntersectionPermission)
            self.assertIn("name", result_data)
            self.assertIn("description", result_data)
            
            # Verify children fields
            children = result_data.get("children", [])
            if children:
                child = children[0]
                # Child should have name (allowed by both)
                self.assertIn("name", child)
                # Extra is allowed by CustomIntersectionPermission but not by ModelConfig
                # The intersection should be applied, so it should NOT be present
                self.assertNotIn("extra", child)
                self.assertIn("grandchildren", child)
                
                # Verify grandchildren fields
                grandchildren = child.get("grandchildren", [])
                if grandchildren:
                    grandchild = grandchildren[0]
                    # Name is allowed by both 
                    self.assertIn("name", grandchild)
                    # Detail is allowed by CustomIntersectionPermission but not by ModelConfig
                    # The intersection should be applied, so it should NOT be present
                    self.assertNotIn("detail", grandchild)
        
        finally:
            # Restore original permissions
            parent_config._permissions = original_parent_permissions
            child_config._permissions = original_child_permissions
            grandchild_config._permissions = original_grandchild_permissions

    def test_combined_restrictions(self):
        """
        Test the combination of ModelConfig.fields restrictions and permission-based
        field restrictions when they allow different sets of fields.
        """
        
        # Get original configs
        parent_config = registry.get_config(ParentTestModel)
        child_config = registry.get_config(ChildTestModel)
        grandchild_config = registry.get_config(GrandChildTestModel)
        
        # Save original values
        original_parent_permissions = parent_config._permissions
        original_child_permissions = child_config._permissions
        original_grandchild_permissions = grandchild_config._permissions
        original_child_fields = child_config.fields
        
        # Modify the fields for ChildTestModel to include 'extra'
        child_config.fields = {"name", "extra", "grandchildren"}
        
        # Add CustomIntersectionPermission which also allows 'extra'
        parent_config._permissions = [CustomIntersectionPermission]
        child_config._permissions = [CustomIntersectionPermission]
        grandchild_config._permissions = [CustomIntersectionPermission]
        
        try:
            url = reverse("ormbridge:model_view", args=["django_app.ParentTestModel"])
            
            query_payload = {
                "ast": {
                    "query": {
                        "type": "get",
                        "filter": {
                            "type": "filter",
                            "conditions": {"id": self.parent.id}
                        }
                    },
                    "serializerOptions": {
                        "depth": 2  # Expand two levels
                    }
                }
            }
            
            response = self.client.post(url, data=query_payload, format="json")
            self.assertEqual(response.status_code, 200)
            
            # Extract the result data
            result_data = response.json().get("data", {})
            
            # Verify children fields
            children = result_data.get("children", [])
            if children:
                child = children[0]
                # Child should have name (allowed by both)
                self.assertIn("name", child)
                # Extra is now allowed by both, so it should be present
                self.assertIn("extra", child)
                self.assertIn("grandchildren", child)
                
                # Verify grandchildren fields
                grandchildren = child.get("grandchildren", [])
                if grandchildren:
                    grandchild = grandchildren[0]
                    # Name is allowed by both 
                    self.assertIn("name", grandchild)
                    # Detail is allowed by CustomIntersectionPermission but not by ModelConfig
                    # The intersection should be applied, so it should NOT be present
                    self.assertNotIn("detail", grandchild)
        
        finally:
            # Restore original values
            parent_config._permissions = original_parent_permissions
            child_config._permissions = original_child_permissions
            grandchild_config._permissions = original_grandchild_permissions
            child_config.fields = original_child_fields

    def test_cache_consistency(self):
        """
        Test that cache doesn't leak data by running a restricted query
        followed by a more permissive query.
        """
        
        # Clear any existing cache
        if hasattr(config, 'cache_backend') and config.cache_backend:
            config.cache_backend.cache.clear()
        
        # Get original configs
        child_config = registry.get_config(ChildTestModel)
        original_child_fields = child_config.fields
        
        url = reverse("ormbridge:model_view", args=["django_app.ParentTestModel"])
        
        # First, run a query with restricted fields (default configuration)
        restricted_query = {
            "ast": {
                "query": {
                    "type": "get",
                    "filter": {
                        "type": "filter",
                        "conditions": {"id": self.parent.id}
                    }
                },
                "serializerOptions": {
                    "depth": 1
                }
            }
        }
        
        restricted_response = self.client.post(url, data=restricted_query, format="json")
        self.assertEqual(restricted_response.status_code, 200)
        restricted_data = restricted_response.json().get("data", {})
        restricted_children = restricted_data.get("children", [])
        
        if restricted_children:
            restricted_child = restricted_children[0]
            # Verify extra is not present in restricted query
            self.assertNotIn("extra", restricted_child)
        
        # Now modify the configuration to allow extra fields
        child_config.fields = {"name", "extra", "grandchildren"}
        
        try:
            # Run a second query that should include extra fields
            permissive_query = {
                "ast": {
                    "query": {
                        "type": "get",
                        "filter": {
                            "type": "filter",
                            "conditions": {"id": self.parent.id}
                        }
                    },
                    "serializerOptions": {
                        "depth": 1
                    }
                }
            }
            
            permissive_response = self.client.post(url, data=permissive_query, format="json")
            self.assertEqual(permissive_response.status_code, 200)
            permissive_data = permissive_response.json().get("data", {})
            permissive_children = permissive_data.get("children", [])
            
            if permissive_children:
                permissive_child = permissive_children[0]
                # Verify extra is now present in permissive query
                self.assertIn("extra", permissive_child)
            
        finally:
            # Restore original configuration
            child_config.fields = original_child_fields