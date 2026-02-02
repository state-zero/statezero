from django.conf import settings
from django.core.management import BaseCommand, call_command


class Command(BaseCommand):
    help = "Start a StateZero Django test server with STATEZERO_TEST_MODE enabled."

    def add_arguments(self, parser):
        parser.add_argument("--addrport", dest="addrport", default="8000")
        parser.add_argument("--settings", dest="settings", default=None)

    def handle(self, *args, **options):
        if options.get("settings"):
            settings_module = options["settings"]
            import os
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", settings_module)

        # Ensure test mode is enabled
        setattr(settings, "STATEZERO_TEST_MODE", True)

        addrport = options.get("addrport") or "8000"
        self.stdout.write(self.style.SUCCESS(
            f"Starting StateZero test server on {addrport} (STATEZERO_TEST_MODE=1)"
        ))
        call_command("runserver", addrport)
