from django.core.management.base import BaseCommand
from catalog.models import StorageZone, MediaType


class Command(BaseCommand):
    help = "Seed StorageZones and MediaTypes (idempotent)."

    def handle(self, *args, **options):
        zones = [
            ("GARAGE_MAIN", "Garage Main"),
            ("OFFICE_SHELF", "Office Shelf"),
            ("TURNTABLE_SHELF", "Turntable Shelf"),
        ]

        zone_objs = {}
        for code, name in zones:
            obj, _ = StorageZone.objects.update_or_create(
                code=code,
                defaults={"name": name},
            )
            zone_objs[code] = obj

        media_types = [
            ("Standard LP", "GARAGE_MAIN"),
            ("Valuable, Sealed, Special", "OFFICE_SHELF"),
            ("Premium Pressings", "TURNTABLE_SHELF"),
            ("Box Set", "TURNTABLE_SHELF"),
            ('7" Vinyl', "GARAGE_MAIN"),
            ("Cassette Tape", "GARAGE_MAIN"),
            ("CD", "GARAGE_MAIN"),
        ]

        for name, zone_code in media_types:
            MediaType.objects.update_or_create(
                name=name,
                defaults={"default_zone": zone_objs[zone_code]},
            )

        self.stdout.write(self.style.SUCCESS("Seeded StorageZones + MediaTypes."))
