"""
Test nested serializer schema generation
"""
from django.test import TestCase
from rest_framework import serializers
from statezero.adaptors.django.actions import DjangoActionSchemaGenerator


class NestedItemSerializer(serializers.Serializer):
    """A nested serializer for testing"""
    item_id = serializers.IntegerField()
    name = serializers.CharField(max_length=100)
    price = serializers.DecimalField(max_digits=10, decimal_places=2)


class TestResponseSerializer(serializers.Serializer):
    """Test response with nested serializers"""
    # Single nested serializer
    single_item = NestedItemSerializer()
    # Many nested serializers (creates ListSerializer)
    items = NestedItemSerializer(many=True)
    # Regular array field for comparison
    tags = serializers.ListField(child=serializers.CharField())


class NestedSerializerSchemaTest(TestCase):
    """Test nested serializer schema generation"""

    def test_nested_serializer_many_true(self):
        """Test that nested serializers with many=True are typed as array"""
        properties, relationships = DjangoActionSchemaGenerator._get_serializer_schema(
            TestResponseSerializer
        )

        # Check that items field (many=True nested serializer) is an array
        self.assertIn("items", properties)
        self.assertEqual(
            properties["items"]["type"],
            "array",
            f"Expected 'array' but got '{properties['items']['type']}'"
        )

    def test_nested_serializer_single(self):
        """Test that single nested serializers are typed as object"""
        properties, relationships = DjangoActionSchemaGenerator._get_serializer_schema(
            TestResponseSerializer
        )

        # Check that single_item field (nested serializer) is an object
        self.assertIn("single_item", properties)
        self.assertEqual(
            properties["single_item"]["type"],
            "object",
            f"Expected 'object' but got '{properties['single_item']['type']}'"
        )

    def test_regular_list_field(self):
        """Test that regular ListField is still typed as array"""
        properties, relationships = DjangoActionSchemaGenerator._get_serializer_schema(
            TestResponseSerializer
        )

        # Check that tags field (regular ListField) is still an array
        self.assertIn("tags", properties)
        self.assertEqual(
            properties["tags"]["type"],
            "array",
            f"Expected 'array' but got '{properties['tags']['type']}'"
        )
