from django.apps import AppConfig


class TestsConfig(AppConfig):
    name = "tests.django_app"
    verbose_name = "Test App"

    def ready(self):
        from statezero.adaptors.django.extensions.simple_history import (
            register_simple_history_signals
        )
        register_simple_history_signals()
