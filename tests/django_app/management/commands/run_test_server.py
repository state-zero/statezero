import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token


class Command(BaseCommand):
    help = "Runs a test server with a clean SQLite database and fixed test users (admin and non-admin)"

    def handle(self, *args, **kwargs):
        # Set up SQLite test database path
        test_db_path = "test_db.sqlite3"

        # Remove existing test database if it exists
        if os.path.exists(test_db_path):
            os.remove(test_db_path)

        # Only override the specific database settings we need
        from django.conf import settings

        settings.TEST_DB_PATH = test_db_path

        settings.DATABASES["default"].update(
            {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": test_db_path,
            }
        )

        settings.STATEZERO_E2E_TESTING = True

        # Run migrations on clean database
        call_command("migrate")

        User = get_user_model()

        # Create or update admin test user with fixed token
        admin_user, _ = User.objects.get_or_create(
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

        # Create or update non-admin test user with fixed token
        non_admin_user, _ = User.objects.get_or_create(
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

        # Print credentials with green styling
        self.stdout.write("\n" + self.style.SUCCESS("=" * 50))
        self.stdout.write(
            self.style.SUCCESS(
                "\nTest environment ready!\n"
                "Admin user credentials:\n"
                "  Username: test_user\n"
                "  Email: test@example.com\n"
                "  Password: test123\n"
                "  Token: testtoken123\n\n"
                "Non-admin user credentials:\n"
                "  Username: non_admin\n"
                "  Email: nonadmin@example.com\n"
                "  Password: test123\n"
                "  Token: nonadmintoken123\n"
            )
        )
        self.stdout.write(self.style.SUCCESS("=" * 50) + "\n")

        # Run the development server (with autoreload disabled)
        self.stdout.write("Starting development server...\n")
        call_command("runserver", "--noreload")
