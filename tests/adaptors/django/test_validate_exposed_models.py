from django.test import TestCase
from django.db import models
import uuid

from statezero.core.config import ModelConfig, Registry
from statezero.adaptors.django.config import config, registry
from statezero.adaptors.django.permissions import AllowAllPermission


# Test models with unique names to avoid conflicts
class TestUnregisteredModel(models.Model):
    """Test model that won't be registered with StateZero"""
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "django_app"
        managed = False


class TestModelWithUnregisteredRelation(models.Model):
    """Test model with a relation to an unregistered model"""
    name = models.CharField(max_length=100)
    unregistered_relation = models.ForeignKey(
        TestUnregisteredModel, 
        on_delete=models.CASCADE,
        related_name="model_relations"
    )

    class Meta:
        app_label = "django_app"
        managed = False


class TestRegisteredModelA(models.Model):
    """Test model that will be registered"""
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "django_app"
        managed = False


class TestRegisteredModelB(models.Model):
    """Test model with relation to another registered model"""
    name = models.CharField(max_length=100)
    related = models.ForeignKey(
        TestRegisteredModelA,
        on_delete=models.CASCADE,
        related_name="model_b_relations"
    )

    class Meta:
        app_label = "django_app"
        managed = False


class TestModelWithM2M(models.Model):
    """Test model with many-to-many relationship"""
    name = models.CharField(max_length=100)
    many_to_many = models.ManyToManyField(
        TestRegisteredModelA,
        related_name="m2m_relations"
    )

    class Meta:
        app_label = "django_app"
        managed = False


# Define custom permission classes for testing
class RestrictedFieldsPermission(AllowAllPermission):
    """Permission class that restricts field access"""
    
    def visible_fields(self, request, model):
        # Only expose the name field, not any relations
        return {"name"}
    
    def editable_fields(self, request, model):
        return {"name"}
    
    def create_fields(self, request, model):
        return {"name"}


class ExposesRelationPermission(AllowAllPermission):
    """Permission class that explicitly exposes relation fields"""
    
    def visible_fields(self, request, model):
        return {"name", "unregistered_relation"}
        
    def editable_fields(self, request, model):
        return {"name", "unregistered_relation"}
        
    def create_fields(self, request, model):
        return {"name", "unregistered_relation"}


class SimpleValidateExposedModelsTests(TestCase):
    """Tests for the validate_exposed_models functionality using basic approach"""

    def setUp(self):
        self._original_models_config = dict(registry._models_config)

    def tearDown(self):
        registry._models_config.clear()
        registry._models_config.update(self._original_models_config)

    def test_valid_related_models_pass(self):
        """Test that models with relations to other registered models pass validation"""
        # Create a fresh registry for this test
        registry._models_config.clear()
        
        # Register both related models
        registry.register(
            TestRegisteredModelA,
            ModelConfig(
                model=TestRegisteredModelA,
                permissions=[AllowAllPermission],
            )
        )
        
        registry.register(
            TestRegisteredModelB,
            ModelConfig(
                model=TestRegisteredModelB,
                permissions=[AllowAllPermission],
            )
        )
        
        # Validation should pass
        result = config.validate_exposed_models(registry)
        self.assertTrue(result)
        
    def test_unregistered_relation_fails(self):
        """Test that exposing an unregistered model relation fails validation"""
        # Create a fresh registry for this test
        registry._models_config.clear()
        
        # Register only the model with the relation to an unregistered model
        registry.register(
            TestModelWithUnregisteredRelation,
            ModelConfig(
                model=TestModelWithUnregisteredRelation,
                permissions=[AllowAllPermission],  # This exposes all fields
            )
        )
        
        # Validation should fail
        with self.assertRaises(ValueError) as context:
            config.validate_exposed_models(registry)
        
        # Check the error message
        error_msg = str(context.exception)
        self.assertIn("unregistered model", error_msg)
        self.assertIn("unregistered_relation", error_msg)
        self.assertIn("testunregisteredmodel", error_msg.lower())
        
    def test_restricted_fields_pass(self):
        """Test that restricting fields properly hides unregistered relations"""
        # Create a fresh registry for this test
        registry._models_config.clear()
        
        # Register model with relation but restrict field access using fields parameter
        registry.register(
            TestModelWithUnregisteredRelation,
            ModelConfig(
                model=TestModelWithUnregisteredRelation,
                permissions=[RestrictedFieldsPermission],  # This is now ignored for field validation
                fields={"name"},  # Only expose name field, not the relation
            )
        )
        
        # Validation should pass since the relation field is not exposed
        result = config.validate_exposed_models(registry)
        self.assertTrue(result)

    def test_m2m_relation_validation(self):
        """Test validation with many-to-many relationships"""
        # Create a fresh registry for this test
        registry._models_config.clear()
        
        # Register only the M2M model without its related model
        registry.register(
            TestModelWithM2M,
            ModelConfig(
                model=TestModelWithM2M,
                permissions=[AllowAllPermission],
            )
        )
        
        # Validation should fail because related model is not registered
        with self.assertRaises(ValueError) as context:
            config.validate_exposed_models(registry)
            
        error_msg = str(context.exception)
        self.assertIn("unregistered model", error_msg)
        self.assertIn("many_to_many", error_msg)
        self.assertIn("testregisteredmodela", error_msg.lower())
        
        # Now register both models in a new registry
        registry._models_config.clear()
        
        registry.register(
            TestRegisteredModelA,  # Register the related model
            ModelConfig(
                model=TestRegisteredModelA,
                permissions=[AllowAllPermission],
            )
        )
        
        registry.register(
            TestModelWithM2M,
            ModelConfig(
                model=TestModelWithM2M,
                permissions=[AllowAllPermission],
            )
        )
        
        # Validation should now pass
        result = config.validate_exposed_models(registry)
        self.assertTrue(result)
        
    def test_multiple_permission_classes(self):
        """Test validation with multiple permission classes"""
        # Create a fresh registry for this test
        registry._models_config.clear()
        
        # Register model with multiple permission classes
        registry.register(
            TestModelWithUnregisteredRelation,
            ModelConfig(
                model=TestModelWithUnregisteredRelation,
                # One permission restricts fields, one exposes relation
                permissions=[RestrictedFieldsPermission, ExposesRelationPermission],
            )
        )
        
        # Validation should fail because one permission class exposes the unregistered relation
        with self.assertRaises(ValueError) as context:
            config.validate_exposed_models(registry)
            
        error_msg = str(context.exception)
        self.assertIn("unregistered model", error_msg)
        self.assertIn("unregistered_relation", error_msg)
        self.assertIn("testunregisteredmodel", error_msg.lower())

    def test_only_exposed_relationships_are_validated(self):
        """Test that unexposed relationships (like reverse relations) are not validated"""
        # Create a fresh registry for this test
        registry._models_config.clear()
        
        # Create a permission that only exposes direct fields, not reverse relations
        class OnlyDirectFieldsPermission(AllowAllPermission):
            def visible_fields(self, request, model):
                if model == TestRegisteredModelA:
                    # Only expose name, not m2m_relations or model_b_relations reverse relations
                    return {"name"}
                return super().visible_fields(request, model)
                
            def editable_fields(self, request, model):
                if model == TestRegisteredModelA:
                    return {"name"}
                return super().editable_fields(request, model)
                
            def create_fields(self, request, model):
                if model == TestRegisteredModelA:
                    return {"name"}
                return super().create_fields(request, model)
        
        # Register only ModelA with restricted permissions
        registry.register(
            TestRegisteredModelA,
            ModelConfig(
                model=TestRegisteredModelA,
                permissions=[OnlyDirectFieldsPermission],  # Only exposes name field
            )
        )
        
        # Validation should pass even though ModelA has reverse relations to unregistered models
        # because those reverse relations are not exposed by permissions
        result = config.validate_exposed_models(registry)
        self.assertTrue(result)

    def test_deep_unregistered_relation_validation(self):
        """Test validation with deep nested relationships where an intermediate model is unregistered.

        Uses real test models: DeepModelLevel1 -> DeepModelLevel2 -> DeepModelLevel3
        """
        from tests.django_app.models import DeepModelLevel1, DeepModelLevel2, DeepModelLevel3

        # Register only Level1 with level2 exposed — Level2 is unregistered
        registry._models_config.clear()
        registry.register(
            DeepModelLevel1,
            ModelConfig(
                model=DeepModelLevel1,
                permissions=[AllowAllPermission],
                fields={"name", "level2"},
            )
        )

        with self.assertRaises(ValueError) as context:
            config.validate_exposed_models(registry)

        error_msg = str(context.exception)
        self.assertIn("unregistered model", error_msg)
        self.assertIn("level2", error_msg)

        # Register Level2 but not Level3 — Level3 is still unregistered
        registry.register(
            DeepModelLevel2,
            ModelConfig(
                model=DeepModelLevel2,
                permissions=[AllowAllPermission],
                fields={"name", "level3"},
            )
        )

        with self.assertRaises(ValueError) as context:
            config.validate_exposed_models(registry)

        error_msg = str(context.exception)
        self.assertIn("unregistered model", error_msg)
        self.assertIn("level3", error_msg)

        # Register all three — validation should pass
        registry.register(
            DeepModelLevel3,
            ModelConfig(
                model=DeepModelLevel3,
                permissions=[AllowAllPermission],
                fields={"name"},
            )
        )

        result = config.validate_exposed_models(registry)
        self.assertTrue(result)

    def test_restricted_fields_skip_unregistered_relation(self):
        """Excluding a relation field from 'fields' means validation ignores that path."""
        from tests.django_app.models import DeepModelLevel1

        registry._models_config.clear()
        # Only expose 'name', not 'level2' — so Level2 being unregistered is fine
        registry.register(
            DeepModelLevel1,
            ModelConfig(
                model=DeepModelLevel1,
                permissions=[AllowAllPermission],
                fields={"name"},
            )
        )

        result = config.validate_exposed_models(registry)
        self.assertTrue(result)