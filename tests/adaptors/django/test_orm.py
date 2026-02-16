import unittest
from typing import Any

from django.db.models import Q
from django.test import TestCase

from statezero.adaptors.django.config import registry
from statezero.adaptors.django.orm import DjangoORMAdapter, QueryASTVisitor
from statezero.adaptors.django.serializers import DRFDynamicSerializer
from statezero.core.config import ModelConfig
from statezero.adaptors.django.event_bus import EventBus
from statezero.core.interfaces import AbstractEventEmitter
from statezero.core.types import ActionType
from tests.django_app.models import DummyModel, DummyRelatedModel


# Dummy permission that always allows all actions.
class AlwaysAllowPermission:
    def allowed_object_actions(self, request: Any, instance: Any, model: Any) -> set:
        # Allow all actions.
        return {
            ActionType.CREATE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.DELETE,
        }

    # Stub methods for other permission methods if needed.
    def visible_fields(self, request: Any, model: Any) -> set:
        return "__all__"

    def allowed_actions(self, request: Any, model: Any) -> set:
        return {
            ActionType.CREATE,
            ActionType.READ,
            ActionType.UPDATE,
            ActionType.DELETE,
        }

    def create_fields(self, request: Any, model: Any) -> set:
        return "__all__"

    def editable_fields(self, request: Any, model: Any) -> set:
        return "__all__"

    def filter_queryset(self, request: Any, queryset: Any) -> Any:
        return queryset


class DummyEventEmitter(AbstractEventEmitter):
    def __init__(self):
        self.events = []

    def emit(self, event_type: ActionType, instance: Any, config: Any = None) -> None:
        self.events.append((event_type, instance))

    def has_permission(self, request, namespace):
        return True

    def authenticate(self, request):
        pass


class QueryASTVisitorTest(TestCase):
    def setUp(self):
        # Create a dummy instance to have a model reference.
        try:
            registry.register(DummyModel, ModelConfig(DummyModel))
        except ValueError:
            pass
        self.visitor = QueryASTVisitor(DummyModel)

    def test_visit_filter_eq(self):
        ast = {"type": "filter", "conditions": {"name": "Test"}}
        q = self.visitor.visit(ast)
        # Q should have a lookup for exact match on name.
        self.assertIn("name", q.children[0])
        self.assertEqual(q.children[0][1], "Test")

    def test_visit_filter_with_operator(self):
        ast = {"type": "filter", "conditions": {"name__icontains": "test"}}
        q = self.visitor.visit(ast)
        # The lookup key should remain as 'name__icontains'
        self.assertIn("name__icontains", q.children[0])
        self.assertEqual(q.children[0][1], "test")

    def test_visit_and_or(self):
        ast = {
            "type": "and",
            "children": [
                {"type": "filter", "conditions": {"name": "Test1"}},
                {
                    "type": "or",
                    "children": [
                        {"type": "filter", "conditions": {"value__gt": 10}},
                        {"type": "filter", "conditions": {"value__lt": 5}},
                    ],
                },
            ],
        }
        q = self.visitor.visit(ast)
        self.assertTrue(isinstance(q, Q))


class DjangoORMAdapterTest(TestCase):
    def setUp(self):
        try:
            registry.register(DummyModel, ModelConfig(DummyModel))
        except ValueError:
            pass
        # Create related instances for foreign key tests.
        self.related1 = DummyRelatedModel.objects.create(name="Rel1")
        self.related2 = DummyRelatedModel.objects.create(name="Rel2")
        # Create some DummyModel instances.
        self.dummy1 = DummyModel.objects.create(
            name="Dummy1", value=10, related=self.related1
        )
        self.dummy2 = DummyModel.objects.create(
            name="Dummy2", value=20, related=self.related2
        )
        self.adapter = DjangoORMAdapter()
        self.adapter.set_queryset(DummyModel.objects.all())
        # Dummy request (can be None for tests) and permission that always allows.
        self.dummy_req = None
        self.always_allow = AlwaysAllowPermission
        # Use the actual serializer instead of a Mock
        self.serializer = DRFDynamicSerializer()

    def test_create(self):
        fields_map = {"django_app.dummymodel": ['name', 'value', 'related']}
        data = {"name": "Dummy3", "value": 30, "related": self.related1}
        instance = self.adapter.create(data, self.serializer, req=self.dummy_req, fields_map=fields_map)
        self.assertEqual(instance.name, "Dummy3")
        self.assertEqual(instance.value, 30)

    def test_filter_node(self):
        # Filter for dummy models with value greater than or equal to 20.
        ast = {"type": "filter", "conditions": {"value__gte": 20}}
        self.adapter.set_queryset(DummyModel.objects.all())
        self.adapter.filter_node(ast)
        qs = self.adapter.queryset
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().name, "Dummy2")

    def test_update(self):
        # Update dummy1's value to 50 using filter.
        ast = {
            "filter": {"type": "filter", "conditions": {"name": "Dummy1"}},
            "data": {"value": 50},
        }
        self.adapter.set_queryset(DummyModel.objects.all())
        updated_count = self.adapter.update(ast, self.dummy_req, [self.always_allow])
        self.assertEqual(updated_count, 1)
        dummy = DummyModel.objects.get(name="Dummy1")
        self.assertEqual(dummy.value, 50)

    def test_delete(self):
        # Delete dummy2 using filter.
        ast = {"filter": {"type": "filter", "conditions": {"name": "Dummy2"}}}
        self.adapter.set_queryset(DummyModel.objects.all())
        deleted_count = self.adapter.delete(ast, self.dummy_req, [self.always_allow])
        self.assertEqual(deleted_count, 1)
        self.assertFalse(DummyModel.objects.filter(name="Dummy2").exists())

    def test_get(self):
        ast = {"filter": {"type": "filter", "conditions": {"name": "Dummy1"}}}
        self.adapter.set_queryset(DummyModel.objects.all())
        instance = self.adapter.get(ast, self.dummy_req, [self.always_allow])
        self.assertEqual(instance.name, "Dummy1")

    def test_get_or_create(self):
        # Test get_or_create when the instance does not exist.
        ast = {
            "lookup": {"name": "Dummy4"},
            "defaults": {"value": 40, "related": self.related1},
        }
        fields_map = {"django_app.dummymodel": ['name', 'value', 'related']}
        self.adapter.set_queryset(DummyModel.objects.all())
        instance, created = self.adapter.get_or_create(ast, self.serializer, self.dummy_req, [self.always_allow], fields_map)
        self.assertTrue(created, "Instance should be created because it did not exist.")
        self.assertEqual(
            instance.name, "Dummy4", "Instance name should match the lookup value."
        )

        # Test get_or_create when the instance exists.
        instance2, created2 = self.adapter.get_or_create(ast, self.serializer, self.dummy_req, [self.always_allow], fields_map)
        self.assertFalse(
            created2, "Instance should not be created again when it already exists."
        )
        self.assertEqual(
            instance.pk, instance2.pk, "Both calls should return the same instance."
        )

    def test_update_or_create(self):
        # Test update_or_create when the instance does not exist.
        ast = {
            "lookup": {"name": "Dummy5"},
            "defaults": {"value": 55, "related": self.related2},
        }
        fields_map = {"django_app.dummymodel": ['name', 'value', 'related']}
        self.adapter.set_queryset(DummyModel.objects.all())
        instance, created = self.adapter.update_or_create(
            ast, self.dummy_req, self.serializer, [self.always_allow], fields_map, fields_map 
        )
        self.assertTrue(
            created, "Instance should be created since it does not exist yet."
        )
        self.assertEqual(
            instance.value, 55, "The value should be set to 55 as provided in defaults."
        )

        # Now update the instance.
        ast["defaults"]["value"] = 100
        instance2, created2 = self.adapter.update_or_create(
            ast, self.dummy_req, self.serializer, [self.always_allow], fields_map, fields_map
        )
        self.assertFalse(
            created2, "Instance should not be created if it already exists."
        )
        self.assertEqual(
            instance2.value, 100, "The instance value should be updated to 100."
        )

    def test_first_last_exists(self):
        self.adapter.set_queryset(DummyModel.objects.all().order_by("value"))
        first = self.adapter.first()
        last = self.adapter.last()
        self.assertEqual(first.value, min(self.dummy1.value, self.dummy2.value))
        self.assertEqual(last.value, max(self.dummy1.value, self.dummy2.value))
        self.assertTrue(self.adapter.exists())

    def test_aggregate_and_count(self):
        self.adapter.set_queryset(DummyModel.objects.all())
        # Test aggregate count.
        agg_result = self.adapter.aggregate(
            [{"function": "count", "field": "id", "alias": "id_count"}]
        )
        self.assertEqual(agg_result["data"]["id_count"], DummyModel.objects.count())
        # Test count method.
        count = self.adapter.count("id")
        self.assertEqual(count, DummyModel.objects.count())

    def test_order_by_select_fields_fetch_list(self):
        # Order by value descending.
        self.adapter.set_queryset(DummyModel.objects.all())
        self.adapter.order_by(["-value"])
        qs = self.adapter.queryset
        self.assertEqual(qs.first().value, max(self.dummy1.value, self.dummy2.value))
        # Select only the 'name' field.
        self.adapter.select_fields(["name"])
        result_list = self.adapter.fetch_list(0, 10)
        for item in result_list:
            self.assertIn("name", item)
            self.assertNotIn("value", item)

    def test_build_model_graph(self):
        graph = self.adapter.build_model_graph(DummyModel)
        self.assertTrue(graph.has_node("django_app.dummymodel"))
        self.assertTrue(graph.has_node("django_app.dummymodel::name"))
        self.assertTrue(graph.has_node("django_app.dummyrelatedmodel"))

    def test_update_instance(self):
        # Create a new instance that we will update via instance-based operation.
        instance = DummyModel.objects.create(
            name="InstanceForUpdate", value=100, related=self.related1
        )
        ast = {
            "filter": {"type": "filter", "conditions": {"id": instance.id}},
            "data": {"value": 555},
        }
        fields_map = {"django_app.dummymodel": ['name', 'value', 'related']}
        # Call the instance-based update.
        updated_instance = self.adapter.update_instance(
            ast, self.dummy_req, [self.always_allow], self.serializer, fields_map
        )

        self.assertEqual(updated_instance.value, 555)
        # Verify that the change is persisted.
        instance.refresh_from_db()
        self.assertEqual(instance.value, 555)

    def test_delete_instance(self):
        # Create a new instance that we will delete via instance-based operation.
        instance = DummyModel.objects.create(
            name="InstanceForDelete", value=200, related=self.related1
        )
        ast = {"filter": {"type": "filter", "conditions": {"id": instance.id}}}
        # Call the instance-based delete.
        self.adapter.delete_instance(ast, self.dummy_req, [self.always_allow])
        # Verify that the instance has been deleted.
        with self.assertRaises(DummyModel.DoesNotExist):
            DummyModel.objects.get(id=instance.id)


if __name__ == "__main__":
    unittest.main()