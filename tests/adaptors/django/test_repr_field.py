"""
Test to verify that repr field is included in read operations after serializer refactoring.
"""
from django.test import TestCase
from statezero.adaptors.django.config import config
from statezero.adaptors.django.serializers import DRFDynamicSerializer
from tests.django_app.models import DummyModel, DummyRelatedModel


class ReprFieldReadOpsTest(TestCase):
    """Test that repr field is returned in all read operations"""

    def setUp(self):
        self.related = DummyRelatedModel.objects.create(name="Related")
        self.dummy1 = DummyModel.objects.create(name="Test1", related=self.related, value=42)
        self.dummy2 = DummyModel.objects.create(name="Test2", related=self.related, value=100)

        self.dummy_model_name = config.orm_provider.get_model_name(DummyModel)
        self.related_model_name = config.orm_provider.get_model_name(DummyRelatedModel)

        self.serializer = DRFDynamicSerializer()

    def test_repr_in_single_get(self):
        """Test that repr field is included when getting a single object"""
        fields_map = {
            self.dummy_model_name: {"name", "value"},
        }

        result = self.serializer.serialize(
            self.dummy1,
            DummyModel,
            depth=0,
            fields_map=fields_map
        )

        # Get the serialized object
        dummy_data = result["included"][self.dummy_model_name][self.dummy1.pk]

        # Check that repr field exists
        self.assertIn("repr", dummy_data, "repr field missing in single GET operation")
        self.assertIsInstance(dummy_data["repr"], dict)
        self.assertIn("str", dummy_data["repr"])
        self.assertIn("img", dummy_data["repr"])

    def test_repr_in_list(self):
        """Test that repr field is included for all items in a list operation"""
        fields_map = {
            self.dummy_model_name: {"name", "value"},
        }

        queryset = DummyModel.objects.all()

        result = self.serializer.serialize(
            queryset,
            DummyModel,
            depth=0,
            fields_map=fields_map,
            many=True
        )

        # Get the serialized objects
        dummy_data = result["included"][self.dummy_model_name]

        # Check repr exists for first object
        self.assertIn("repr", dummy_data[self.dummy1.pk], "repr field missing in LIST operation for dummy1")
        self.assertIsInstance(dummy_data[self.dummy1.pk]["repr"], dict)
        self.assertIn("str", dummy_data[self.dummy1.pk]["repr"])

        # Check repr exists for second object
        self.assertIn("repr", dummy_data[self.dummy2.pk], "repr field missing in LIST operation for dummy2")
        self.assertIsInstance(dummy_data[self.dummy2.pk]["repr"], dict)
        self.assertIn("str", dummy_data[self.dummy2.pk]["repr"])

    def test_repr_after_update(self):
        """Test that repr field is included after an update operation"""
        fields_map = {
            self.dummy_model_name: {"name", "value"},
        }

        # Update the object
        update_data = {"name": "Updated"}
        updated_instance = self.serializer.save(
            model=DummyModel,
            data=update_data,
            instance=self.dummy1,
            fields_map=fields_map,
            partial=True
        )

        # Now serialize the updated object
        result = self.serializer.serialize(
            updated_instance,
            DummyModel,
            depth=0,
            fields_map=fields_map
        )

        # Get the serialized object
        dummy_data = result["included"][self.dummy_model_name][updated_instance.pk]

        # Check that repr field exists
        self.assertIn("repr", dummy_data, "repr field missing after UPDATE operation")
        self.assertIsInstance(dummy_data["repr"], dict)
        self.assertIn("str", dummy_data["repr"])
        self.assertEqual(dummy_data["name"], "Updated")

    def test_repr_with_empty_fields_map(self):
        """Test that repr is still included even with minimal fields requested"""
        fields_map = {
            self.dummy_model_name: set(),  # Empty set - only id and repr should be returned
        }

        result = self.serializer.serialize(
            self.dummy1,
            DummyModel,
            depth=0,
            fields_map=fields_map
        )

        # Get the serialized object
        dummy_data = result["included"][self.dummy_model_name][self.dummy1.pk]

        # Should have id and repr only
        self.assertIn("id", dummy_data)
        self.assertIn("repr", dummy_data, "repr field missing with empty fields_map")
        self.assertNotIn("name", dummy_data)
        self.assertNotIn("value", dummy_data)

    def test_repr_with_all_fields(self):
        """Test that repr field is included when requesting all fields via __all__"""
        all_db_fields = config.orm_provider.get_db_fields(DummyModel)

        fields_map = {
            self.dummy_model_name: all_db_fields,  # All fields
        }

        result = self.serializer.serialize(
            self.dummy1,
            DummyModel,
            depth=0,
            fields_map=fields_map
        )

        # Get the serialized object
        dummy_data = result["included"][self.dummy_model_name][self.dummy1.pk]

        # Check that repr field exists along with all other fields
        self.assertIn("repr", dummy_data, "repr field missing when requesting all fields")
        self.assertIsInstance(dummy_data["repr"], dict)
        self.assertIn("str", dummy_data["repr"])
        self.assertIn("img", dummy_data["repr"])
        self.assertIn("id", dummy_data)
        self.assertIn("name", dummy_data)
        self.assertIn("value", dummy_data)

    def test_repr_with_subset_of_fields(self):
        """Test that repr field is included when requesting a subset of fields"""
        fields_map = {
            self.dummy_model_name: {"name"},  # Only request name field
        }

        result = self.serializer.serialize(
            self.dummy1,
            DummyModel,
            depth=0,
            fields_map=fields_map
        )

        # Get the serialized object
        dummy_data = result["included"][self.dummy_model_name][self.dummy1.pk]

        # Should have id, name, and repr
        self.assertIn("id", dummy_data)
        self.assertIn("name", dummy_data)
        self.assertIn("repr", dummy_data, "repr field missing when requesting subset of fields")
        self.assertIsInstance(dummy_data["repr"], dict)
        self.assertIn("str", dummy_data["repr"])
        # Should NOT have value field
        self.assertNotIn("value", dummy_data)

    def test_repr_in_list_with_subset_of_fields(self):
        """Test that repr field is included for all items in list with subset of fields"""
        fields_map = {
            self.dummy_model_name: {"value"},  # Only request value field
        }

        queryset = DummyModel.objects.all()

        result = self.serializer.serialize(
            queryset,
            DummyModel,
            depth=0,
            fields_map=fields_map,
            many=True
        )

        # Get the serialized objects
        dummy_data = result["included"][self.dummy_model_name]

        # Check repr exists for first object
        self.assertIn("repr", dummy_data[self.dummy1.pk], "repr field missing in LIST with subset for dummy1")
        self.assertIn("value", dummy_data[self.dummy1.pk])
        self.assertNotIn("name", dummy_data[self.dummy1.pk])

        # Check repr exists for second object
        self.assertIn("repr", dummy_data[self.dummy2.pk], "repr field missing in LIST with subset for dummy2")
        self.assertIn("value", dummy_data[self.dummy2.pk])
        self.assertNotIn("name", dummy_data[self.dummy2.pk])
