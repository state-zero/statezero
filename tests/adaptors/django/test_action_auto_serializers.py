import datetime as dt
import uuid
import enum
from typing import Any, Annotated, Optional, Union, Literal

from django.db import models

from django.test import SimpleTestCase
from rest_framework import serializers

from tests.django_app.models import DummyModel, DummyRelatedModel
from statezero.adaptors.django.action_serializers import (
    AutoSerializerInferenceError,
    build_action_input_serializer,
)


class Priority(models.TextChoices):
    LOW = "low", "Low"
    HIGH = "high", "High"


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class ActionAutoSerializerTests(SimpleTestCase):
    def _build(self, func, docstring: str | None = None):
        return build_action_input_serializer(func, docstring=docstring)

    def test_infers_basic_scalar_fields(self):
        def action(
            request,
            name: str,
            count: int,
            ratio: float,
            active: bool,
            at: dt.datetime,
            day: dt.date,
            when: dt.time,
            uid: uuid.UUID,
        ):
            return None

        serializer_class = self._build(action)
        serializer = serializer_class()

        self.assertIsInstance(serializer.fields["name"], serializers.CharField)
        self.assertIsInstance(serializer.fields["count"], serializers.IntegerField)
        self.assertIsInstance(serializer.fields["ratio"], serializers.FloatField)
        self.assertIsInstance(serializer.fields["active"], serializers.BooleanField)
        self.assertIsInstance(serializer.fields["at"], serializers.DateTimeField)
        self.assertIsInstance(serializer.fields["day"], serializers.DateField)
        self.assertIsInstance(serializer.fields["when"], serializers.TimeField)
        self.assertIsInstance(serializer.fields["uid"], serializers.UUIDField)

        self.assertTrue(serializer.fields["name"].required)
        self.assertTrue(serializer.fields["count"].required)

    def test_optional_and_defaults(self):
        def action(
            request,
            title: Optional[str] = None,
            quantity: int = 5,
            note: Optional[str] = None,
        ):
            return None

        serializer = self._build(action)()
        title_field = serializer.fields["title"]
        quantity_field = serializer.fields["quantity"]
        note_field = serializer.fields["note"]

        self.assertFalse(title_field.required)
        self.assertTrue(title_field.allow_null)
        self.assertFalse(quantity_field.required)
        self.assertEqual(quantity_field.default, 5)
        self.assertFalse(note_field.required)
        self.assertTrue(note_field.allow_null)
        self.assertIsNone(note_field.default)

    def test_infers_model_and_list_fields(self):
        def action(
            request,
            related: DummyRelatedModel,
            related_many: list[DummyRelatedModel],
            tags: list[str],
            payloads: list[dict],
            metadata: dict,
        ):
            return None

        serializer = self._build(action)()

        related_field = serializer.fields["related"]
        related_many_field = serializer.fields["related_many"]
        tags_field = serializer.fields["tags"]
        payloads_field = serializer.fields["payloads"]
        metadata_field = serializer.fields["metadata"]

        self.assertIsInstance(related_field, serializers.PrimaryKeyRelatedField)
        self.assertIsInstance(related_many_field, serializers.ManyRelatedField)
        self.assertIsInstance(
            related_many_field.child_relation, serializers.PrimaryKeyRelatedField
        )

        self.assertIsInstance(tags_field, serializers.ListField)
        self.assertIsInstance(tags_field.child, serializers.CharField)

        self.assertIsInstance(payloads_field, serializers.ListField)
        self.assertIsInstance(payloads_field.child, serializers.JSONField)

        self.assertIsInstance(metadata_field, serializers.JSONField)

    def test_docstring_descriptions_are_applied(self):
        def action(request, title: str, count: int):
            """
            Parameters
            ----------
            title : str
                Ticket title.
            count : int
                How many to create.
            """
            return None

        serializer = self._build(action, docstring=action.__doc__)()
        self.assertEqual(serializer.fields["title"].help_text, "Ticket title.")
        self.assertEqual(serializer.fields["count"].help_text, "How many to create.")

    def test_annotated_type_is_unwrapped(self):
        def action(request, tag: Annotated[str, "ignored"]):
            return None

        serializer = self._build(action)()
        self.assertIsInstance(serializer.fields["tag"], serializers.CharField)

    def test_enum_and_textchoices_infer_choice_field(self):
        def action(request, priority: Priority, color: Color):
            return None

        serializer = self._build(action)()
        priority_field = serializer.fields["priority"]
        color_field = serializer.fields["color"]

        self.assertIsInstance(priority_field, serializers.ChoiceField)
        self.assertIsInstance(color_field, serializers.ChoiceField)
        self.assertEqual(list(priority_field.choices.keys()), ["low", "high"])
        self.assertIn("red", list(color_field.choices.keys()))

    def test_literal_infers_choice_field(self):
        def action(request, level: Literal["low", "medium", "high"]):
            return None

        serializer = self._build(action)()
        level_field = serializer.fields["level"]
        self.assertIsInstance(level_field, serializers.ChoiceField)
        self.assertEqual(set(level_field.choices), {"low", "medium", "high"})

    def test_drf_field_annotation_class(self):
        def action(request, email: serializers.EmailField):
            return None

        serializer = self._build(action)()
        email_field = serializer.fields["email"]
        self.assertIsInstance(email_field, serializers.EmailField)

    def test_drf_field_annotation_instance(self):
        def action(request, code: serializers.CharField(max_length=12)):
            return None

        serializer = self._build(action)()
        code_field = serializer.fields["code"]
        self.assertIsInstance(code_field, serializers.CharField)
        self.assertEqual(code_field.max_length, 12)

    def test_drf_field_type_hint_with_docstring(self):
        def action(request, age: serializers.IntegerField):
            """
            Parameters
            ----------
            age : int
                Age in years.
            """
            return None

        serializer = self._build(action, docstring=action.__doc__)()
        age_field = serializer.fields["age"]
        self.assertIsInstance(age_field, serializers.IntegerField)
        self.assertEqual(age_field.help_text, "Age in years.")

    def test_returns_none_when_no_fields(self):
        def action(request):
            return None

        self.assertIsNone(self._build(action))

    def test_untyped_list_raises(self):
        def action(request, items: list):
            return None

        with self.assertRaises(AutoSerializerInferenceError):
            self._build(action)

    def test_any_raises(self):
        def action(request, payload: Any):
            return None

        with self.assertRaises(AutoSerializerInferenceError):
            self._build(action)

    def test_union_multiple_raises(self):
        def action(request, value: Union[int, str]):
            return None

        with self.assertRaises(AutoSerializerInferenceError):
            self._build(action)

    def test_missing_type_hint_raises(self):
        def action(request, value):
            return None

        with self.assertRaises(AutoSerializerInferenceError):
            self._build(action)

    def test_varargs_raises(self):
        def action(request, *args, **kwargs):
            return None

        with self.assertRaises(AutoSerializerInferenceError):
            self._build(action)

    def test_list_any_raises(self):
        def action(request, items: list[Any]):
            return None

        with self.assertRaises(AutoSerializerInferenceError):
            self._build(action)

    def test_list_of_dict_origin(self):
        def action(request, items: list[dict[str, Any]]):
            return None

        serializer = self._build(action)()
        items_field = serializer.fields["items"]
        self.assertIsInstance(items_field, serializers.ListField)
        self.assertIsInstance(items_field.child, serializers.JSONField)

    def test_list_of_model_infers_queryset(self):
        def action(request, models: list[DummyModel]):
            return None

        serializer = self._build(action)()
        field = serializer.fields["models"]
        self.assertIsInstance(field, serializers.ManyRelatedField)
        self.assertIsInstance(field.child_relation, serializers.PrimaryKeyRelatedField)
