from django.conf import settings
from django.core.management import BaseCommand, call_command
from django.utils.module_loading import import_string


class Command(BaseCommand):
    help = "Start a StateZero Django test server with STATEZERO_TEST_MODE enabled."

    def add_arguments(self, parser):
        parser.add_argument("--addrport", dest="addrport", default="8000")

    def handle(self, *args, **options):
        # Ensure test mode is enabled
        setattr(settings, "STATEZERO_TEST_MODE", True)

        addrport = options.get("addrport") or "8000"
        startup_hook = getattr(settings, "STATEZERO_TEST_STARTUP_HOOK", None)
        if startup_hook:
            try:
                hook = startup_hook if callable(startup_hook) else import_string(startup_hook)
                hook()
            except Exception as exc:
                self.stderr.write(
                    self.style.ERROR(
                        f"STATEZERO_TEST_STARTUP_HOOK failed: {exc}"
                    )
                )
                raise
        self.stdout.write(self.style.SUCCESS(
            f"Starting StateZero test server on {addrport} (STATEZERO_TEST_MODE=1)"
        ))
        call_command("runserver", addrport)
