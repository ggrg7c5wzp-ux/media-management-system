from django.core.management.base import BaseCommand

from catalog.models import MediaItem
from catalog.services.binning import assign_logical_bin


class Command(BaseCommand):
    help = "Assign logical bins to media items (deterministic first-pass)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Do not persist changes.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        items = MediaItem.objects.select_related(
            "artist", "media_type", "zone_override", "bucket"
        ).all()

        for item in items:
            result = assign_logical_bin(item, persist=not dry_run)
            self.stdout.write(f"{item} -> {result.logical_bin} ({result.reason})")

        self.stdout.write(self.style.SUCCESS("Assignment complete."))
