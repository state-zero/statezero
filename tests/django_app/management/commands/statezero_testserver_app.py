import os
from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, call_command
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = "Start the StateZero test server using the test app settings."

    def add_arguments(self, parser):
        parser.add_argument("--addrport", dest="addrport", default="8000")
        parser.add_argument(
            "--skip-migrate",
            action="store_true",
            help="Skip running migrations before starting the server.",
        )

    def handle(self, *args, **options):
        # Force test settings module
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")
        # Ensure test mode is enabled for the process
        os.environ.setdefault("STATEZERO_TEST_MODE", "1")

        addrport = options.get("addrport") or "8000"
        if not options.get("skip_migrate"):
            call_command("migrate", interactive=False, run_syncdb=True)

        user_model = get_user_model()
        admin_user, _ = user_model.objects.get_or_create(
            username="test_user", defaults={"email": "test@example.com"}
        )
        admin_user.set_password("test123")
        admin_user.is_staff = True
        admin_user.is_superuser = True
        admin_user.save()

        admin_token, _ = Token.objects.get_or_create(
            user=admin_user, defaults={"key": "testtoken123"}
        )
        if admin_token.key != "testtoken123":
            admin_token.key = "testtoken123"
            admin_token.save()

        non_admin_user, _ = user_model.objects.get_or_create(
            username="non_admin", defaults={"email": "nonadmin@example.com"}
        )
        non_admin_user.set_password("test123")
        non_admin_user.is_staff = False
        non_admin_user.is_superuser = False
        non_admin_user.save()

        non_admin_token, _ = Token.objects.get_or_create(
            user=non_admin_user, defaults={"key": "nonadmintoken123"}
        )
        if non_admin_token.key != "nonadmintoken123":
            non_admin_token.key = "nonadmintoken123"
            non_admin_token.save()

        self.stdout.write(
            self.style.SUCCESS(
                "Test auth ready: user=test_user token=testtoken123; "
                "non_admin token=nonadmintoken123"
            )
        )
        call_command("statezero_testserver", addrport=addrport)
