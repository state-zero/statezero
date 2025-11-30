"""
Tests for statezero.adaptors.django.signals helper functions.
"""
import unittest
from unittest.mock import patch

from django.test import TestCase

from statezero.adaptors.django.config import config, registry
from statezero.adaptors.django.signals import (
    notify_created,
    notify_updated,
    notify_deleted,
    notify_bulk_created,
    notify_bulk_updated,
    notify_bulk_deleted,
    post_bulk_create,
    post_bulk_update,
    post_bulk_delete,
    _validate_instance,
    _validate_instances_list,
    _validate_model_registered,
)
from statezero.core.config import ModelConfig
from statezero.core.types import ActionType
from tests.django_app.models import DummyModel, DummyRelatedModel


class TestValidationHelpers(TestCase):
    """Tests for internal validation functions."""

    def test_validate_instance_none(self):
        """Should raise ValueError for None instance."""
        with self.assertRaises(ValueError) as ctx:
            _validate_instance(None)
        self.assertIn("cannot be None", str(ctx.exception))

    def test_validate_instance_not_model(self):
        """Should raise TypeError for non-model objects."""
        with self.assertRaises(TypeError) as ctx:
            _validate_instance("not a model")
        self.assertIn("Expected a Django model instance", str(ctx.exception))

    def test_validate_instance_no_pk(self):
        """Should raise ValueError when require_pk=True and instance has no PK."""
        instance = DummyModel(name="test", value=1)  # Not saved, no PK
        with self.assertRaises(ValueError) as ctx:
            _validate_instance(instance, require_pk=True)
        self.assertIn("has no primary key", str(ctx.exception))

    def test_validate_instance_with_pk(self):
        """Should return model class for valid instance with PK."""
        related = DummyRelatedModel.objects.create(name="rel")
        instance = DummyModel.objects.create(name="test", value=1, related=related)
        model_class = _validate_instance(instance, require_pk=True)
        self.assertEqual(model_class, DummyModel)

    def test_validate_instances_list_empty(self):
        """Should raise ValueError for empty list."""
        with self.assertRaises(ValueError) as ctx:
            _validate_instances_list([])
        self.assertIn("empty list", str(ctx.exception))

    def test_validate_instances_list_wrong_type(self):
        """Should raise TypeError for non-list/tuple."""
        with self.assertRaises(TypeError) as ctx:
            _validate_instances_list("not a list")
        self.assertIn("Expected a list", str(ctx.exception))

    def test_validate_instances_list_mixed_types(self):
        """Should raise TypeError for mixed model types."""
        related = DummyRelatedModel.objects.create(name="rel")
        instance1 = DummyModel.objects.create(name="test1", value=1, related=related)
        instance2 = DummyRelatedModel.objects.create(name="rel2")

        with self.assertRaises(TypeError) as ctx:
            _validate_instances_list([instance1, instance2])
        self.assertIn("same model type", str(ctx.exception))

    def test_validate_model_registered_unregistered(self):
        """Should raise ValueError for unregistered model."""
        class UnregisteredModel:
            class _meta:
                pass
            __name__ = "UnregisteredModel"

        with self.assertRaises(ValueError) as ctx:
            _validate_model_registered(UnregisteredModel)
        self.assertIn("not registered", str(ctx.exception))


class TestSingleInstanceSignals(TestCase):
    """Tests for single-instance signal functions."""

    def setUp(self):
        try:
            registry.register(DummyModel, ModelConfig(DummyModel))
        except ValueError:
            pass  # Already registered

        self.related = DummyRelatedModel.objects.create(name="rel")
        self.instance = DummyModel.objects.create(
            name="test", value=42, related=self.related
        )

    def test_notify_created_emits_event(self):
        """notify_created should emit CREATE event."""
        with patch.object(config.event_bus, 'emit_event') as mock_emit:
            notify_created(self.instance)
            mock_emit.assert_called_once_with(ActionType.CREATE, self.instance)

    def test_notify_updated_emits_event(self):
        """notify_updated should emit UPDATE event."""
        with patch.object(config.event_bus, 'emit_event') as mock_emit:
            notify_updated(self.instance)
            mock_emit.assert_called_once_with(ActionType.UPDATE, self.instance)

    def test_notify_deleted_emits_event(self):
        """notify_deleted should emit DELETE event."""
        with patch.object(config.event_bus, 'emit_event') as mock_emit:
            notify_deleted(self.instance)
            mock_emit.assert_called_once_with(ActionType.DELETE, self.instance)

    def test_notify_created_requires_pk(self):
        """notify_created should reject instances without PK."""
        unsaved = DummyModel(name="unsaved", value=1)
        with self.assertRaises(ValueError) as ctx:
            notify_created(unsaved)
        self.assertIn("no primary key", str(ctx.exception))

    def test_notify_updated_requires_pk(self):
        """notify_updated should reject instances without PK."""
        unsaved = DummyModel(name="unsaved", value=1)
        with self.assertRaises(ValueError) as ctx:
            notify_updated(unsaved)
        self.assertIn("no primary key", str(ctx.exception))

    def test_notify_deleted_requires_pk(self):
        """notify_deleted should reject instances without PK."""
        unsaved = DummyModel(name="unsaved", value=1)
        with self.assertRaises(ValueError) as ctx:
            notify_deleted(unsaved)
        self.assertIn("no primary key", str(ctx.exception))


class TestBulkSignals(TestCase):
    """Tests for bulk signal functions."""

    def setUp(self):
        try:
            registry.register(DummyModel, ModelConfig(DummyModel))
        except ValueError:
            pass  # Already registered

        self.related = DummyRelatedModel.objects.create(name="rel")
        self.instances = [
            DummyModel.objects.create(name=f"test{i}", value=i, related=self.related)
            for i in range(3)
        ]

    def test_notify_bulk_created_emits_event(self):
        """notify_bulk_created should emit BULK_CREATE event."""
        with patch.object(config.event_bus, 'emit_bulk_event') as mock_emit:
            notify_bulk_created(self.instances)
            mock_emit.assert_called_once_with(ActionType.BULK_CREATE, self.instances)

    def test_notify_bulk_updated_emits_event(self):
        """notify_bulk_updated should emit BULK_UPDATE event."""
        with patch.object(config.event_bus, 'emit_bulk_event') as mock_emit:
            notify_bulk_updated(self.instances)
            mock_emit.assert_called_once_with(ActionType.BULK_UPDATE, self.instances)

    def test_notify_bulk_deleted_with_instances(self):
        """notify_bulk_deleted should emit BULK_DELETE event with instances."""
        with patch.object(config.event_bus, 'emit_bulk_event') as mock_emit:
            notify_bulk_deleted(self.instances)
            mock_emit.assert_called_once_with(ActionType.BULK_DELETE, self.instances)

    def test_notify_bulk_deleted_with_model_and_pks(self):
        """notify_bulk_deleted should work with model class and PKs."""
        pks = [inst.pk for inst in self.instances]

        with patch.object(config.event_bus, 'emit_bulk_event') as mock_emit:
            notify_bulk_deleted(DummyModel, pks)

            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            self.assertEqual(call_args[0][0], ActionType.BULK_DELETE)

            # Verify pseudo-instances have correct PKs
            pseudo_instances = call_args[0][1]
            self.assertEqual(len(pseudo_instances), len(pks))
            for pseudo, expected_pk in zip(pseudo_instances, pks):
                self.assertEqual(pseudo.pk, expected_pk)

    def test_notify_bulk_deleted_model_without_pks_raises(self):
        """notify_bulk_deleted with model class requires pks parameter."""
        with self.assertRaises(ValueError) as ctx:
            notify_bulk_deleted(DummyModel)
        self.assertIn("must also provide a list of PKs", str(ctx.exception))

    def test_notify_bulk_deleted_empty_pks_raises(self):
        """notify_bulk_deleted with empty PKs list should raise."""
        with self.assertRaises(ValueError) as ctx:
            notify_bulk_deleted(DummyModel, [])
        self.assertIn("empty list of PKs", str(ctx.exception))

    def test_notify_bulk_deleted_instances_with_pks_param_raises(self):
        """notify_bulk_deleted with instances shouldn't accept pks param."""
        with self.assertRaises(TypeError) as ctx:
            notify_bulk_deleted(self.instances, pks=[1, 2, 3])
        self.assertIn("should only be used when the first argument is a model class", str(ctx.exception))

    def test_notify_bulk_updated_with_queryset(self):
        """notify_bulk_updated should accept QuerySets (objects still exist)."""
        qs = DummyModel.objects.filter(name__startswith="test")

        with patch.object(config.event_bus, 'emit_bulk_event') as mock_emit:
            notify_bulk_updated(qs)
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            self.assertEqual(call_args[0][0], ActionType.BULK_UPDATE)

    def test_notify_bulk_created_rejects_queryset(self):
        """notify_bulk_created should reject QuerySets (must use list)."""
        qs = DummyModel.objects.filter(name__startswith="test")
        with self.assertRaises(TypeError) as ctx:
            notify_bulk_created(qs)
        self.assertIn("Expected a list", str(ctx.exception))


class TestSignalReceivers(TestCase):
    """Tests for receiving bulk signals."""

    def setUp(self):
        try:
            registry.register(DummyModel, ModelConfig(DummyModel))
        except ValueError:
            pass  # Already registered

        self.related = DummyRelatedModel.objects.create(name="rel")
        self.instances = [
            DummyModel.objects.create(name=f"test{i}", value=i, related=self.related)
            for i in range(3)
        ]
        # Track received signals
        self.received_signals = []

    def tearDown(self):
        # Disconnect any handlers we connected
        post_bulk_create.disconnect(dispatch_uid="test_bulk_create")
        post_bulk_update.disconnect(dispatch_uid="test_bulk_update")
        post_bulk_delete.disconnect(dispatch_uid="test_bulk_delete")

    def test_post_bulk_create_signal_received(self):
        """post_bulk_create signal should be dispatched on notify_bulk_created."""
        def handler(sender, instances, **kwargs):
            self.received_signals.append({
                "signal": "post_bulk_create",
                "sender": sender,
                "instances": instances,
            })

        post_bulk_create.connect(handler, sender=DummyModel, dispatch_uid="test_bulk_create")

        notify_bulk_created(self.instances)

        self.assertEqual(len(self.received_signals), 1)
        self.assertEqual(self.received_signals[0]["signal"], "post_bulk_create")
        self.assertEqual(self.received_signals[0]["sender"], DummyModel)
        self.assertEqual(self.received_signals[0]["instances"], self.instances)

    def test_post_bulk_update_signal_received(self):
        """post_bulk_update signal should be dispatched on notify_bulk_updated."""
        def handler(sender, instances, **kwargs):
            self.received_signals.append({
                "signal": "post_bulk_update",
                "sender": sender,
                "instances": instances,
            })

        post_bulk_update.connect(handler, sender=DummyModel, dispatch_uid="test_bulk_update")

        notify_bulk_updated(self.instances)

        self.assertEqual(len(self.received_signals), 1)
        self.assertEqual(self.received_signals[0]["signal"], "post_bulk_update")
        self.assertEqual(self.received_signals[0]["sender"], DummyModel)
        self.assertEqual(self.received_signals[0]["instances"], self.instances)

    def test_post_bulk_delete_signal_received(self):
        """post_bulk_delete signal should be dispatched on notify_bulk_deleted."""
        def handler(sender, instances, pks, **kwargs):
            self.received_signals.append({
                "signal": "post_bulk_delete",
                "sender": sender,
                "instances": instances,
                "pks": pks,
            })

        post_bulk_delete.connect(handler, sender=DummyModel, dispatch_uid="test_bulk_delete")

        notify_bulk_deleted(self.instances)

        self.assertEqual(len(self.received_signals), 1)
        self.assertEqual(self.received_signals[0]["signal"], "post_bulk_delete")
        self.assertEqual(self.received_signals[0]["sender"], DummyModel)
        expected_pks = [inst.pk for inst in self.instances]
        self.assertEqual(self.received_signals[0]["pks"], expected_pks)

    def test_post_bulk_delete_with_pks_signal_received(self):
        """post_bulk_delete should work when called with model + pks."""
        def handler(sender, instances, pks, **kwargs):
            self.received_signals.append({
                "signal": "post_bulk_delete",
                "sender": sender,
                "pks": pks,
            })

        post_bulk_delete.connect(handler, sender=DummyModel, dispatch_uid="test_bulk_delete")

        pks = [inst.pk for inst in self.instances]
        notify_bulk_deleted(DummyModel, pks)

        self.assertEqual(len(self.received_signals), 1)
        self.assertEqual(self.received_signals[0]["pks"], pks)

    def test_signal_only_received_for_matching_sender(self):
        """Signal should only be received when sender matches."""
        def handler(sender, instances, **kwargs):
            self.received_signals.append({"sender": sender})

        # Connect to DummyRelatedModel, not DummyModel
        post_bulk_create.connect(handler, sender=DummyRelatedModel, dispatch_uid="test_bulk_create")

        # Trigger for DummyModel - handler should NOT be called
        notify_bulk_created(self.instances)

        self.assertEqual(len(self.received_signals), 0)


if __name__ == "__main__":
    unittest.main()
