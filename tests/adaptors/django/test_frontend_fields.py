import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

from django.test import TestCase

from statezero.adaptors.django.config import config, registry
from statezero.core.config import ModelConfig
from statezero.adaptors.django.schemas import DjangoSchemaGenerator
from statezero.core.ast_parser import ASTParser
from statezero.adaptors.django.permissions import AllowAllPermission
from tests.django_app.models import DummyModel, DummyRelatedModel


class TestFrontendFieldsSchemaGeneration(TestCase):
    """Test that frontend_fields controls which fields appear in schemas"""

    def setUp(self):
        self.generator = DjangoSchemaGenerator()
        self._original_get_config = registry.get_config

    def tearDown(self):
        registry.get_config = self._original_get_config

    def test_schema_respects_frontend_fields_subset(self):
        """Test that schema only includes fields in frontend_fields"""
        # Create a config that limits frontend_fields
        class RestrictedFrontendConfig:
            frontend_fields = {"name", "value"}  # Only these fields in schema
            fields = "__all__"  # All fields allowed for deserialization
            additional_fields = []
            filterable_fields = set()
            searchable_fields = set()
            ordering_fields = set()
            pre_hooks = []
            post_hooks = []
            display = None

        registry.get_config = lambda model: RestrictedFrontendConfig()

        schema_meta = self.generator.generate_schema(
            DummyModel,
            global_schema_overrides={},
            additional_fields=[]
        )

        # Should only include name and value (frontend_fields restricts to these)
        # id and related field should not be in the schema
        field_names = set(schema_meta.properties.keys())
        self.assertIn("name", field_names)
        self.assertIn("value", field_names)
        self.assertNotIn("related", field_names)
        # Verify only the specified fields are present
        self.assertEqual(field_names, {"name", "value"})

    def test_schema_with_frontend_fields_all(self):
        """Test that frontend_fields='__all__' includes all fields"""
        class AllFrontendConfig:
            frontend_fields = "__all__"
            fields = "__all__"
            additional_fields = []
            filterable_fields = set()
            searchable_fields = set()
            ordering_fields = set()
            pre_hooks = []
            post_hooks = []
            display = None

        registry.get_config = lambda model: AllFrontendConfig()

        schema_meta = self.generator.generate_schema(
            DummyModel,
            global_schema_overrides={},
            additional_fields=[]
        )

        # Should include all fields
        field_names = set(schema_meta.properties.keys())
        self.assertIn("id", field_names)
        self.assertIn("name", field_names)
        self.assertIn("value", field_names)
        self.assertIn("related", field_names)

    def test_frontend_fields_default_to_fields(self):
        """Test that frontend_fields defaults to fields when not specified"""
        # Create a ModelConfig instance to test the default behavior
        model_config = ModelConfig(
            model=DummyModel,
            fields={"name", "value"}
            # frontend_fields not specified
        )

        # frontend_fields should default to fields
        self.assertEqual(model_config.frontend_fields, model_config.fields)
        self.assertEqual(model_config.frontend_fields, {"name", "value"})


class TestFrontendFieldsSerialization(TestCase):
    """Test that frontend_fields controls serialization output"""

    def setUp(self):
        self._original_get_config = registry.get_config
        self.model_name = config.orm_provider.get_model_name(DummyModel)

        # Create test instance
        self.related = DummyRelatedModel.objects.create(name="Related")
        self.test_instance = DummyModel.objects.create(
            name="test",
            value=42,
            related=self.related
        )

    def tearDown(self):
        registry.get_config = self._original_get_config
        DummyModel.objects.all().delete()
        DummyRelatedModel.objects.all().delete()

    def test_serialization_uses_frontend_fields_for_read_operations(self):
        """Test that read operations serialize using frontend_fields"""
        # Setup config with restricted frontend_fields
        class RestrictedFrontendConfig:
            frontend_fields = {"name", "value"}  # Only these in schema/read
            fields = "__all__"  # Allow deserialization of all fields
            additional_fields = []
            filterable_fields = set()
            searchable_fields = set()
            ordering_fields = set()
            permissions = [AllowAllPermission]
            pre_hooks = []
            post_hooks = []
            display = None

        registry.get_config = lambda model: RestrictedFrontendConfig()

        # Create an ASTParser to test the read operation
        parser = ASTParser(
            engine=config.orm_provider,
            serializer=config.serializer,
            model=DummyModel,
            config=config,
            registry=registry,
            base_queryset=DummyModel.objects.all(),
            serializer_options={},
            request=None
        )

        # Get the read fields map (used for serialization)
        read_fields = parser._get_operation_fields(DummyModel, "read")

        # Read fields should only include frontend_fields
        # Note: id/pk is always included by Django's permission logic
        self.assertIn("name", read_fields)
        self.assertIn("value", read_fields)
        # related field should not be in the visible fields since frontend_fields restricts it
        # when using AllowAllPermission with "__all__", it defaults to frontend_fields
        self.assertNotIn("related", read_fields)

    def test_deserialization_uses_fields_for_write_operations(self):
        """Test that write operations use 'fields' not 'frontend_fields'"""
        # Setup config where fields differ from frontend_fields
        class AsymmetricFieldsConfig:
            frontend_fields = {"name"}  # Only show name in reads
            fields = {"name", "value"}  # Allow writes to both name and value
            additional_fields = []
            filterable_fields = set()
            searchable_fields = set()
            ordering_fields = set()
            permissions = [AllowAllPermission]
            pre_hooks = []
            post_hooks = []
            display = None

        registry.get_config = lambda model: AsymmetricFieldsConfig()

        # Create an ASTParser to test write operations
        parser = ASTParser(
            engine=config.orm_provider,
            serializer=config.serializer,
            model=DummyModel,
            config=config,
            registry=registry,
            base_queryset=DummyModel.objects.all(),
            serializer_options={},
            request=None
        )

        # Get create/update fields (used for deserialization)
        create_fields = parser._get_operation_fields(DummyModel, "create")
        update_fields = parser._get_operation_fields(DummyModel, "update")

        # Create/update fields should include both name and value
        # These use the "fields" config, not "frontend_fields"
        self.assertIn("name", create_fields)
        self.assertIn("value", create_fields)
        self.assertIn("name", update_fields)
        self.assertIn("value", update_fields)

        # Read fields should only include name
        read_fields = parser._get_operation_fields(DummyModel, "read")
        self.assertIn("name", read_fields)
        # value should not be in read fields when using AllowAllPermission with frontend_fields restriction
        self.assertNotIn("value", read_fields)
