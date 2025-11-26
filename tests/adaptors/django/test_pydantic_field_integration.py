"""
Integration tests for django-pydantic-field's SchemaField with statezero serialization.
Tests that Pydantic models are serialized correctly as dicts (not nested arrays).
"""
import unittest

try:
    from django_pydantic_field import SchemaField
    from pydantic import BaseModel
    PYDANTIC_FIELD_AVAILABLE = True
except ImportError:
    PYDANTIC_FIELD_AVAILABLE = False


@unittest.skipUnless(PYDANTIC_FIELD_AVAILABLE, "django-pydantic-field not installed")
class PydanticFieldIntegrationTest(unittest.TestCase):
    """Test SchemaField serialization through the statezero serializer"""

    @classmethod
    def setUpClass(cls):
        """Create test model dynamically since SchemaField may not be available"""
        from django.db import models, connection
        from pydantic import BaseModel
        from typing import List
        from django_pydantic_field import SchemaField

        # Define Pydantic schemas for testing
        class PriceAdjustment(BaseModel):
            type: str
            percent: int

        cls.PriceAdjustment = PriceAdjustment

        # Create a dynamic test model with SchemaField
        class PydanticTestModel(models.Model):
            name = models.CharField(max_length=100)
            adjustment = SchemaField(schema=PriceAdjustment, null=True, blank=True)
            adjustments = SchemaField(schema=List[PriceAdjustment], default=list)

            def __str__(self):
                return f"PydanticTestModel: {self.name}"

            def __img__(self):
                return f"/img/{self.name}.png"

            class Meta:
                app_label = "django_app"

        cls.PydanticTestModel = PydanticTestModel

        # Create the table
        with connection.schema_editor() as schema_editor:
            try:
                schema_editor.create_model(PydanticTestModel)
            except Exception:
                # Table may already exist from previous test run
                pass

    @classmethod
    def tearDownClass(cls):
        """Clean up the dynamic test model table"""
        from django.db import connection

        with connection.schema_editor() as schema_editor:
            try:
                schema_editor.delete_model(cls.PydanticTestModel)
            except Exception:
                pass

    def setUp(self):
        """Create test instances"""
        # Clear any existing test data
        self.PydanticTestModel.objects.all().delete()

        # Create test instance with single Pydantic model
        self.instance_single = self.PydanticTestModel.objects.create(
            name="Single Adjustment",
            adjustment=self.PriceAdjustment(type="adjust_price", percent=5),
            adjustments=[]
        )

        # Create test instance with list of Pydantic models
        self.instance_list = self.PydanticTestModel.objects.create(
            name="Multiple Adjustments",
            adjustment=None,
            adjustments=[
                self.PriceAdjustment(type="adjust_price", percent=10),
                self.PriceAdjustment(type="discount", percent=15),
            ]
        )

    def test_single_pydantic_model_serialization(self):
        """
        Test that a single Pydantic model is serialized as a dict, not nested arrays.

        Without proper serialization, Pydantic models would serialize as:
        [[["type","adjust_price"],["percent",5]]]

        With proper serialization, it should be:
        {"type": "adjust_price", "percent": 5}
        """
        from statezero.adaptors.django.serializers import DRFDynamicSerializer
        from statezero.adaptors.django.config import config

        serializer_wrapper = DRFDynamicSerializer()
        model_name = config.orm_provider.get_model_name(self.PydanticTestModel)

        fields_map = {
            model_name: {"name", "adjustment"}
        }

        result = serializer_wrapper.serialize(
            self.instance_single, self.PydanticTestModel, depth=0, fields_map=fields_map
        )

        # Verify the structure
        self.assertIn("data", result)
        self.assertIn("included", result)
        self.assertIn(model_name, result["included"])

        instance_data = result["included"][model_name][self.instance_single.pk]

        # Verify adjustment is serialized as a dict, not nested arrays
        self.assertIn("adjustment", instance_data)
        adjustment = instance_data["adjustment"]

        self.assertIsInstance(adjustment, dict,
            f"Expected dict, got {type(adjustment).__name__}: {adjustment}")
        self.assertEqual(adjustment["type"], "adjust_price")
        self.assertEqual(adjustment["percent"], 5)

    def test_list_of_pydantic_models_serialization(self):
        """
        Test that a list of Pydantic models is serialized as a list of dicts.

        Without proper serialization, it would serialize as nested arrays like:
        [[[[["type","adjust_price"],["percent",10]]],[[["type","discount"],["percent",15]]]]]

        With proper serialization, it should be:
        [{"type": "adjust_price", "percent": 10}, {"type": "discount", "percent": 15}]
        """
        from statezero.adaptors.django.serializers import DRFDynamicSerializer
        from statezero.adaptors.django.config import config

        serializer_wrapper = DRFDynamicSerializer()
        model_name = config.orm_provider.get_model_name(self.PydanticTestModel)

        fields_map = {
            model_name: {"name", "adjustments"}
        }

        result = serializer_wrapper.serialize(
            self.instance_list, self.PydanticTestModel, depth=0, fields_map=fields_map
        )

        instance_data = result["included"][model_name][self.instance_list.pk]

        # Verify adjustments is serialized as a list of dicts
        self.assertIn("adjustments", instance_data)
        adjustments = instance_data["adjustments"]

        self.assertIsInstance(adjustments, list,
            f"Expected list, got {type(adjustments).__name__}: {adjustments}")
        self.assertEqual(len(adjustments), 2)

        # Verify each item is a dict with correct structure
        for i, adj in enumerate(adjustments):
            self.assertIsInstance(adj, dict,
                f"Expected dict at index {i}, got {type(adj).__name__}: {adj}")
            self.assertIn("type", adj)
            self.assertIn("percent", adj)

        # Verify specific values
        self.assertEqual(adjustments[0]["type"], "adjust_price")
        self.assertEqual(adjustments[0]["percent"], 10)
        self.assertEqual(adjustments[1]["type"], "discount")
        self.assertEqual(adjustments[1]["percent"], 15)

    def test_null_pydantic_field_serialization(self):
        """Test that null SchemaField values are serialized correctly"""
        from statezero.adaptors.django.serializers import DRFDynamicSerializer
        from statezero.adaptors.django.config import config

        serializer_wrapper = DRFDynamicSerializer()
        model_name = config.orm_provider.get_model_name(self.PydanticTestModel)

        fields_map = {
            model_name: {"name", "adjustment"}
        }

        result = serializer_wrapper.serialize(
            self.instance_list, self.PydanticTestModel, depth=0, fields_map=fields_map
        )

        instance_data = result["included"][model_name][self.instance_list.pk]

        # Verify null adjustment is serialized as None
        self.assertIn("adjustment", instance_data)
        self.assertIsNone(instance_data["adjustment"])


if __name__ == "__main__":
    unittest.main()
