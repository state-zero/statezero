"""
Tests for django-simple-history integration with StateZero.
"""
import unittest
from unittest.mock import patch

from django.test import TestCase

from statezero.adaptors.django.config import config, registry
from statezero.core.config import ModelConfig
from statezero.core.types import ActionType

try:
    from tests.django_app.models import HistoryTestModel
    HAS_SIMPLE_HISTORY = True
except ImportError:
    HAS_SIMPLE_HISTORY = False


@unittest.skipUnless(HAS_SIMPLE_HISTORY, "django-simple-history not installed")
class TestSimpleHistoryIntegration(TestCase):
    """Tests for simple_history integration with StateZero event bus."""

    def setUp(self):
        # Register the historical model with StateZero
        HistoricalModel = HistoryTestModel.history.model
        try:
            registry.register(HistoricalModel, ModelConfig(HistoricalModel))
        except ValueError:
            pass  # Already registered

    @unittest.skip("Signal is now registered in apps.ready()")
    def test_historical_record_created_without_signal_registration(self):
        """
        Without register_simple_history_signals(), StateZero should NOT
        receive events when historical records are created.
        """
        events = []

        def capture_event(action_type, instance):
            events.append((action_type, instance))

        with patch.object(config.event_bus, 'emit_event', side_effect=capture_event):
            # Create a model instance - this triggers simple_history
            instance = HistoryTestModel.objects.create(name="test", value=42)

            # Update it to create another historical record
            instance.value = 100
            instance.save()

        # Filter for historical model events only
        HistoricalModel = HistoryTestModel.history.model
        historical_events = [e for e in events if isinstance(e[1], HistoricalModel)]

        # Without signal registration, we should NOT see historical events
        self.assertEqual(len(historical_events), 0,
            "Historical events should NOT be emitted without register_simple_history_signals()")

    def test_historical_record_created_with_signal_registration(self):
        """
        With register_simple_history_signals(), StateZero SHOULD
        receive events when historical records are created.
        """
        events = []

        def capture_event(action_type, instance):
            events.append((action_type, instance))

        with patch.object(config.event_bus, 'emit_event', side_effect=capture_event):
            # Create a model instance - this triggers simple_history
            instance = HistoryTestModel.objects.create(name="test2", value=42)

            # Update it to create another historical record
            instance.value = 200
            instance.save()

        # Filter for historical model events only
        HistoricalModel = HistoryTestModel.history.model
        historical_events = [e for e in events if isinstance(e[1], HistoricalModel)]

        # With signal registration, we SHOULD see historical events
        self.assertGreater(len(historical_events), 0,
            "Historical events SHOULD be emitted after register_simple_history_signals()")

        # All historical events should be CREATE type
        for action_type, instance in historical_events:
            self.assertEqual(action_type, ActionType.CREATE)


if __name__ == "__main__":
    unittest.main()
