"""Tests for additional fields warning in ModelConfig."""
import warnings
from django.db import models
from django.test import TestCase

from statezero.core.config import ModelConfig
from statezero.core.classes import AdditionalField


class MockModel(models.Model):
    """Mock model for testing."""
    name = models.CharField(max_length=100)

    class Meta:
        app_label = 'test'


class TestAdditionalFieldsWarning(TestCase):
    """Tests for the additional fields warning."""

    def test_warns_when_additional_fields_missing_from_fields(self):
        """Should warn when DEBUG=True, fields is a set, and additional_fields not in fields."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')

            ModelConfig(
                model=MockModel,
                fields={'name'},  # missing 'computed_field'
                additional_fields=[
                    AdditionalField(name='computed_field', field=models.CharField(max_length=100), title='Computed Field')
                ],
                DEBUG=True
            )

            self.assertEqual(len(w), 1)
            self.assertIn("computed_field", str(w[0].message))
            self.assertIn("will be ignored", str(w[0].message))

    def test_no_warning_when_fields_is_all(self):
        """Should NOT warn when fields is __all__."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')

            ModelConfig(
                model=MockModel,
                fields='__all__',
                additional_fields=[
                    AdditionalField(name='computed_field', field=models.CharField(max_length=100), title='Computed Field')
                ],
                DEBUG=True
            )

            self.assertEqual(len(w), 0)

    def test_no_warning_when_debug_is_false(self):
        """Should NOT warn when DEBUG=False."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')

            ModelConfig(
                model=MockModel,
                fields={'name'},  # missing 'computed_field'
                additional_fields=[
                    AdditionalField(name='computed_field', field=models.CharField(max_length=100), title='Computed Field')
                ],
                DEBUG=False
            )

            self.assertEqual(len(w), 0)

    def test_no_warning_when_additional_fields_in_fields(self):
        """Should NOT warn when additional_field is in fields."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')

            ModelConfig(
                model=MockModel,
                fields={'name', 'computed_field'},  # includes 'computed_field'
                additional_fields=[
                    AdditionalField(name='computed_field', field=models.CharField(max_length=100), title='Computed Field')
                ],
                DEBUG=True
            )

            self.assertEqual(len(w), 0)

    def test_warns_only_for_missing_fields(self):
        """Should only warn for fields that are actually missing."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')

            ModelConfig(
                model=MockModel,
                fields={'name', 'included_field'},  # includes only 'included_field'
                additional_fields=[
                    AdditionalField(name='included_field', field=models.CharField(max_length=100), title='Included Field'),
                    AdditionalField(name='missing_field', field=models.CharField(max_length=100), title='Missing Field')
                ],
                DEBUG=True
            )

            self.assertEqual(len(w), 1)
            self.assertIn("missing_field", str(w[0].message))
            self.assertNotIn("included_field", str(w[0].message))
