from django.core.management.base import BaseCommand

from statezero.client.generate import generate_client


class Command(BaseCommand):
    help = "Generate a standalone Python client package from registered StateZero models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default="./sz",
            help="Output directory for the generated package (default: ./sz)",
        )

    def handle(self, *args, **options):
        output_dir = options["output"]
        self.stdout.write(f"Generating StateZero Python client to {output_dir}/ ...")
        result = generate_client(output_dir)
        self.stdout.write(self.style.SUCCESS(f"Client generated at {result}"))
