"""
Django Simple History integration for StateZero.

Django Simple History uses its own signals to create historical records,
which bypass Django's standard post_save signals. This module provides
a helper to wire up those signals to StateZero.
"""


def register_simple_history_signals() -> None:
    """
    Wire up Django Simple History to emit StateZero events.

    Call this function in your AppConfig.ready() method to ensure StateZero
    receives events when historical records are created.

    Note: You must register your HistoricalX models with StateZero for this
    to have any effect. Historical models are separate Django models
    (e.g., HistoricalReservation for Reservation).

    Raises:
        ImportError: If django-simple-history is not installed

    Example:
        # In your apps.py
        class MyAppConfig(AppConfig):
            name = 'myapp'

            def ready(self):
                from statezero.adaptors.django.extensions.simple_history import (
                    register_simple_history_signals
                )
                register_simple_history_signals()
    """
    try:
        from simple_history.signals import post_create_historical_record
    except ImportError:
        raise ImportError(
            "django-simple-history is not installed. "
            "Install it with: pip install django-simple-history"
        )

    from statezero.adaptors.django.config import registry
    from statezero.adaptors.django.signals import notify_created

    def notify_statezero_of_historical_record(sender, instance, history_instance, **kwargs):
        """Notify StateZero when a historical record is created for a registered model."""
        if history_instance.__class__ in registry._models_config:
            notify_created(history_instance)

    post_create_historical_record.connect(
        notify_statezero_of_historical_record,
        dispatch_uid="statezero_simple_history"
    )
