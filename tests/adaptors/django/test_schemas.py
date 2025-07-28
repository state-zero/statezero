import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

import unittest
from typing import Type

from django.db import models
from djmoney.models.fields import MoneyField
from hypothesis import HealthCheck, given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from statezero.adaptors.django.config import config, registry
# Import the schema generator and necessary classes.
from statezero.adaptors.django.schemas import DjangoSchemaGenerator
from statezero.core.classes import (AdditionalField, FieldFormat, FieldType,
                                    ModelSchemaMetadata, SchemaFieldMetadata)


# No longer need the openapi_spec_validator
# from openapi_spec_validator import validate




# Define a proper dummy model config (instead of the app-level config)
class DummyModelConfig:
    additional_fields = []
    filterable_fields = "__all__"
    searchable_fields = "__all__"
    ordering_fields = "__all__"
    pre_hooks = []
    post_hooks = []
    fields = "__all__"


# ----------------------
# Existing Test Models
# ----------------------


class DummyRelated(models.Model):
    name = models.CharField(max_length=50, verbose_name="Related Name")

    class Meta:
        app_label = "testapp"
        verbose_name = "dummy related"
        verbose_name_plural = "dummy relateds"


class SimpleDummyModel(models.Model):
    auto_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, verbose_name="Name")
    age = models.IntegerField(default=0)
    updated = models.DateField(auto_now=True)

    class Meta:
        app_label = "testapp"
        verbose_name = "simple dummy"
        verbose_name_plural = "simple dummies"


class ComplexDummyModel(models.Model):
    auto_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, verbose_name="Name")
    age = models.IntegerField(default=0)
    bio = models.TextField(null=True, blank=True)
    price = MoneyField(max_digits=10, decimal_places=2, default=0)
    related = models.ForeignKey(DummyRelated, on_delete=models.CASCADE)
    many_related = models.ManyToManyField(DummyRelated)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateField(auto_now=True)
    default_callable = models.CharField(max_length=50, default=lambda: "callable")

    class Meta:
        app_label = "testapp"
        verbose_name = "complex dummy"
        verbose_name_plural = "complex dummies"


# ----------------------
# Test Cases (using setUp/tearDown to override get_config)
# ----------------------


class TestSimpleFields(unittest.TestCase):
    def setUp(self):
        self.generator = DjangoSchemaGenerator()
        # Save original and override get_config
        self._original_get_config = registry.get_config
        registry.get_config = lambda model: DummyModelConfig()

    def tearDown(self):
        registry.get_config = self._original_get_config

    def test_simple_field_schema(self):
        schema_meta = self.generator.generate_schema(
            SimpleDummyModel, global_schema_overrides={}, additional_fields=[]
        )
        # Instead of get_openapi_schema, now we simply call .dict()
        schema_dict = schema_meta.dict()
        # (Removed: validate(schema_dict))

        self.assertIsInstance(schema_meta, ModelSchemaMetadata)
        self.assertEqual(schema_meta.model_name, "testapp.simpledummymodel")
        self.assertEqual(schema_meta.primary_key_field, "auto_id")

        # Check that simple fields are correctly generated.
        self.assertIn("name", schema_dict["properties"])
        name_field = schema_meta.properties["name"]
        self.assertEqual(name_field.type, FieldType.STRING)
        self.assertEqual(name_field.title, "Name")

        self.assertIn("age", schema_dict["properties"])
        age_field = schema_meta.properties["age"]
        self.assertEqual(age_field.type, FieldType.INTEGER)

        self.assertIn("updated", schema_dict["properties"])
        updated_field = schema_meta.properties["updated"]
        self.assertEqual(updated_field.format, FieldFormat.DATE)


class TestComplexFieldsAndRelationships(unittest.TestCase):
    def setUp(self):
        self.generator = DjangoSchemaGenerator()
        self._original_get_config = registry.get_config
        registry.get_config = lambda model: DummyModelConfig()

    def tearDown(self):
        registry.get_config = self._original_get_config

    def test_complex_fields_schema(self):
        schema_meta = self.generator.generate_schema(
            ComplexDummyModel,
            global_schema_overrides=config.schema_overrides,
            additional_fields=[],
        )
        schema_dict = schema_meta.dict()
        # (Removed: validate(schema_dict))

        # Check MoneyField: should have a definition and a $ref.
        self.assertIn("price", schema_meta.properties)
        price_field = schema_meta.properties["price"]
        self.assertEqual(price_field.format, FieldFormat.MONEY)
        self.assertIsNotNone(price_field.ref)

        # Check foreign key relationship.
        self.assertIn("related", schema_meta.relationships)
        rel = schema_meta.relationships["related"]
        self.assertEqual(rel["type"], FieldFormat.FOREIGN_KEY)
        self.assertIn("testapp", rel["model"])

        # Check many-to-many relationship.
        self.assertIn("many_related", schema_meta.relationships)
        m2m = schema_meta.relationships["many_related"]
        self.assertEqual(m2m["type"], FieldFormat.MANY_TO_MANY)

        # Check that callable defaults are handled (evaluated to their return value).
        default_callable_field = schema_meta.properties["default_callable"]
        self.assertEqual(default_callable_field.default, "callable")


class TestAdditionalFields(unittest.TestCase):
    def setUp(self):
        self.generator = DjangoSchemaGenerator()

        # Define a dummy config that provides an additional field.
        class DummyConfigWithAdditional:
            additional_fields = [
                AdditionalField(
                    name="extra_field",
                    field=models.CharField(max_length=20),
                    title="Extra"
                )
            ]
            filterable_fields = "__all__"
            searchable_fields = "__all__"
            ordering_fields = "__all__"
            pre_hooks = []
            post_hooks = []
            fields = "__all__"

        self._original_get_config = registry.get_config
        registry.get_config = lambda model: DummyConfigWithAdditional()

    def tearDown(self):
        registry.get_config = self._original_get_config

    def test_additional_field_inclusion(self):
        schema_meta = self.generator.generate_schema(
            ComplexDummyModel, global_schema_overrides={}, additional_fields=[]
        )
        schema_dict = schema_meta.dict()
        # (Removed: validate(schema_dict))

        self.assertIn("extra_field", schema_meta.properties)
        extra_field = schema_meta.properties["extra_field"]
        self.assertTrue(extra_field.read_only)
        self.assertEqual(extra_field.title, "Extra")


# ----------------------
# Hypothesis-based Dynamic Model Tests
# ----------------------


def create_dynamic_model(model_name: str, field_defs: dict) -> Type[models.Model]:
    """
    Dynamically creates and returns a Django model.
    """
    if not any(getattr(f, "primary_key", False) for f in field_defs.values()):
        field_defs["id"] = models.AutoField(primary_key=True)
    field_defs["__module__"] = __name__
    Meta = type(
        "Meta",
        (),
        {
            "app_label": "testapp",
            "verbose_name": model_name.lower(),
            "verbose_name_plural": model_name.lower() + "s",
        },
    )
    field_defs["Meta"] = Meta
    return type(model_name, (models.Model,), field_defs)


@st.composite
def django_field_strategy(draw):
    field_type = draw(
        st.sampled_from(
            [
                "CharField",
                "TextField",
                "IntegerField",
                "BooleanField",
                "DateField",
                "DateTimeField",
                "DecimalField",
            ]
        )
    )

    kwargs = {}
    kwargs["blank"] = draw(st.booleans())
    kwargs["null"] = draw(st.booleans())

    if draw(st.booleans()):
        if field_type == "IntegerField":
            kwargs["default"] = draw(st.integers(min_value=0, max_value=100))
        elif field_type in ["CharField", "TextField"]:
            kwargs["default"] = draw(st.text(min_size=1, max_size=10))
        elif field_type == "BooleanField":
            kwargs["default"] = draw(st.booleans())
        elif field_type in ["DateField", "DateTimeField"]:
            kwargs["default"] = draw(st.dates()).isoformat()
        elif field_type == "DecimalField":
            kwargs["default"] = str(draw(st.floats(min_value=0, max_value=100)))

    if field_type == "CharField":
        kwargs["max_length"] = draw(st.integers(min_value=5, max_value=100))
        return draw(st.just(models.CharField(**kwargs)))
    elif field_type == "TextField":
        return draw(st.just(models.TextField(**kwargs)))
    elif field_type == "IntegerField":
        return draw(st.just(models.IntegerField(**kwargs)))
    elif field_type == "BooleanField":
        return draw(st.just(models.BooleanField(**kwargs)))
    elif field_type == "DateField":
        return draw(st.just(models.DateField(**kwargs)))
    elif field_type == "DateTimeField":
        return draw(st.just(models.DateTimeField(**kwargs)))
    elif field_type == "DecimalField":
        kwargs["max_digits"] = draw(st.integers(min_value=3, max_value=10))
        kwargs["decimal_places"] = draw(st.integers(min_value=1, max_value=5))
        return draw(st.just(models.DecimalField(**kwargs)))
    else:
        kwargs["max_length"] = 50
        return draw(st.just(models.CharField(**kwargs)))


@st.composite
def dynamic_model_strategy(draw):
    num_fields = draw(st.integers(min_value=1, max_value=5))
    fields = {}
    identifier_strategy = st.from_regex(
        r"(?!Meta$|__module__$)[a-zA-Z_][a-zA-Z0-9_]*", fullmatch=True
    )

    for _ in range(num_fields):
        field_name = draw(identifier_strategy)
        while field_name in fields:
            field_name = draw(identifier_strategy)
        fields[field_name] = draw(django_field_strategy())
    return fields


class TestDynamicModelsWithHypothesis(unittest.TestCase):
    def setUp(self):
        self.generator = DjangoSchemaGenerator()
        self._original_get_config = registry.get_config
        registry.get_config = lambda model: DummyModelConfig()

    def tearDown(self):
        registry.get_config = self._original_get_config

    @hypothesis_settings(max_examples=10, suppress_health_check=[HealthCheck.too_slow])
    @given(dynamic_model_strategy())
    def test_dynamic_model_schema_generation(self, field_defs):
        model_name = "DynamicModel"
        DynamicModel = create_dynamic_model(model_name, field_defs)
        schema_meta = self.generator.generate_schema(
            DynamicModel, global_schema_overrides={}, additional_fields=[]
        )
        schema_dict = schema_meta.dict()
        # (Removed: validate(schema_dict))

        self.assertEqual(schema_meta.model_name, "testapp.dynamicmodel")
        self.assertIsInstance(schema_meta.properties, dict)
        for field_name in field_defs.keys():
            self.assertIn(field_name, schema_meta.properties)


if __name__ == "__main__":
    unittest.main()
