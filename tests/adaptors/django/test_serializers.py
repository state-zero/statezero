import os

# Ensure the DJANGO_SETTINGS_MODULE is set before any Django-related imports.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django

django.setup()

import unittest
from decimal import Decimal
from typing import Any, Dict, Set

from django.conf import settings
from django.db import models
from django.test import TestCase
from rest_framework import serializers

from ormbridge.adaptors.django.config import config, registry
from ormbridge.adaptors.django.serializers import (DRFDynamicSerializer,
                                                   DynamicModelSerializer,
                                                   RelatedFieldWithRepr,
                                                   get_custom_serializer)
from tests.django_app.models import (ComprehensiveModel, DeepModelLevel1,
                                     DeepModelLevel2, DeepModelLevel3,
                                     DummyModel, DummyRelatedModel)

###############################################################################
# Dummy Cache and Dependency Store implementations for testing caching.
###############################################################################


class DummyCacheBackend:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value

    def invalidate(self, key):
        self.store.pop(key, None)


class DummyDependencyStore:
    def __init__(self):
        self.deps = {}

    def add_cache_key(self, model_name, instance_pk, cache_key):
        self.deps.setdefault(model_name, {}).setdefault(instance_pk, set()).add(
            cache_key
        )

    def get_cache_keys(self, model_name, instance_pk):
        return self.deps.get(model_name, {}).get(instance_pk, set()).copy()

    def clear_cache_keys(self, model_name, instance_pk):
        if model_name in self.deps:
            self.deps[model_name].pop(instance_pk, None)


###############################################################################
# Optionally, define a custom ModelSummaryRepresentation for testing.
###############################################################################


class ModelSummaryRepresentation:
    def __init__(self, id, repr, img=None, model_name=None):
        self.id = id
        self.repr = repr
        self.img = img
        self.model_name = model_name

    def to_dict(self):
        return {"id": self.id, "repr": self.repr, "img": self.img}


class DummySerializerField(serializers.Field):
    pass


###############################################################################
# Tests
###############################################################################


class GetCustomSerializerTests(TestCase):
    def setUp(self):
        # Save originals to restore later
        self.orig_config = (
            config.custom_serializers.copy()
            if hasattr(config, "custom_serializers")
            else {}
        )
        config.custom_serializers = {}
        self.orig_settings = getattr(settings, "CUSTOM_FIELD_SERIALIZERS", {}).copy()
        settings.CUSTOM_FIELD_SERIALIZERS = {}

    def tearDown(self):
        config.custom_serializers = self.orig_config
        settings.CUSTOM_FIELD_SERIALIZERS = self.orig_settings

    def test_config_override(self):
        class DummyField:
            pass

        config.custom_serializers = {DummyField: DummySerializerField}
        result = get_custom_serializer(DummyField)
        self.assertEqual(result, DummySerializerField)

    def test_settings_override(self):
        class DummyField:
            pass

        config.custom_serializers = {}  # ensure app config is empty
        key = f"{DummyField.__module__}.{DummyField.__name__}"
        settings.CUSTOM_FIELD_SERIALIZERS = {
            key: f"{DummySerializerField.__module__}.{DummySerializerField.__name__}"
        }
        result = get_custom_serializer(DummyField)
        self.assertEqual(result, DummySerializerField)

    def test_get_custom_serializer_none(self):
        class DummyField:
            pass

        config.custom_serializers = {}
        settings.CUSTOM_FIELD_SERIALIZERS = {}
        result = get_custom_serializer(DummyField)
        self.assertIsNone(result)


class RelatedFieldWithReprTests(TestCase):
    def setUp(self):
        self.related = DummyRelatedModel.objects.create(name="TestRelated")

    def test_to_representation_minimal_single(self):
        field = RelatedFieldWithRepr(queryset=DummyRelatedModel.objects.all(), depth=0)
        rep = field.to_representation(self.related)
        expected = {
            "id": self.related.pk,
            "repr": str(self.related),
            "img": self.related.__img__(),
        }
        self.assertEqual(rep, expected)

    def test_to_representation_minimal_many(self):
        r1 = DummyRelatedModel.objects.create(name="Test1")
        r2 = DummyRelatedModel.objects.create(name="Test2")
        qs = DummyRelatedModel.objects.all().filter(pk__in=[r1.pk, r2.pk])
        field = RelatedFieldWithRepr(queryset=DummyRelatedModel.objects.all(), depth=0)
        rep = field.to_representation(qs)
        expected = [
            {"id": r1.pk, "repr": str(r1), "img": r1.__img__()},
            {"id": r2.pk, "repr": str(r2), "img": r2.__img__()},
        ]
        rep_sorted = sorted(rep, key=lambda d: d["id"])
        expected_sorted = sorted(expected, key=lambda d: d["id"])
        self.assertEqual(rep_sorted, expected_sorted)

    def test_to_representation_expanded_single(self):
        SerializerClass = DynamicModelSerializer.for_model(DummyRelatedModel, depth=1)
        parent = SerializerClass(instance=self.related, context={"fields_map": {}})
        field = RelatedFieldWithRepr(queryset=DummyRelatedModel.objects.all(), depth=1)
        field.bind("related", parent)
        rep = field.to_representation(self.related)
        expected = {
            "id": self.related.pk,
            "name": self.related.name,
            "repr": str(self.related),
            "img": self.related.__img__(),
        }
        self.assertEqual(rep, expected)

    def test_to_representation_expanded_many(self):
        r1 = DummyRelatedModel.objects.create(name="Test1")
        r2 = DummyRelatedModel.objects.create(name="Test2")
        qs = DummyRelatedModel.objects.filter(pk__in=[r1.pk, r2.pk])
        SerializerClass = DynamicModelSerializer.for_model(DummyRelatedModel, depth=1)
        parent = SerializerClass(instance=r1, context={"fields_map": {}})
        field = RelatedFieldWithRepr(queryset=DummyRelatedModel.objects.all(), depth=1)
        field.bind("related", parent)
        rep = field.to_representation(qs)
        expected_r1 = {
            "id": r1.pk,
            "name": r1.name,
            "repr": str(r1),
            "img": r1.__img__(),
        }
        expected_r2 = {
            "id": r2.pk,
            "name": r2.name,
            "repr": str(r2),
            "img": r2.__img__(),
        }
        expected = [expected_r1, expected_r2]
        rep_sorted = sorted(rep, key=lambda d: d["id"])
        expected_sorted = sorted(expected, key=lambda d: d["id"])
        self.assertEqual(rep_sorted, expected_sorted)

    def test_to_internal_value(self):
        related = self.related
        field = RelatedFieldWithRepr(queryset=DummyRelatedModel.objects.all(), depth=0)
        data = {"id": related.pk}
        result = field.to_internal_value(data)
        self.assertEqual(result, related)
        result2 = field.to_internal_value(related.pk)
        self.assertEqual(result2, related)


class DynamicModelSerializerTests(TestCase):
    def setUp(self):
        self.related = DummyRelatedModel.objects.create(name="Related")
        self.dummy = DummyModel.objects.create(name="Test", related=self.related)
        # Instead of setting on the serializer class, assign to global config.
        config.cache_backend = DummyCacheBackend()
        config.dependency_store = DummyDependencyStore()

    def test_allowed_fields_filtering(self):
        fields_map: Dict[str, Set[str]] = {
            "django_app.dummymodel": {"name", "computed"}
        }
        SerializerClass = DynamicModelSerializer.for_model(DummyModel, depth=1)
        serializer = SerializerClass(
            instance=self.dummy, context={"fields_map": fields_map}, depth=1
        )
        self.assertIn("name", serializer.fields)
        self.assertNotIn("id", serializer.fields)
        self.assertNotIn("related", serializer.fields)

    def test_get_repr_and_get_img(self):
        SerializerClass = DynamicModelSerializer.for_model(DummyModel, depth=0)
        serializer = SerializerClass(instance=self.dummy, context={"fields_map": {}})
        self.assertEqual(serializer.get_repr(self.dummy), str(self.dummy))
        self.assertEqual(serializer.get_img(self.dummy), self.dummy.__img__())

    def test_additional_computed_fields(self):
        class DummyAdditionalField:
            def __init__(self, name, field, title=None):
                self.name = name
                self.field = field
                self.title = title

        class DummyModelConfig:
            def __init__(self, additional_fields):
                self.additional_fields = additional_fields
                self.pre_hooks = []
                self.post_hooks = []
                self.custom_querysets = {}

        additional_field = DummyAdditionalField(
            "computed", models.CharField(max_length=255), title="Computed Field"
        )
        dummy_config = DummyModelConfig([additional_field])
        original_get_config = registry.get_config
        registry.get_config = lambda model: (
            dummy_config if model == DummyModel else None
        )

        SerializerClass = DynamicModelSerializer.for_model(DummyModel, depth=0)
        serializer = SerializerClass(instance=self.dummy, context={"fields_map": {}})
        self.assertIn("computed", serializer.fields)
        data = serializer.data
        self.assertIn("computed", data)
        registry.get_config = original_get_config

    def test_dependency_logging_expanded(self):
        SerializerClass = DynamicModelSerializer.for_model(DummyModel, depth=1)
        serializer = SerializerClass(
            instance=self.dummy, context={"fields_map": {}}, depth=1
        )
        _ = serializer.data
        dep_registry = serializer.context.get("dependency_registry", {})
        model_key = config.orm_provider.get_model_name(DummyRelatedModel)
        self.assertIn(model_key, dep_registry)
        self.assertIn(self.related.pk, dep_registry[model_key])

    def test_caching_single_object(self):
        # First serialization should store a value in the dummy cache.
        serializer_wrapper = DRFDynamicSerializer()
        data1 = serializer_wrapper.serialize(
            self.dummy, DummyModel, depth=0, fields_map={}
        )
        # Check that a cache entry exists in the global config.
        cache_keys = list(config.cache_backend.store.keys())
        self.assertTrue(len(cache_keys) > 0)
        # Change the underlying model (simulate external change) and serialize again.
        self.dummy.name = "Changed"
        self.dummy.save()
        # Second call should return the cached result (thus still showing the old name).
        data2 = serializer_wrapper.serialize(
            self.dummy, DummyModel, depth=0, fields_map={}
        )
        self.assertEqual(data1, data2)

    def test_caching_list_minimal(self):
        r1 = DummyRelatedModel.objects.create(name="Related1")
        r2 = DummyRelatedModel.objects.create(name="Related2")
        d1 = DummyModel.objects.create(name="Test1", related=r1)
        d2 = DummyModel.objects.create(name="Test2", related=r2)
        serializer_wrapper = DRFDynamicSerializer()
        data = serializer_wrapper.serialize(
            [d1, d2], DummyModel, depth=0, fields_map={}, many=True
        )
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        # Check that each individual instance is cached in the global cache.
        cache_keys = list(config.cache_backend.store.keys())
        # We expect at least two distinct cache keys (one per instance)
        self.assertTrue(len(cache_keys) >= 2)


class DRFDynamicSerializerTests(TestCase):
    def setUp(self):
        self.related = DummyRelatedModel.objects.create(name="Related")
        self.dummy = DummyModel.objects.create(name="Test", related=self.related)
        config.cache_backend = DummyCacheBackend()
        config.dependency_store = DummyDependencyStore()

    def test_serialize_single_object_minimal(self):
        serializer_wrapper = DRFDynamicSerializer()
        data = serializer_wrapper.serialize(
            self.dummy, DummyModel, depth=0, fields_map={}
        )
        self.assertEqual(data["id"], self.dummy.pk)
        self.assertEqual(data["name"], self.dummy.name)
        self.assertIn("related", data)
        self.assertEqual(data["related"]["id"], self.related.pk)
        self.assertEqual(data["related"]["repr"], str(self.related))
        self.assertEqual(data["related"]["img"], self.related.__img__())

    def test_serialize_list_minimal(self):
        r1 = DummyRelatedModel.objects.create(name="Related1")
        r2 = DummyRelatedModel.objects.create(name="Related2")
        d1 = DummyModel.objects.create(name="Test1", related=r1)
        d2 = DummyModel.objects.create(name="Test2", related=r2)
        serializer_wrapper = DRFDynamicSerializer()
        data = serializer_wrapper.serialize(
            [d1, d2], DummyModel, depth=0, fields_map={}, many=True
        )
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)

    def test_deserialize_valid_data(self):
        original_is_valid = DynamicModelSerializer.is_valid

        def fake_is_valid(self, raise_exception=False):
            self._validated_data = self.initial_data
            return True

        DynamicModelSerializer.is_valid = fake_is_valid

        serializer_wrapper = DRFDynamicSerializer()
        input_data = {"name": "Test"}
        validated = serializer_wrapper.deserialize(DummyModel, input_data)
        self.assertEqual(validated, input_data)
        DynamicModelSerializer.is_valid = original_is_valid


class DependencyLoggingTests(TestCase):
    def test_dependency_logging_on_dummy_model(self):
        related = DummyRelatedModel.objects.create(name="DepTestRelated")
        dummy = DummyModel.objects.create(name="DepTestDummy", related=related)
        SerializerClass = DynamicModelSerializer.for_model(DummyModel, depth=1)
        serializer = SerializerClass(
            instance=dummy, context={"fields_map": {}}, depth=1
        )
        _ = serializer.data
        dep_registry: Dict = serializer.context.get("dependency_registry", {})
        related_key = config.orm_provider.get_model_name(DummyRelatedModel)
        self.assertIn(related_key, dep_registry)
        self.assertIn(related.pk, dep_registry[related_key])

    def test_dependency_logging_on_deep_models(self):
        level3 = DeepModelLevel3.objects.create(name="Level3Test")
        level2 = DeepModelLevel2.objects.create(name="Level2Test", level3=level3)
        level1 = DeepModelLevel1.objects.create(name="Level1Test", level2=level2)
        dummy1 = DummyModel.objects.create(name="DeepDummy1", related=None)
        dummy2 = DummyModel.objects.create(name="DeepDummy2", related=None)
        level1.comprehensive_models.add(dummy1, dummy2)

        SerializerClass = DynamicModelSerializer.for_model(DeepModelLevel1, depth=2)
        serializer = SerializerClass(
            instance=level1, context={"fields_map": {}}, depth=2
        )
        _ = serializer.data
        dep_registry: Dict = serializer.context.get("dependency_registry", {})

        level2_key = config.orm_provider.get_model_name(DeepModelLevel2)
        level3_key = config.orm_provider.get_model_name(DeepModelLevel3)
        dummy_key = config.orm_provider.get_model_name(DummyModel)

        self.assertIn(level2_key, dep_registry)
        self.assertIn(level3_key, dep_registry)
        self.assertIn(dummy_key, dep_registry)
        self.assertIn(level2.pk, dep_registry[level2_key])
        self.assertIn(level3.pk, dep_registry[level3_key])
        dummy_logged = (
            dummy1.pk in dep_registry[dummy_key] or dummy2.pk in dep_registry[dummy_key]
        )
        self.assertTrue(dummy_logged)

    def test_dependency_logging_on_comprehensive_model(self):
        level3 = DeepModelLevel3.objects.create(name="CompLevel3")
        level2 = DeepModelLevel2.objects.create(name="CompLevel2", level3=level3)
        level1 = DeepModelLevel1.objects.create(name="CompLevel1", level2=level2)
        comp = ComprehensiveModel.objects.create(
            char_field="TestComp",
            text_field="Some text",
            int_field=42,
            bool_field=True,
            decimal_field=Decimal("10.50"),
            json_field={"key": "value"},
            money_field=Decimal("10.50"),
            related=level1,
        )
        SerializerClass = DynamicModelSerializer.for_model(ComprehensiveModel, depth=1)
        serializer = SerializerClass(instance=comp, context={"fields_map": {}}, depth=1)
        _ = serializer.data
        dep_registry: Dict = serializer.context.get("dependency_registry", {})

        level1_key = config.orm_provider.get_model_name(DeepModelLevel1)
        self.assertIn(level1_key, dep_registry)
        self.assertIn(level1.pk, dep_registry[level1_key])


if __name__ == "__main__":
    unittest.main()
