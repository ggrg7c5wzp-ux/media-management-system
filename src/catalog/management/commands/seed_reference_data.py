from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import StorageZone, MediaType, SortBucket


class Command(BaseCommand):
    help = "Seed/normalize reference data (StorageZone, MediaType, SortBucket) in an idempotent way."

    @transaction.atomic
    def handle(self, *args, **options):
        # -------------------------
        # Storage Zones
        # -------------------------
        zone_names = [
            "Garage Main",
            "Office Shelf",
            "Turntable Shelf",
        ]

        zones = {}
        for name in zone_names:
            obj, created = StorageZone.objects.update_or_create(
                name=name,
                defaults={},
            )
            zones[name] = obj
            self.stdout.write(f"{'CREATED' if created else 'OK     '} StorageZone: {name}")

        # -------------------------
        # Sort Buckets (SortKey2 mapping target)
        # -------------------------
        # NOTE: codes are stable machine keys; names are display labels.
        bucket_defs = [
            ("COUNTRY_AMERICANA", "Country & Americana"),
            ("POP", "Pop"),
            ("ROCK", "Rock"),
            ("HARD_ROCK", "Hard Rock, Metal, Punk"),
            ("RB_HIPHOP", "R&B, Hip Hop, Rap, Reggae"),
            ("BLUES_JAZZ", "Blues, Jazz, Vocals"),
            ("ALT_GRUNGE", "Alternative & Grunge"),
            ("SOUNDTRACKS", "Soundtracks"),
            ("COMPS", "Compilations"),
            ("HOLIDAY", "Holiday"),
            ("NEW_WAVE_SYNTH", "New Wave & Synthpop"),
            ("MISC", "Miscellaneous"),
        ]

        for code, name in bucket_defs:
            obj, created = SortBucket.objects.update_or_create(
                code=code,
                defaults={"name": name},
            )
            self.stdout.write(f"{'CREATED' if created else 'OK     '} SortBucket: {code} -> {obj.name}")

        # -------------------------
        # Media Types (SortKey3 mapping target)
        # -------------------------
        # Default zone policy (your v2 defaults)
        media_type_defs = [
            ("Standard LP", "Garage Main"),
            ('7" Vinyl', "Garage Main"),
            ("Cassette Tape", "Garage Main"),
            ("CD", "Garage Main"),
            ("Valuable, Sealed, Special", "Office Shelf"),
            ("Premium Pressings", "Turntable Shelf"),
            ("Box Set", "Turntable Shelf"),
        ]

        for name, zone_name in media_type_defs:
            obj, created = MediaType.objects.update_or_create(
                name=name,
                defaults={"default_zone": zones[zone_name]},
            )
            self.stdout.write(
                f"{'CREATED' if created else 'OK     '} MediaType: {name} -> default zone {obj.default_zone.name}"
            )

        self.stdout.write(self.style.SUCCESS("Reference data seeding complete."))
